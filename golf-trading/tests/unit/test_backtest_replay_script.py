from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backtest_replay import (
    load_fixture,
    render_replay_manifest_json,
    run_fixture_replay,
    write_output,
)

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_forecast_candidate_replay.json"
)
MULTI_MARKET_FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_multi_market_core_replay.json"
)
TOP5_OUTRIGHT_FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_top5_outright_replay.json"
)


@pytest.mark.parametrize(
    "fixture_path",
    [FIXTURE_PATH, MULTI_MARKET_FIXTURE_PATH, TOP5_OUTRIGHT_FIXTURE_PATH],
)
def test_run_fixture_replay_writes_event_db_and_stable_manifest(
    tmp_path: Path,
    fixture_path: Path,
) -> None:
    fixture = load_fixture(fixture_path)
    database_url = f"sqlite:///{tmp_path / 'event.db'}"

    manifest = run_fixture_replay(fixture, database_url=database_url)
    rendered = render_replay_manifest_json(manifest)

    assert {line["book_id"] for line in fixture["book_lines"]} == {
        ticket["book_id"] for ticket in _flatten_ticket_payloads(manifest)
    }
    assert {line["market_type"] for line in fixture["book_lines"]} == {
        ticket["market_type"] for ticket in _flatten_ticket_payloads(manifest)
    }
    assert manifest["ticket_summary"] == {
        "approved": fixture["expected"]["approved_ticket_count"],
        "rejected": fixture["expected"]["rejected_ticket_count"],
    }
    assert manifest["report"]["settled_count"] == fixture["expected"]["settled_count"]
    assert manifest["report"]["clv_count"] == fixture["expected"]["clv_count"]
    assert manifest["report"]["strategy_profit_loss"] == fixture["expected"][
        "strategy_profit_loss"
    ]
    assert {
        "forecast_batch_hash": manifest["forecast_batch_hash"],
        "candidate_batch_hash": manifest["candidate_batch_hash"],
        "ticket_batch_hash": manifest["ticket_batch_hash"],
        "settlement_batch_hash": manifest["settlement_batch_hash"],
        "report_hash": manifest["report_hash"],
        "manifest_hash": manifest["manifest_hash"],
    } == fixture["expected_hashes"]
    assert json.loads(rendered)["manifest_hash"] == fixture["expected_hashes"][
        "manifest_hash"
    ]


def test_run_fixture_replay_refuses_non_empty_event_db(tmp_path: Path) -> None:
    fixture = load_fixture(FIXTURE_PATH)
    database_url = f"sqlite:///{tmp_path / 'event.db'}"
    run_fixture_replay(fixture, database_url=database_url)

    with pytest.raises(ValueError, match="requires an empty event database"):
        run_fixture_replay(fixture, database_url=database_url)


def test_write_output_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "replay.json"

    write_output(path, '{"manifest_hash": "ok"}')

    assert path.read_text() == '{"manifest_hash": "ok"}'


def _flatten_ticket_payloads(manifest: dict) -> list[dict]:
    return [
        {"side": side, **payload}
        for side, payload in manifest["tickets"].items()
    ]
