"""export_control_plane_status.py's Splash reader must match the ledger's
actual writer schema (splash_operator_console.py's lineup_entries/results
shape) and look in the per-week run directories run_splash_week.py actually
writes to — this file exists because that mismatch shipped silently for
weeks (no prior test caught it) until the first real ledger entries were
written and the dashboard showed zero open positions."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.export_control_plane_status import (
    _latest_splash_portfolio_file,
    _splash_open_positions,
    build_splash_status,
)


def _write_ledger(path: Path, *, lineup_entries=(), results=()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "lineup_entries": list(lineup_entries), "results": list(results)}))


def test_splash_open_positions_reads_real_writer_schema(tmp_path: Path) -> None:
    week_dir = tmp_path / "splash-week" / "2026-07-open"
    _write_ledger(
        week_dir / "splash-results-ledger.json",
        lineup_entries=[
            {
                "entry_id": "entry-1",
                "contest_id": "contest-a",
                "contest_name": "Betsperts Golf $10 The Open Championship",
                "lineup_id": "rungood-1508",
                "entry_fee_dollars": 10.0,
                "entered_at": "2026-07-16T13:39:50Z",
            }
        ],
    )

    positions, total_at_risk, notes = _splash_open_positions(tmp_path)

    assert notes == []
    assert total_at_risk == 10.0
    assert len(positions) == 1
    assert positions[0]["stake"] == 10.0
    assert positions[0]["id"] == "entry-1"
    assert "rungood-1508" in positions[0]["description"]


def test_splash_open_positions_excludes_settled_contests(tmp_path: Path) -> None:
    week_dir = tmp_path / "splash-week" / "2026-07-open"
    _write_ledger(
        week_dir / "splash-results-ledger.json",
        lineup_entries=[
            {"entry_id": "entry-1", "contest_id": "contest-a", "entry_fee_dollars": 10.0},
            {"entry_id": "entry-2", "contest_id": "contest-b", "entry_fee_dollars": 20.0},
        ],
        results=[{"result_id": "result-1", "contest_id": "contest-a", "payout_dollars": 0.0}],
    )

    positions, total_at_risk, _ = _splash_open_positions(tmp_path)

    assert [p["id"] for p in positions] == ["entry-2"]
    assert total_at_risk == 20.0


def test_splash_open_positions_aggregates_across_weeks(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path / "splash-week" / "2026-07-09" / "splash-results-ledger.json",
        lineup_entries=[{"entry_id": "entry-old", "contest_id": "contest-old", "entry_fee_dollars": 5.0}],
    )
    _write_ledger(
        tmp_path / "splash-week" / "2026-07-16" / "splash-results-ledger.json",
        lineup_entries=[{"entry_id": "entry-new", "contest_id": "contest-new", "entry_fee_dollars": 10.0}],
    )

    positions, total_at_risk, _ = _splash_open_positions(tmp_path)

    assert {p["id"] for p in positions} == {"entry-old", "entry-new"}
    assert total_at_risk == 15.0


def test_latest_splash_portfolio_file_prefers_newest_week_dir(tmp_path: Path) -> None:
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "rungood-splash-portfolios.json").write_text("{}")
    week_file = tmp_path / "splash-week" / "2026-07-16" / "rungood-splash-portfolios.json"
    week_file.parent.mkdir(parents=True, exist_ok=True)
    week_file.write_text("{}")

    result = _latest_splash_portfolio_file(tmp_path)

    assert result == week_file


def test_latest_splash_portfolio_file_falls_back_to_legacy_path(tmp_path: Path) -> None:
    legacy = tmp_path / "rungood-splash-portfolios.json"
    legacy.write_text("{}")

    assert _latest_splash_portfolio_file(tmp_path) == legacy


def test_latest_splash_portfolio_file_none_when_nothing_exists(tmp_path: Path) -> None:
    assert _latest_splash_portfolio_file(tmp_path) is None


def test_build_splash_status_end_to_end(tmp_path: Path) -> None:
    week_dir = tmp_path / "splash-week" / "2026-07-16"
    week_dir.mkdir(parents=True)
    (week_dir / "rungood-splash-portfolios.json").write_text(
        json.dumps(
            {
                "artifact_hash": "abc123",
                "contest": {"name": "RunGood $100K", "entry_fee_cents": 10000},
                "portfolios": {
                    "conservative": {"lineup_count": 2, "expected_roi": 0.05, "inputs_hash": "h1"},
                },
                "hard_review_items": [],
            }
        )
    )
    _write_ledger(
        week_dir / "splash-results-ledger.json",
        lineup_entries=[
            {"entry_id": "entry-1", "contest_id": "contest-a", "entry_fee_dollars": 10.0},
        ],
    )

    status = build_splash_status(tmp_path)

    assert status["health"]["status"] == "ok"
    assert len(status["opportunities"]) == 1
    assert len(status["positions"]) == 1
    assert status["exposures"]["total_at_risk"] == 10.0
