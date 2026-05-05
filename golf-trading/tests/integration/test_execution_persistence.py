from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.execution.persistence import (
    persist_clv,
    persist_placement,
    persist_settlement,
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.execution.placement import log_placement
from src.execution.settlement import settle_placement
from src.execution.tickets import generate_ticket
from src.monitoring.attribution import record_attribution_for_bet_row
from src.monitoring.clv import compute_clv
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet
from src.storage.models import BetAttribution, BetCandidate, Player, Tournament

NOW = datetime(2024, 3, 11, tzinfo=UTC)


def _candidate(db_session) -> BetCandidate:
    tournament = Tournament(name="The Players Championship", tour="pga")
    player = Player(datagolf_player_id="scheffler", name_canonical="Scottie Scheffler")
    opponent = Player(datagolf_player_id="mcIlroy", name_canonical="Rory McIlroy")
    db_session.add_all([tournament, player, opponent])
    db_session.flush()

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="matchup_2ball",
        side="scheffler",
        player_id_1=player.player_id,
        player_id_2=opponent.player_id,
        book="dk",
        fair_prob=0.56,
        book_prob=0.51,
        book_american_odds=-110,
        edge_pct=0.05,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash="candidate-hash",
        created_at=NOW,
    )
    db_session.add(candidate)
    db_session.flush()
    return candidate


