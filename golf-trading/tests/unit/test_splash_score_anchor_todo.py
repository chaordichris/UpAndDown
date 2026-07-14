from __future__ import annotations

from scripts.build_splash_score_anchor_todo import build_score_anchor_todo


def test_build_score_anchor_todo_prefills_make_cut_and_leaves_moments_empty() -> None:
    rank_rows = [
        {"player_id": "24968", "player_name": "Ben Griffin", "datagolf_rank": 18},
        {"player_id": "missing", "player_name": "Missing Forecast", "datagolf_rank": 99},
    ]
    forecast = {
        "event_name": "John Deere Classic",
        "last_updated": "2026-07-01 12:00:00",
        "baseline": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "make_cut": 0.8172,
                "win": 0.057,
                "top_5": 0.20,
                "top_10": 0.32,
                "top_20": 0.49,
            }
        ],
    }

    todo_rows, review = build_score_anchor_todo(rank_rows, forecast)

    assert todo_rows == [
        {
            "player_id": "24968",
            "player_name": "Ben Griffin",
            "datagolf_rank": 18,
            "make_cut_probability": 0.8172,
            "made_cut_score_mean": None,
            "made_cut_score_sd": None,
            "cut_rounds_score_mean": None,
            "cut_rounds_score_sd": None,
            "source": "datagolf_pretournament_make_cut_prefill_score_moments_required",
            "raw_datagolf_player_name": "Griffin, Ben",
            "win_probability": 0.057,
            "top_5_probability": 0.20,
            "top_10_probability": 0.32,
            "top_20_probability": 0.49,
        }
    ]
    assert review["review_items"] == [
        {
            "player_id": "missing",
            "player_name": "Missing Forecast",
            "datagolf_rank": 99,
            "status": "missing_datagolf_pretournament_forecast",
        }
    ]
    assert review["inputs_hash"]
