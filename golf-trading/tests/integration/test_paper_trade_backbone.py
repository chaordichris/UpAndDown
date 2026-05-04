from __future__ import annotations

import math
from datetime import UTC, datetime

from src.execution.placement import log_placement
from src.execution.settlement import settle_placement
from src.execution.tickets import generate_ticket, render_ticket
from src.monitoring.clv import compute_clv
from src.monitoring.reports import build_paper_trade_report
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet

NOW = datetime(2024, 3, 11, tzinfo=UTC)


def _edge() -> EdgeResult:
    return EdgeResult(
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


def test_candidate_to_ticket_to_settlement_to_report() -> None:
    edge = _edge()
    sizing = size_core_bet(
        edge=edge,
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )

    ticket = generate_ticket(edge, sizing, tournament_id="players_2024", created_at=NOW)
    placement = log_placement(ticket, actual_american_odds=-105, placed_at=NOW)
    settlement = settle_placement(placement, result="win", settled_at=NOW)
    clv = compute_clv(ticket, placement, closing_american_odds=-125, captured_at=NOW)
    report = build_paper_trade_report([ticket], [settlement], [clv])

    assert ticket.approved
    assert ticket.inputs_hash
    assert placement.status == "placed"
    assert settlement.profit_loss > 0
    assert clv.clv_raw > 0
    assert report.ticket_count == 1
    assert report.approved_count == 1
    assert report.settled_count == 1
    assert math.isclose(report.total_profit_loss, settlement.profit_loss)
    assert "TKT-" in render_ticket(ticket)


def test_manual_rejection_records_no_stake() -> None:
    edge = _edge()
    sizing = size_core_bet(
        edge=edge,
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    ticket = generate_ticket(edge, sizing, tournament_id="players_2024", created_at=NOW)

    placement = log_placement(ticket, rejected=True, rejection_reason="Line moved.", placed_at=NOW)

    assert placement.status == "rejected"
    assert placement.actual_stake == 0.0
    assert placement.actual_american_odds is None
