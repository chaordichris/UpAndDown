from __future__ import annotations

from datetime import UTC, datetime

from src.execution.candidates import build_ticket_from_candidate, ticket_unticketed_candidates
from src.execution.persistence import persist_ticket
from src.storage.models import BetCandidate, Player, Tournament

NOW = datetime(2024, 3, 11, tzinfo=UTC)


def _candidate(
    db_session,
    *,
    market_type: str = "matchup_2ball",
    edge_pct: float = 0.05,
    datagolf_id: str = "scheffler",
    edge_sd: float | None = None,
    p_value: float | None = None,
    passes_fdr: bool = True,
    with_opponent: bool = True,
) -> tuple[BetCandidate, Player, Player | None]:
    tournament = Tournament(name="The Players Championship", tour="pga")
    player = Player(datagolf_player_id=datagolf_id, name_canonical=datagolf_id.title())
    opponent = (
        Player(datagolf_player_id=f"{datagolf_id}-opp", name_canonical=f"{datagolf_id.title()} Opp")
        if with_opponent
        else None
    )
    db_session.add_all([row for row in [tournament, player, opponent] if row is not None])
    db_session.flush()

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type=market_type,
        side=datagolf_id,
        player_id_1=player.player_id,
        player_id_2=opponent.player_id if opponent is not None else None,
        book="dk",
        fair_prob=0.56,
        book_prob=0.56 - edge_pct,
        book_american_odds=-110,
        edge_pct=edge_pct,
        edge_sd=edge_sd,
        p_value=p_value,
        passes_fdr=passes_fdr,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash=f"candidate-{market_type}-{edge_pct}-{datagolf_id}",
        created_at=NOW,
    )
    db_session.add(candidate)
    db_session.flush()
    return candidate, player, opponent


def _build_ticket(
    candidate,
    player,
    opponent,
    *,
    book_odds: int | None = None,
    posterior_kelly_enabled: bool = False,
    fdr_enabled: bool = False,
):
    return build_ticket_from_candidate(
        candidate,
        player,
        opponent_player=opponent,
        book_american_odds=book_odds,
        total_bankroll=25_000,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
        posterior_kelly_enabled=posterior_kelly_enabled,
        fdr_enabled=fdr_enabled,
        created_at=NOW,
    )


def test_build_ticket_from_core_candidate_and_persist(db_session) -> None:
    candidate, player, opponent = _candidate(db_session, edge_pct=0.05)

    ticket = _build_ticket(candidate, player, opponent)
    row = persist_ticket(db_session, ticket, candidate_id=candidate.candidate_id)

    assert ticket.approved
    assert ticket.recommended_stake == 137.5
    assert ticket.datagolf_id == "scheffler"
    assert ticket.opponent_id == "scheffler-opp"
    assert row.ticket_id is not None
    assert row.proposed_american_odds == -110


def test_build_ticket_from_candidate_allows_odds_override(db_session) -> None:
    candidate, player, opponent = _candidate(db_session, edge_pct=0.05)

    ticket = _build_ticket(candidate, player, opponent, book_odds=-108)

    assert ticket.recommended_american_odds == -108
    assert ticket.approved


def test_build_ticket_from_candidate_rejects_below_threshold(db_session) -> None:
    candidate, player, opponent = _candidate(db_session, edge_pct=0.02)

    ticket = _build_ticket(candidate, player, opponent)

    assert not ticket.approved
    assert ticket.recommended_stake == 0.0
    assert ticket.rejection_reason == "Edge below minimum threshold."


def test_build_ticket_from_candidate_respects_fdr_flag(db_session) -> None:
    candidate, player, opponent = _candidate(
        db_session,
        edge_pct=0.05,
        edge_sd=0.02,
        p_value=0.12,
        passes_fdr=False,
    )

    legacy_ticket = _build_ticket(candidate, player, opponent, fdr_enabled=False)
    gated_ticket = _build_ticket(candidate, player, opponent, fdr_enabled=True)

    assert legacy_ticket.approved
    assert not gated_ticket.approved
    assert gated_ticket.rejection_reason == "Candidate failed FDR control."


def test_build_ticket_from_candidate_can_use_posterior_kelly(db_session) -> None:
    candidate, player, opponent = _candidate(db_session, edge_pct=0.05, edge_sd=0.04)

    legacy_ticket = _build_ticket(candidate, player, opponent)
    posterior_ticket = _build_ticket(
        candidate,
        player,
        opponent,
        posterior_kelly_enabled=True,
    )

    assert posterior_ticket.approved
    assert posterior_ticket.sizing_method == "posterior_kelly"
    assert posterior_ticket.recommended_stake < legacy_ticket.recommended_stake


def test_build_ticket_from_convex_candidate_uses_fixed_unit(db_session) -> None:
    candidate, player, opponent = _candidate(
        db_session,
        market_type="outright_win",
        edge_pct=0.09,
    )

    ticket = _build_ticket(candidate, player, opponent, book_odds=2500)

    assert ticket.approved
    assert ticket.sleeve == "convex"
    assert ticket.sizing_method == "fixed_unit"
    assert ticket.recommended_stake == 12.5


def test_build_ticket_from_outright_candidate_without_opponent_uses_fixed_unit(db_session) -> None:
    candidate, player, opponent = _candidate(
        db_session,
        market_type="outright_win",
        edge_pct=0.09,
        with_opponent=False,
    )

    ticket = _build_ticket(candidate, player, opponent, book_odds=2500)

    assert ticket.approved
    assert ticket.sleeve == "convex"
    assert ticket.opponent_id is None
    assert ticket.sizing_method == "fixed_unit"
    assert ticket.recommended_stake == 12.5


def test_build_ticket_from_top20_candidate_without_opponent(db_session) -> None:
    candidate, player, opponent = _candidate(
        db_session,
        market_type="top_20",
        edge_pct=0.05,
        with_opponent=False,
    )

    ticket = _build_ticket(candidate, player, opponent)

    assert ticket.approved
    assert ticket.sleeve == "core"
    assert ticket.opponent_id is None
    assert ticket.recommended_stake > 0


def test_ticket_unticketed_candidates_skips_existing_ticket(db_session) -> None:
    first, first_player, first_opponent = _candidate(db_session, datagolf_id="scheffler")
    second, _, _ = _candidate(db_session, datagolf_id="rahm")
    existing_ticket = _build_ticket(first, first_player, first_opponent)
    persist_ticket(db_session, existing_ticket, candidate_id=first.candidate_id)

    rows = ticket_unticketed_candidates(
        db_session,
        total_bankroll=25_000,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
        created_at=NOW,
    )

    assert len(rows) == 1
    assert rows[0].candidate_id == second.candidate_id


def test_ticket_unticketed_candidates_respects_limit(db_session) -> None:
    first, _, _ = _candidate(db_session, datagolf_id="scheffler")
    _candidate(db_session, datagolf_id="rahm")

    rows = ticket_unticketed_candidates(
        db_session,
        total_bankroll=25_000,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
        limit=1,
        created_at=NOW,
    )

    assert len(rows) == 1
    assert rows[0].candidate_id == first.candidate_id
