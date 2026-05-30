"""Unit tests for shadow-live guardrails and reporting separation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.execution.persistence import place_ticket_row, persist_ticket
from src.execution.shadow_live import (
    SHADOW_LIVE_METHOD,
    ShadowLiveGuardrail,
    check_shadow_live_placement,
    get_tournament_shadow_live_staked,
)
from src.execution.tickets import generate_ticket
from src.monitoring.reports import (
    build_phase3_evidence_report,
    build_shadow_live_summary,
    build_stored_paper_trade_report,
)
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet
from src.storage.db import get_session, init_db
from src.storage.models import BetCandidate, BetOutcome, BetTicket, PlacedBet, Player, Tournament

NOW = datetime(2026, 5, 7, tzinfo=UTC)

_ENABLED = ShadowLiveGuardrail(
    enabled=True,
    starting_bankroll_dollars=500.0,
    per_bet_cap_dollars=25.0,
    per_tournament_cap_dollars=100.0,
)
_DISABLED = ShadowLiveGuardrail(
    enabled=False,
    starting_bankroll_dollars=500.0,
    per_bet_cap_dollars=25.0,
    per_tournament_cap_dollars=100.0,
)


# ---------------------------------------------------------------------------
# Guardrail — pure logic (no DB needed)
# ---------------------------------------------------------------------------

def test_guardrail_disabled_raises(tmp_path) -> None:
    """Disabled guardrail blocks placement even with valid stake."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        with pytest.raises(ValueError, match="disabled"):
            check_shadow_live_placement(session, _DISABLED, 10.0, tournament_id=1)


def test_guardrail_zero_stake_raises(tmp_path) -> None:
    """Zero or negative stake is always rejected."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        with pytest.raises(ValueError, match="positive"):
            check_shadow_live_placement(session, _ENABLED, 0.0, tournament_id=1)


def test_guardrail_over_per_bet_cap_raises(tmp_path) -> None:
    """Stake exceeding per-bet cap is blocked."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        with pytest.raises(ValueError, match="per-bet cap"):
            check_shadow_live_placement(session, _ENABLED, 26.0, tournament_id=1)


def test_guardrail_over_tournament_cap_raises(tmp_path) -> None:
    """Placement that would push tournament total over cap is blocked."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        tournament, candidate, ticket = _make_candidate_and_ticket(session)
        # Place 4 × $25 shadow-live bets to get to $100 (the cap)
        for i in range(4):
            _place_shadow_live(session, ticket if i == 0 else _extra_ticket(session, candidate), 25.0)
        session.flush()
        # Fifth bet at $1 would push total to $101, exceeding the $100 cap
        with pytest.raises(ValueError, match="per-tournament"):
            check_shadow_live_placement(session, _ENABLED, 1.0, tournament.tournament_id)


def test_guardrail_valid_placement_passes(tmp_path) -> None:
    """Valid stake under all caps does not raise."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        tournament, _, _ = _make_candidate_and_ticket(session)
        # No prior bets — $20 well within both caps
        check_shadow_live_placement(session, _ENABLED, 20.0, tournament.tournament_id)


# ---------------------------------------------------------------------------
# get_tournament_shadow_live_staked
# ---------------------------------------------------------------------------

