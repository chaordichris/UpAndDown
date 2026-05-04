from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.backtest_replay import load_fixture, run_fixture_replay
from scripts.backtest_review import (
    _write_output,
    build_backtest_review_artifact,
    collect_backtest_report_slices,
    parse_event_arg,
    render_backtest_review_artifact_json,
)
from src.backtest.summary import BacktestReportSlice
from src.monitoring.reports import StoredPaperTradeReport
from src.storage.db import init_db

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_forecast_candidate_replay.json"
)


def test_parse_event_arg_requires_label_and_database_url() -> None:
    assert parse_event_arg("event_1=sqlite:////tmp/event.db") == (
        "event_1",
        "sqlite:////tmp/event.db",
    )

    with pytest.raises(argparse.ArgumentTypeError):
        parse_event_arg("sqlite:////tmp/event.db")


def test_backtest_review_artifact_is_stable_json_with_hashes() -> None:
    slices = [
        BacktestReportSlice(
            label="event_1",
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
            label="event_2",
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

    first = build_backtest_review_artifact(slices, code_version="backtest-review-test")
    second = build_backtest_review_artifact(slices, code_version="backtest-review-test")
    rendered = render_backtest_review_artifact_json(first)

    assert first == second
    assert first["summary"]["tournament_count"] == 2
    assert first["summary"]["settled_count"] == 3
    assert first["summary"]["average_clv_raw"] == 0.0
    assert first["summary_hash"] == "0a7ed640e82d696d8fd85e3f4e5034a592e9aa84034d80b0578a3f3b7fd77788"
    assert first["manifest_hash"] == "2ead7a5efc79c0f98b31ef7b6329ec40f55ebeeea0c172db508e854d8a2070ff"
    assert '"artifact_type": "backtest_review"' in rendered
    assert '"summary_hash":' in rendered


def test_collect_backtest_report_slices_reads_replay_event_db(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'event.db'}"
    run_fixture_replay(load_fixture(FIXTURE_PATH), database_url=database_url)

    slices = collect_backtest_report_slices([("event_1", database_url)])

    assert len(slices) == 1
    assert slices[0].label == "event_1"
    assert slices[0].report.ticket_count == 2
    assert slices[0].report.settled_count == 1


def test_collect_backtest_report_slices_refuses_empty_event_db(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"
    init_db(database_url)

    with pytest.raises(ValueError, match="has no replay rows"):
        collect_backtest_report_slices([("empty", database_url)])


def test_write_output_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "review.json"

    _write_output(path, '{"ok": true}')

    assert path.read_text() == '{"ok": true}'


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