def _ticket():
    edge = EdgeResult(
        datagolf_id="scheffler",
        opponent_id="mcIlroy",
        market_type="matchup_2ball",
        book_id="dk",
        fair_prob=0.56,
        book_no_vig_prob=0.51,
        edge=0.05,
        sleeve="core",
        passes_threshold=True,
        book_american_odds=-110,
    )
    sizing = size_core_bet(
        edge=edge,
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    return generate_ticket(edge, sizing, tournament_id="players_2024", created_at=NOW)


def test_persist_full_execution_artifact_chain(db_session) -> None:
    candidate = _candidate(db_session)
    ticket = _ticket()
    ticket_row = persist_ticket(db_session, ticket, candidate_id=candidate.candidate_id)

    placement = log_placement(ticket, actual_american_odds=-105, placed_at=NOW)
    placed_row = persist_placement(db_session, placement, ticket_id=ticket_row.ticket_id)

    settlement = settle_placement(placement, result="win", settled_at=NOW)
    outcome_row = persist_settlement(db_session, settlement, bet_id=placed_row.bet_id)

    clv = compute_clv(ticket, placement, closing_american_odds=-125, captured_at=NOW)
    clv_row = persist_clv(db_session, clv, bet_id=placed_row.bet_id)

    assert ticket_row.ticket_id is not None
    assert ticket_row.inputs_hash == ticket.inputs_hash
    assert placed_row.actual_american_odds == -105
    assert placed_row.inputs_hash == placement.inputs_hash
    assert outcome_row.profit_loss == settlement.profit_loss
    assert clv_row.clv_raw == clv.clv_raw


def test_rejected_placement_is_not_persisted_as_placed_bet(db_session) -> None:
    candidate = _candidate(db_session)
    ticket = _ticket()
    ticket_row = persist_ticket(db_session, ticket, candidate_id=candidate.candidate_id)
    placement = log_placement(
        ticket,
        rejected=True,
        rejection_reason="Line moved below threshold.",
        placed_at=NOW,
    )

    with pytest.raises(ValueError, match="Only placed bets"):
        persist_placement(db_session, placement, ticket_id=ticket_row.ticket_id)


def test_operator_row_helpers_place_settle_and_record_clv(db_session) -> None:
    candidate = _candidate(db_session)
    ticket = _ticket()
    ticket_row = persist_ticket(db_session, ticket, candidate_id=candidate.candidate_id)

    placed_row = place_ticket_row(
        db_session,
        ticket_row,
        candidate,
        actual_american_odds=-102,
        actual_stake=125.0,
        placed_at=NOW,
        notes="manual placement",
    )
    outcome_row = settle_bet_row(
        db_session,
        placed_row,
        result="loss",
        settled_at=NOW,
        notes="missed",
    )
    clv_row = record_clv_for_bet_row(
        db_session,
        placed_row,
        ticket_row,
        candidate,
        closing_american_odds=-120,
        captured_at=NOW,
    )

    assert placed_row.ticket_id == ticket_row.ticket_id
    assert placed_row.book == "dk"
    assert outcome_row.profit_loss == -125.0
    assert clv_row.clv_model == pytest.approx(candidate.fair_prob - clv_row.closing_implied_prob)


def test_operator_row_helpers_separate_promo_pnl(db_session) -> None:
    candidate = _candidate(db_session)
    ticket_row = persist_ticket(db_session, _ticket(), candidate_id=candidate.candidate_id)
    placed_row = place_ticket_row(
        db_session,
        ticket_row,
        candidate,
        actual_american_odds=-105,
        actual_stake=100.0,
        placed_at=NOW,
        bet_class="BOOSTED_ODDS",
        boost_terms_json='{"profit_boost_multiplier": 1.5}',
    )
    outcome_row = settle_bet_row(db_session, placed_row, result="win", settled_at=NOW)

    assert placed_row.bet_class == "BOOSTED_ODDS"
    assert outcome_row.profit_loss_raw == pytest.approx(95.24, abs=0.01)
    assert outcome_row.profit_loss_realized == pytest.approx(142.86, abs=0.01)
    assert outcome_row.profit_loss == outcome_row.profit_loss_realized


def test_operator_row_helpers_record_attribution(db_session) -> None:
    candidate = _candidate(db_session)
    ticket_row = persist_ticket(db_session, _ticket(), candidate_id=candidate.candidate_id)
    placed_row = place_ticket_row(
        db_session,
        ticket_row,
        candidate,
        actual_american_odds=-105,
        actual_stake=100.0,
        placed_at=NOW,
    )
    outcome_row = settle_bet_row(db_session, placed_row, result="win", settled_at=NOW)

    attribution = record_attribution_for_bet_row(
        db_session,
        placed_row,
        ticket_row,
        candidate,
        outcome_row,
        flat_stake=100.0,
        created_at=NOW,
    )
    total = attribution.model_alpha + attribution.execution_drift + attribution.sizing_alpha + attribution.variance

    assert attribution.realized_profit_loss == outcome_row.profit_loss
    assert total == pytest.approx(outcome_row.profit_loss)
    assert db_session.query(BetAttribution).count() == 1

    with pytest.raises(ValueError, match="already has attribution"):
        record_attribution_for_bet_row(
            db_session,
            placed_row,
            ticket_row,
            candidate,
            outcome_row,
            flat_stake=100.0,
            created_at=NOW,
        )


def test_operator_row_helpers_reject_duplicate_actions(db_session) -> None:
    candidate = _candidate(db_session)
    ticket_row = persist_ticket(db_session, _ticket(), candidate_id=candidate.candidate_id)
    placed_row = place_ticket_row(db_session, ticket_row, candidate, placed_at=NOW)

    with pytest.raises(ValueError, match="already has a placed bet"):
        place_ticket_row(db_session, ticket_row, candidate, placed_at=NOW)

    settle_bet_row(db_session, placed_row, result="push", settled_at=NOW)
    with pytest.raises(ValueError, match="already has a settlement"):
        settle_bet_row(db_session, placed_row, result="push", settled_at=NOW)

    record_clv_for_bet_row(
        db_session,
        placed_row,
        ticket_row,
        candidate,
        closing_american_odds=-110,
        captured_at=NOW,
    )
    with pytest.raises(ValueError, match="already has a CLV snapshot"):
        record_clv_for_bet_row(
            db_session,
            placed_row,
            ticket_row,
            candidate,
            closing_american_odds=-110,
            captured_at=NOW,
        )