def test_staked_returns_zero_when_no_shadow_bets(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        tournament, candidate, ticket = _make_candidate_and_ticket(session)
        # Only a paper bet placed
        place_ticket_row(session, ticket, candidate, actual_american_odds=-110, actual_stake=20.0)
        session.flush()
        staked = get_tournament_shadow_live_staked(session, tournament.tournament_id)
    assert staked == 0.0


def test_staked_accumulates_shadow_live_bets(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        tournament, candidate, ticket = _make_candidate_and_ticket(session)
        t2 = _extra_ticket(session, candidate)
        _place_shadow_live(session, ticket, 15.0)
        _place_shadow_live(session, t2, 10.0)
        session.flush()
        staked = get_tournament_shadow_live_staked(session, tournament.tournament_id)
    assert staked == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Reports: paper report excludes shadow-live bets
# ---------------------------------------------------------------------------

def test_paper_report_excludes_shadow_live_bets(tmp_path) -> None:
    """build_stored_paper_trade_report must not count shadow-live bets."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        _, candidate, ticket = _make_candidate_and_ticket(session)
        t2 = _extra_ticket(session, candidate)
        # One paper bet, one shadow-live bet
        place_ticket_row(session, ticket, candidate, actual_american_odds=-110, actual_stake=20.0)
        _place_shadow_live(session, t2, 15.0)
        session.flush()

        report = build_stored_paper_trade_report(session)

    assert report.placed_count == 1
    assert report.total_staked == pytest.approx(20.0)


def test_shadow_live_summary_counts_only_shadow_bets(tmp_path) -> None:
    """build_shadow_live_summary must not count paper bets."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        _, candidate, ticket = _make_candidate_and_ticket(session)
        t2 = _extra_ticket(session, candidate)
        place_ticket_row(session, ticket, candidate, actual_american_odds=-110, actual_stake=20.0)
        _place_shadow_live(session, t2, 15.0)
        session.flush()

        summary = build_shadow_live_summary(session)

    assert summary.bet_count == 1
    assert summary.total_staked == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Evidence check: shadow-live is NOT contamination
# ---------------------------------------------------------------------------

def test_evidence_check_does_not_flag_shadow_live(tmp_path) -> None:
    """Shadow-live bets must not trigger the evidence contamination flag."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        _, candidate, ticket = _make_candidate_and_ticket(session)
        _place_shadow_live(session, ticket, 15.0)
        session.flush()

        evidence = build_phase3_evidence_report(session)

    # Shadow-live is not contamination — the criterion must still pass
    manual_criterion = next(
        c for c in evidence.criteria if c.name == "manual_placements_only"
    )
    assert manual_criterion.passed is True


def test_evidence_check_flags_backtest_as_contamination(tmp_path) -> None:
    """Backtest placements must still be caught as contamination."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    with get_session(db_url) as session:
        _, candidate, ticket = _make_candidate_and_ticket(session)
        place_ticket_row(
            session,
            ticket,
            candidate,
            actual_american_odds=-110,
            actual_stake=20.0,
            placement_method="backtest",
        )
        session.flush()

        evidence = build_phase3_evidence_report(session)

    manual_criterion = next(
        c for c in evidence.criteria if c.name == "manual_placements_only"
    )
    assert manual_criterion.passed is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate_and_ticket(session):
    tournament = Tournament(name="Truist Championship", tour="pga", created_at=NOW)
    player = Player(datagolf_player_id="scheffler", name_canonical="Scottie Scheffler", created_at=NOW, updated_at=NOW)
    opponent = Player(datagolf_player_id="mcilroy", name_canonical="Rory McIlroy", created_at=NOW, updated_at=NOW)
    session.add_all([tournament, player, opponent])
    session.flush()

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
        inputs_hash="candidate-test",
        created_at=NOW,
    )
    session.add(candidate)
    session.flush()

    edge = EdgeResult(
        datagolf_id="scheffler",
        opponent_id="mcilroy",
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
        active_bankroll=10_000.0,
        total_bankroll=25_000.0,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    ticket_draft = generate_ticket(edge, sizing, tournament_id="test", created_at=NOW)
    ticket = persist_ticket(session, ticket_draft, candidate_id=candidate.candidate_id)
    return tournament, candidate, ticket


def _extra_ticket(session, candidate: BetCandidate) -> BetTicket:
    """Create a second approved ticket for the same candidate."""
    ticket = BetTicket(
        candidate_id=candidate.candidate_id,
        sleeve="core",
        proposed_stake=20.0,
        proposed_american_odds=-110,
        kelly_fraction_used=0.25,
        sizing_method="fractional_kelly",
        approved=True,
        inputs_hash=f"extra-{id(candidate)}",
        created_at=NOW,
    )
    session.add(ticket)
    session.flush()
    return ticket


def _place_shadow_live(session, ticket: BetTicket, stake: float) -> PlacedBet:
    """Place a shadow-live bet bypassing the guardrail (for test setup)."""
    row = PlacedBet(
        ticket_id=ticket.ticket_id,
        book="dk",
        actual_american_odds=-110,
        actual_stake=stake,
        placed_at=NOW,
        notes="shadow-live test bet",
        placement_method=SHADOW_LIVE_METHOD,
        bet_class="STANDARD",
        inputs_hash=f"sl-bet-{id(ticket)}",
    )
    session.add(row)
    session.flush()
    return row
