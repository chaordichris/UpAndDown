from __future__ import annotations

from scripts.evaluate_splash_lobby import render_evaluation_summary
from src.fantasy.splash.contest_evaluator import (
    SplashLobbyEvaluationConfig,
    build_splash_lobby_evaluation,
)


def test_splash_lobby_evaluation_ranks_supported_total_strokes_contests() -> None:
    artifact = build_splash_lobby_evaluation(
        _discovery_manifest(),
        config=SplashLobbyEvaluationConfig(
            bankroll_dollars=1_000,
            weekly_cap_fraction=0.10,
            per_contest_cap_fraction=0.10,
            max_entries_per_contest=8,
        ),
    )

    assert artifact["artifact_type"] == "splash_lobby_evaluation"
    assert artifact["source"]["league_id"] == "league-1"
    assert artifact["contest_count"] == 2
    assert artifact["contests"][0]["contest"]["name"] == "RunGood Total Strokes"
    assert artifact["contests"][0]["recommendation"]["action"] == "priority-play"
    assert artifact["contests"][0]["capital"]["recommended_entries"] == 3
    assert artifact["contests"][1]["contest"]["name"] == "Dollar Winnings"
    assert artifact["contests"][1]["recommendation"]["action"] == "monitor"
    assert artifact["capital_plan"]["planned_spend_dollars"] == 75.0
    assert artifact["capital_plan"]["planned_entries"] == 3
    assert artifact["artifact_hash"]


def test_splash_lobby_evaluation_respects_weekly_cap() -> None:
    artifact = build_splash_lobby_evaluation(
        _discovery_manifest(),
        config=SplashLobbyEvaluationConfig(
            bankroll_dollars=500,
            weekly_cap_fraction=0.05,
            per_contest_cap_fraction=0.20,
            max_entries_per_contest=8,
        ),
    )

    assert artifact["capital_plan"]["weekly_cap_dollars"] == 25.0
    assert artifact["capital_plan"]["planned_entries"] == 1
    assert artifact["capital_plan"]["planned_spend_dollars"] == 25.0


def test_render_evaluation_summary_contains_operator_plan() -> None:
    artifact = build_splash_lobby_evaluation(
        _discovery_manifest(),
        config=SplashLobbyEvaluationConfig(
            bankroll_dollars=1_000,
            per_contest_cap_fraction=0.10,
        ),
    )

    rendered = render_evaluation_summary(artifact)

    assert "Splash capital plan" in rendered
    assert "RunGood Total Strokes" in rendered
    assert "priority-play" in rendered


def _discovery_manifest() -> dict:
    return {
        "artifact_hash": "discovery-hash",
        "source": {"league_id": "league-1", "lobby_url": "https://app.splashsports.test/lobby"},
        "contests": [
            {
                "id": "contest-total-strokes",
                "name": "RunGood Total Strokes",
                "contest_type": "player_tier",
                "contest_type_alt_text": "Tiers",
                "entry_fee_cents": 2500,
                "entry_fee_dollars": 25,
                "prize_pool_cents": 2502000,
                "prize_pool_dollars": 25020,
                "start_date": "2026-07-09T12:00:00.000Z",
                "status": "SCHEDULED",
                "entries": {"filled": 22, "max": 1000, "max_per_user": 40},
                "scoring_type": "golf_score",
                "expected_picks_count": 6,
                "drop_worst_count": 1,
                "league": {"id": "league-1", "name": "PGA", "sport": "golf"},
            },
            {
                "id": "contest-dollar-winnings",
                "name": "Dollar Winnings",
                "contest_type": "player_tier",
                "contest_type_alt_text": "Tiers",
                "entry_fee_cents": 10000,
                "entry_fee_dollars": 100,
                "prize_pool_cents": 504000,
                "prize_pool_dollars": 5040,
                "start_date": "2026-07-09T12:00:00.000Z",
                "status": "SCHEDULED",
                "entries": {"filled": 33, "max": 56, "max_per_user": 3},
                "scoring_type": "dollars",
                "expected_picks_count": 6,
                "drop_worst_count": 0,
                "league": {"id": "league-1", "name": "PGA", "sport": "golf"},
            },
        ],
    }
