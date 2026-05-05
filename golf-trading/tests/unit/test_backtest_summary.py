from __future__ import annotations

import pytest

from src.backtest.summary import (
    BacktestReportSlice,
    aggregate_backtest_reports,
    render_backtest_summary,
)
from src.monitoring.reports import StoredPaperTradeReport


def test_aggregate_backtest_reports_weights_rates_by_available_counts() -> None:
    summary = aggregate_backtest_reports(
        [
            BacktestReportSlice(
                label="event-1",
                report=_report(
                    ticket_count=2,
                    approved_count=1,
                    placed_count=1,
                    settled_count=1,
                    clv_count=1,
                    total_staked=100.0,
                    strategy_profit_loss=50.0,
                    total_profit_loss=50.0,
                    average_edge=0.05,
                    average_clv_raw=0.02,
                    positive_clv_rate=1.0,
                ),
            ),
            BacktestReportSlice(
                label="event-2",
                report=_report(
                    ticket_count=3,
                    approved_count=2,
                    placed_count=2,
                    settled_count=2,
                    clv_count=2,
                    total_staked=200.0,
                    strategy_profit_loss=-75.0,
                    total_profit_loss=-75.0,
                    average_edge=0.03,
                    average_clv_raw=-0.01,
                    positive_clv_rate=0.5,
                ),
            ),
        ]
    )

    assert summary.tournament_count == 2
    assert summary.ticket_count == 5
    assert summary.approved_count == 3
    assert summary.placed_count == 3
    assert summary.settled_count == 3
    assert summary.clv_count == 3
    assert summary.total_staked == 300.0
    assert summary.strategy_profit_loss == -25.0
    assert summary.realized_profit_loss == -25.0
    assert summary.strategy_roi == pytest.approx(-25.0 / 300.0)
    assert summary.average_edge == pytest.approx(((0.05 * 2) + (0.03 * 3)) / 5)
    assert summary.average_clv_raw == pytest.approx(((0.02 * 1) + (-0.01 * 2)) / 3)
    assert summary.positive_clv_rate == pytest.approx(((1.0 * 1) + (0.5 * 2)) / 3)
    assert summary.profitable_tournament_count == 1
    assert summary.positive_clv_tournament_count == 1
    assert "Tournaments: 2" in render_backtest_summary(summary)
    assert "Strategy P&L: $-25.00" in render_backtest_summary(summary)


def test_aggregate_backtest_reports_handles_empty_summary() -> None:
    summary = aggregate_backtest_reports([])

    assert summary.tournament_count == 0
    assert summary.total_staked == 0.0
    assert summary.strategy_roi == 0.0
    assert summary.average_edge is None
    assert summary.average_clv_raw is None
    assert summary.positive_clv_rate is None
    assert "Average raw CLV: n/a" in render_backtest_summary(summary)


def _report(
    *,
    ticket_count: int = 0,
    approved_count: int = 0,
    placed_count: int = 0,
    settled_count: int = 0,
    clv_count: int = 0,
    total_staked: float = 0.0,
    strategy_profit_loss: float = 0.0,
    total_profit_loss: float = 0.0,
    average_edge: float | None = None,
    average_clv_raw: float | None = None,
    positive_clv_rate: float | None = None,
) -> StoredPaperTradeReport:
    return StoredPaperTradeReport(
        ticket_count=ticket_count,
        approved_count=approved_count,
        open_ticket_count=0,
        placed_count=placed_count,
        settled_count=settled_count,
        pending_settlement_count=0,
        clv_count=clv_count,
        missing_clv_count=0,
        total_staked=total_staked,
        open_approved_stake=0.0,
        total_profit_loss=total_profit_loss,
        strategy_profit_loss=strategy_profit_loss,
        promo_profit_loss=total_profit_loss - strategy_profit_loss,
        roi=0.0 if total_staked == 0 else total_profit_loss / total_staked,
        strategy_roi=0.0 if total_staked == 0 else strategy_profit_loss / total_staked,
        average_edge=average_edge,
        average_clv_raw=average_clv_raw,
        positive_clv_rate=positive_clv_rate,
        attribution_count=0,
        model_alpha=0.0,
        execution_drift=0.0,
        sizing_alpha=0.0,
        variance=0.0,
    )
