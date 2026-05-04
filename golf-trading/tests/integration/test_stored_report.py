from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO

import pytest

from src.execution.persistence import (
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.execution.tickets import generate_ticket
from src.monitoring.attribution import record_attribution_for_bet_row
from src.monitoring.reports import (
    build_stored_paper_trade_report,
    export_tickets_csv,
    render_open_actions,
    render_stored_report,
    render_ticket_detail,
)
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet
from src.storage.models import BetCandidate, Player, Tournament

NOW = datetime(2024, 3, 11, tzinfo=UTC)


def _candidate(db_session, *, edge_pct: float = 0.05) -> BetCandidate:
    tournament = Tournament(name="The Players Championship", tour="pga")
    player = Player(datagolf_player_id=f"player-{edge_pct}", name_canonical=f"Player {edge_pct}")
    opponent = Player(datagolf_player_id=f"opp-{edge_pct}", name_canonical=f"Opponent {edge_pct}")
    db_session.add_all([tournament, player, opponent])
    db_session.flush()

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="matchup_2ball",
        side=player.datagolf_player_id,
        player_id_1=player.player_id,
        player_id_2=opponent.player_id,
        book="dk",
        fair_prob=0.56,
        book_prob=0.56 - edge_pct,
        book_american_odds=-110,
        edge_pct=edge_pct,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash=f"candidate-{edge_pct}",
        created_at=NOW,
    )
    db_session.add(candidate)
    db_session.flush()
    return candidate


def _ticket(candidate: BetCandidate, *, passes_threshold: bool = True):
    edge = EdgeResult(
        datagolf_id=candidate.side,
        opponent_id="opponent",
        market_type="matchup_2ball",
        book_id="dk",
        fair_prob=candidate.fair_prob,
        book_no_vig_prob=candidate.book_prob,
        edge=candidate.edge_pct,
        sleeve="core",
        passes_threshold=passes_threshold,
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


def test_build_stored_report_mixed_open_settled_and_clv(db_session) -> None:
    settled_candidate = _candidate(db_session, edge_pct=0.05)
    settled_ticket = persist_ticket(
        db_session,
        _ticket(settled_candidate),
        candidate_id=settled_candidate.candidate_id,
    )
    placed = place_ticket_row(
        db_session,
        settled_ticket,
        settled_candidate,
        actual_stake=100.0,
        actual_american_odds=-105,
        placed_at=NOW,
    )
    outcome = settle_bet_row(db_session, placed, result="win", settled_at=NOW)
    record_clv_for_bet_row(
        db_session,
        placed,
        settled_ticket,
        settled_candidate,
        closing_american_odds=-125,
        captured_at=NOW,
    )
    record_attribution_for_bet_row(
        db_session,
        placed,
        settled_ticket,
        settled_candidate,
        outcome,
        flat_stake=100.0,
        created_at=NOW,
    )

    open_candidate = _candidate(db_session, edge_pct=0.04)
    persist_ticket(db_session, _ticket(open_candidate), candidate_id=open_candidate.candidate_id)

    report = build_stored_paper_trade_report(db_session)

    assert report.ticket_count == 2
    assert report.approved_count == 2
    assert report.open_ticket_count == 1
    assert report.placed_count == 1
    assert report.settled_count == 1
    assert report.pending_settlement_count == 0
    assert report.clv_count == 1
    assert report.missing_clv_count == 0
    assert report.total_staked == 100.0
    assert report.total_profit_loss == pytest.approx(95.24, abs=0.01)
    assert report.roi == pytest.approx(0.9524, abs=0.001)
    assert report.average_edge == pytest.approx(0.045)
    assert report.positive_clv_rate == 1.0
    assert report.attribution_count == 1
    assert report.model_alpha == 5.0
    assert report.execution_drift == 4.33
    assert "Attribution rows: 1" in render_stored_report(report)


def test_ticket_detail_csv_and_open_actions(db_session) -> None:
    open_candidate = _candidate(db_session, edge_pct=0.05)
    open_ticket = persist_ticket(
        db_session,
        _ticket(open_candidate),
        candidate_id=open_candidate.candidate_id,
    )

    pending_candidate = _candidate(db_session, edge_pct=0.04)
    pending_ticket = persist_ticket(
        db_session,
        _ticket(pending_candidate),
        candidate_id=pending_candidate.candidate_id,
    )
    pending_bet = place_ticket_row(
        db_session,
        pending_ticket,
        pending_candidate,
        actual_stake=50.0,
        actual_american_odds=-105,
        placed_at=NOW,
    )

    rejected_candidate = _candidate(db_session, edge_pct=0.02)
    rejected_ticket = persist_ticket(
        db_session,
        _ticket(rejected_candidate, passes_threshold=False),
        candidate_id=rejected_candidate.candidate_id,
    )

    detail = render_ticket_detail(db_session, open_ticket.ticket_id)
    csv_text = export_tickets_csv(db_session, unplaced_only=True, approved_only=True)
    actions = render_open_actions(db_session)

    assert f"Ticket {open_ticket.ticket_id}" in detail
    assert "The Players Championship" in detail
    assert "ticket_id,candidate_id,status,approved" in csv_text
    exported_rows = list(csv.DictReader(StringIO(csv_text)))
    exported_ticket_ids = {int(row["ticket_id"]) for row in exported_rows}
    assert open_ticket.ticket_id in exported_ticket_ids
    assert pending_ticket.ticket_id not in exported_ticket_ids
    assert rejected_ticket.ticket_id not in exported_ticket_ids
    assert "Tickets to place: 1" in actions
    assert f"bet_id={pending_bet.bet_id}" in actions
    assert "Bets pending settlement: 1" in actions
    assert "Bets missing CLV: 1" in actions
    assert "Bets missing attribution: 0" in actions
    assert "Rejected tickets: 1" in actions


def test_stored_report_separates_strategy_and_promo_pnl(db_session) -> None:
    candidate = _candidate(db_session, edge_pct=0.05)
    ticket = persist_ticket(
        db_session,
        _ticket(candidate),
        candidate_id=candidate.candidate_id,
    )
    placed = place_ticket_row(
        db_session,
        ticket,
        candidate,
        actual_stake=100.0,
        actual_american_odds=-105,
        placed_at=NOW,
        bet_class="BOOSTED_ODDS",
        boost_terms_json='{"profit_boost_multiplier": 1.5}',
    )
    settle_bet_row(db_session, placed, result="win", settled_at=NOW)

    report = build_stored_paper_trade_report(db_session)
    rendered = render_stored_report(report)

    assert report.strategy_profit_loss == pytest.approx(95.24, abs=0.01)
    assert report.promo_profit_loss == pytest.approx(47.62, abs=0.01)
    assert report.total_profit_loss == pytest.approx(142.86, abs=0.01)
    assert "Strategy P&L: $95.24" in rendered
    assert "Promo P&L: $47.62" in rendered
