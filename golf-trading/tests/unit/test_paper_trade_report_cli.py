from __future__ import annotations

import json
from pathlib import Path

from scripts.paper_trade import (
    _write_output,
    build_stored_report_artifact,
    render_stored_report_json,
)
from src.monitoring.reports import StoredPaperTradeReport


def test_render_stored_report_json_is_stable() -> None:
    rendered = render_stored_report_json(_report(), code_version="paper-report-test")
    payload = json.loads(rendered)

    assert payload["artifact_type"] == "paper_trade_report"
    assert payload["artifact_hash"] == "05f403b6a6ae90490e3c051f61b3f0c6f8b68a7f4609878037a207c11a9db565"
    assert payload["report"]["ticket_count"] == 2
    assert payload["report"]["settled_count"] == 1
    assert payload["report"]["strategy_profit_loss"] == 95.24
    assert '"average_clv_raw": 0.03' in rendered
    assert rendered == render_stored_report_json(
        _report(),
        code_version="paper-report-test",
    )


def test_build_stored_report_artifact_is_stable() -> None:
    first = build_stored_report_artifact(_report(), code_version="paper-report-test")
    second = build_stored_report_artifact(_report(), code_version="paper-report-test")

    assert first == second
    assert first["report"]["positive_clv_rate"] == 1.0


def test_write_output_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "paper-report.json"

    _write_output(path, '{"ticket_count": 2}')

    assert path.read_text() == '{"ticket_count": 2}'


def _report() -> StoredPaperTradeReport:
    return StoredPaperTradeReport(
        ticket_count=2,
        approved_count=2,
        open_ticket_count=1,
        placed_count=1,
        settled_count=1,
        pending_settlement_count=0,
        clv_count=1,
        missing_clv_count=0,
        total_staked=100.0,
        open_approved_stake=50.0,
        total_profit_loss=95.24,
        strategy_profit_loss=95.24,
        promo_profit_loss=0.0,
        roi=0.9524,
        strategy_roi=0.9524,
        average_edge=0.045,
        average_clv_raw=0.03,
        positive_clv_rate=1.0,
        attribution_count=1,
        model_alpha=5.0,
        execution_drift=4.33,
        sizing_alpha=0.0,
        variance=85.91,
    )
