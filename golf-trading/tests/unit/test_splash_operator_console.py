from __future__ import annotations

import json

from scripts.splash_operator_console import (
    _handle_post,
    build_splash_dashboard_html,
    make_handler,
)


def test_splash_operator_console_renders_artifact_workflow(tmp_path) -> None:
    artifact_dir = tmp_path / "splash"
    artifact_dir.mkdir()
    (artifact_dir / "evaluation.json").write_text(json.dumps(_evaluation_artifact()))
    (artifact_dir / "lineup-card.json").write_text(json.dumps(_lineup_card()))

    rendered = build_splash_dashboard_html(artifact_dir)

    assert "UpAndDown Splash Console" in rendered
    assert "Splash Review State" in rendered
    assert "Lobby Opportunity Board" in rendered
    assert "RunGood Total Strokes" in rendered
    assert "Generated Lineups" in rendered
    assert "Ben Griffin" in rendered
    assert "Results / P&amp;L" in rendered


def test_splash_operator_console_records_lineup_and_result(tmp_path) -> None:
    artifact_dir = tmp_path / "splash"

    entry_message = _handle_post(
        "/record-lineup-entry",
        {
            "contest_id": ["contest-1"],
            "contest_name": ["RunGood Total Strokes"],
            "lineup_id": ["lineup-1"],
            "entry_number": ["1"],
            "players": ["Ben Griffin\nRyo Hisatsune"],
            "entry_fee_dollars": ["25"],
            "source_artifact_hash": ["card-hash"],
            "notes": ["entered manually"],
        },
        artifact_dir,
    )
    result_message = _handle_post(
        "/record-result",
        {
            "contest_id": ["contest-1"],
            "contest_name": ["RunGood Total Strokes"],
            "entries_played": ["1"],
            "entry_fee_dollars": ["25"],
            "payout_dollars": ["50"],
            "notes": ["min cash"],
        },
        artifact_dir,
    )

    ledger = json.loads((artifact_dir / "splash-results-ledger.json").read_text())
    rendered = build_splash_dashboard_html(artifact_dir)

    assert entry_message == "Recorded Splash lineup entry entry-1."
    assert result_message == "Recorded Splash result result-1: P&L $25.00."
    assert ledger["lineup_entries"][0]["players"] == ["Ben Griffin", "Ryo Hisatsune"]
    assert ledger["results"][0]["profit_loss_dollars"] == 25.0
    assert ledger["artifact_hash"]
    assert "Tracked P&amp;L" in rendered
    assert "$25.00" in rendered


def test_splash_operator_console_handler_factory(tmp_path) -> None:
    handler = make_handler(tmp_path)

    assert handler.__name__ == "SplashOperatorConsoleHandler"


def _evaluation_artifact() -> dict:
    return {
        "artifact_type": "splash_lobby_evaluation",
        "artifact_hash": "evaluation-hash",
        "contest_count": 1,
        "capital_plan": {
            "planned_entries": 3,
            "planned_spend_dollars": 75.0,
            "planned_contests": [
                {
                    "contest_id": "contest-1",
                    "name": "RunGood Total Strokes",
                    "action": "priority-play",
                    "recommended_entries": 3,
                    "recommended_spend_dollars": 75.0,
                    "opportunity_score": 91.0,
                }
            ],
        },
        "contests": [
            {
                "contest": {
                    "id": "contest-1",
                    "name": "RunGood Total Strokes",
                    "entry_fee_dollars": 25.0,
                    "prize_pool_dollars": 25020.0,
                },
                "field": {
                    "fill_rate": 0.5,
                    "filled_entries": 500,
                    "max_entries": 1000,
                },
                "capital": {
                    "recommended_entries": 3,
                    "recommended_spend_dollars": 75.0,
                },
                "recommendation": {
                    "action": "priority-play",
                    "reasons": ["DataGolf total-strokes workflow supported"],
                },
                "opportunity_score": 91.0,
            }
        ],
    }


def _lineup_card() -> dict:
    return {
        "artifact_hash": "card-hash",
        "contest": {
            "id": "contest-1",
            "name": "RunGood Total Strokes",
            "entry_fee_cents": 2500,
        },
        "entry_plan": {"recommended_entries": 1},
        "lineups": [
            {
                "entry_number": 1,
                "lineup_id": "lineup-1",
                "players": ["Ben Griffin", "Ryo Hisatsune"],
                "expected_profit_cents": 1500,
                "marginal_ev_cents": 1200,
                "target_duplication_count": 1,
            }
        ],
    }
