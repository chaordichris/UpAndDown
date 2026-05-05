from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.backtest.summary import BacktestReportSlice, aggregate_backtest_reports
from src.monitoring.reports import StoredPaperTradeReport
from src.storage.hashing import artifact_hash, stable_hash

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_multi_tournament_summary.json"
)


def test_backtest_multi_tournament_summary_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["summary"]["tournament_count"] == fixture["expected"]["tournament_count"]
    assert first["summary"]["ticket_count"] == fixture["expected"]["ticket_count"]
    assert first["summary"]["settled_count"] == fixture["expected"]["settled_count"]
    assert first["summary"]["strategy_profit_loss"] == fixture["expected"][
        "strategy_profit_loss"
    ]
    assert first["summary"]["strategy_roi"] == fixture["expected"]["strategy_roi"]
    assert first["summary"]["average_edge"] == fixture["expected"]["average_edge"]
    assert first["summary"]["average_clv_raw"] == fixture["expected"]["average_clv_raw"]
    assert first["summary"]["positive_clv_rate"] == fixture["expected"]["positive_clv_rate"]
    assert first["summary"]["profitable_tournament_count"] == fixture["expected"][
        "profitable_tournament_count"
    ]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "summary_hash": manifest["summary_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    report_slices = [
        BacktestReportSlice(label=payload["label"], report=_report_from_fixture(payload))
        for payload in fixture["reports"]
    ]
    summary = aggregate_backtest_reports(report_slices)
    summary_payload = _rounded(asdict(summary))
    manifest = {
        "scenario": fixture["scenario"],
        "shape": {
            "reports": len(report_slices),
        },
        "summary": summary_payload,
        "summary_hash": artifact_hash(
            artifact_type="backtest_multi_tournament_summary",
            inputs={
                "reports": fixture["reports"],
                "summary": summary_payload,
            },
            config=None,
            code_version=fixture["code_version"],
        ),
    }
    return {**manifest, "manifest_hash": stable_hash(manifest)}


def _report_from_fixture(payload: dict[str, Any]) -> StoredPaperTradeReport:
    total_staked = payload["total_staked"]
    strategy_profit_loss = payload["strategy_profit_loss"]
    total_profit_loss = payload["total_profit_loss"]
    return StoredPaperTradeReport(
        ticket_count=payload["ticket_count"],
        approved_count=payload["approved_count"],
        open_ticket_count=0,
        placed_count=payload["placed_count"],
        settled_count=payload["settled_count"],
        pending_settlement_count=0,
        clv_count=payload["clv_count"],
        missing_clv_count=0,
        total_staked=total_staked,
        open_approved_stake=0.0,
        total_profit_loss=total_profit_loss,
        strategy_profit_loss=strategy_profit_loss,
        promo_profit_loss=total_profit_loss - strategy_profit_loss,
        roi=0.0 if total_staked == 0 else total_profit_loss / total_staked,
        strategy_roi=0.0 if total_staked == 0 else strategy_profit_loss / total_staked,
        average_edge=payload["average_edge"],
        average_clv_raw=payload["average_clv_raw"],
        positive_clv_rate=payload["positive_clv_rate"],
        attribution_count=0,
        model_alpha=0.0,
        execution_drift=0.0,
        sizing_alpha=0.0,
        variance=0.0,
    )


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded
