"""Aggregate settled backtest reports across tournaments."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.monitoring.reports import StoredPaperTradeReport


@dataclass(frozen=True)
class BacktestReportSlice:
    """One tournament or event report to include in a backtest summary."""

    label: str
    report: StoredPaperTradeReport


@dataclass(frozen=True)
class BacktestAggregateSummary:
    """Weighted aggregate of existing stored paper-trade reports."""

    tournament_count: int
    ticket_count: int
    approved_count: int
    placed_count: int
    settled_count: int
    clv_count: int
    total_staked: float
    strategy_profit_loss: float
    realized_profit_loss: float
    strategy_roi: float
    realized_roi: float
    average_edge: float | None
    average_clv_raw: float | None
    positive_clv_rate: float | None
    profitable_tournament_count: int
    positive_clv_tournament_count: int


def aggregate_backtest_reports(reports: list[BacktestReportSlice]) -> BacktestAggregateSummary:
    """Roll event-level reports into one multi-tournament backtest summary."""
    ticket_count = sum(item.report.ticket_count for item in reports)
    approved_count = sum(item.report.approved_count for item in reports)
    placed_count = sum(item.report.placed_count for item in reports)
    settled_count = sum(item.report.settled_count for item in reports)
    clv_count = sum(item.report.clv_count for item in reports)
    total_staked = round(sum(item.report.total_staked for item in reports), 2)
    strategy_profit_loss = round(sum(item.report.strategy_profit_loss for item in reports), 2)
    realized_profit_loss = round(sum(item.report.total_profit_loss for item in reports), 2)

    return BacktestAggregateSummary(
        tournament_count=len(reports),
        ticket_count=ticket_count,
        approved_count=approved_count,
        placed_count=placed_count,
        settled_count=settled_count,
        clv_count=clv_count,
        total_staked=total_staked,
        strategy_profit_loss=strategy_profit_loss,
        realized_profit_loss=realized_profit_loss,
        strategy_roi=0.0 if total_staked == 0 else strategy_profit_loss / total_staked,
        realized_roi=0.0 if total_staked == 0 else realized_profit_loss / total_staked,
        average_edge=_weighted_average(
            (item.report.average_edge, item.report.ticket_count) for item in reports
        ),
        average_clv_raw=_weighted_average(
            (item.report.average_clv_raw, item.report.clv_count) for item in reports
        ),
        positive_clv_rate=_weighted_average(
            (item.report.positive_clv_rate, item.report.clv_count) for item in reports
        ),
        profitable_tournament_count=sum(
            item.report.strategy_profit_loss > 0 for item in reports
        ),
        positive_clv_tournament_count=sum(
            (item.report.average_clv_raw or 0.0) > 0 for item in reports
        ),
    )


def render_backtest_summary(summary: BacktestAggregateSummary) -> str:
    """Render a concise multi-tournament backtest summary."""
    return "\n".join(
        [
            "Backtest Summary",
            f"Tournaments: {summary.tournament_count}",
            (
                f"Tickets: {summary.ticket_count} total, "
                f"{summary.approved_count} approved"
            ),
            f"Bets: {summary.placed_count} placed, {summary.settled_count} settled",
            f"CLV: {summary.clv_count} recorded",
            f"Staked: ${summary.total_staked:.2f}",
            f"Strategy P&L: ${summary.strategy_profit_loss:.2f}",
            f"Realized P&L: ${summary.realized_profit_loss:.2f}",
            f"Strategy ROI: {summary.strategy_roi:.2%}",
            f"Realized ROI: {summary.realized_roi:.2%}",
            f"Average edge: {_format_optional_pct(summary.average_edge)}",
            f"Average raw CLV: {_format_optional_pct(summary.average_clv_raw)}",
            f"Positive CLV rate: {_format_optional_pct(summary.positive_clv_rate)}",
            f"Profitable tournaments: {summary.profitable_tournament_count}",
            f"Positive-CLV tournaments: {summary.positive_clv_tournament_count}",
        ]
    )


def _weighted_average(values: Iterable[tuple[float | None, int]]) -> float | None:
    total_weight = 0
    weighted_sum = 0.0
    for value, weight in values:
        if value is None or weight <= 0:
            continue
        total_weight += weight
        weighted_sum += value * weight
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


def _format_optional_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"
