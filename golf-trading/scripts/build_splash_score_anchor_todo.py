"""Build a manual score-anchor TODO file from mapped Splash players and DG forecasts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.io_utils import (  # noqa: E402
    fixture_path as _fixture_path,
    load_json as _load_json,
    write_json as _write_json,
)
from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a score-anchor TODO file with DataGolf make-cut probabilities."
    )
    parser.add_argument("--datagolf-ranks-fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--datagolf-forecast-fixture")
    parser.add_argument("--tour", default="pga")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    rank_rows = _load_json(_fixture_path(root, args.datagolf_ranks_fixture))
    forecast = (
        _load_json(_fixture_path(root, args.datagolf_forecast_fixture))
        if args.datagolf_forecast_fixture
        else fetch_datagolf_pretournament_forecast(args.tour)
    )
    todo_rows, review = build_score_anchor_todo(rank_rows, forecast)
    _write_json(_fixture_path(root, args.output), todo_rows)
    _write_json(_fixture_path(root, args.review_output), review)
    print(
        json.dumps(
            {
                "todo_count": len(todo_rows),
                "review_count": len(review["review_items"]),
                "output": args.output,
                "review_output": args.review_output,
                "artifact_hash": stable_hash({"todo_rows": todo_rows, "review": review}),
            },
            indent=2,
            sort_keys=True,
        )
    )


def fetch_datagolf_pretournament_forecast(tour: str) -> dict[str, Any]:
    load_dotenv(".env")
    api_key = os.getenv("DATAGOLF_API_KEY")
    if not api_key:
        raise RuntimeError("DATAGOLF_API_KEY is not set")
    response = httpx.get(
        "https://feeds.datagolf.com/preds/pre-tournament",
        params={"key": api_key, "tour": tour, "odds_format": "percent"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError("DataGolf pre-tournament forecast response must be a JSON object")
    return data


def build_score_anchor_todo(
    rank_rows: list[dict[str, Any]],
    forecast: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    forecast_by_id = {
        str(row["dg_id"]): row
        for row in forecast.get("baseline", [])
        if row.get("dg_id") is not None
    }
    todo_rows: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    for row in rank_rows:
        player_id = str(row["player_id"])
        forecast_row = forecast_by_id.get(player_id)
        if forecast_row is None:
            review_items.append(
                {
                    "player_id": player_id,
                    "player_name": row["player_name"],
                    "datagolf_rank": row["datagolf_rank"],
                    "status": "missing_datagolf_pretournament_forecast",
                }
            )
            continue
        todo_rows.append(
            {
                "player_id": player_id,
                "player_name": row["player_name"],
                "datagolf_rank": row["datagolf_rank"],
                "make_cut_probability": forecast_row.get("make_cut"),
                "made_cut_score_mean": None,
                "made_cut_score_sd": None,
                "cut_rounds_score_mean": None,
                "cut_rounds_score_sd": None,
                "source": "datagolf_pretournament_make_cut_prefill_score_moments_required",
                "raw_datagolf_player_name": forecast_row.get("player_name"),
                "win_probability": forecast_row.get("win"),
                "top_5_probability": forecast_row.get("top_5"),
                "top_10_probability": forecast_row.get("top_10"),
                "top_20_probability": forecast_row.get("top_20"),
            }
        )
    review = {
        "policy": (
            "DataGolf pre-tournament forecast supplies make_cut/top-N/win probabilities. "
            "The score simulator still requires made-cut and missed-cut score moments; "
            "those fields remain null until manually or separately sourced."
        ),
        "event_name": forecast.get("event_name"),
        "last_updated": forecast.get("last_updated"),
        "todo_count": len(todo_rows),
        "review_count": len(review_items),
        "review_items": review_items,
        "inputs_hash": stable_hash(
            {
                "rank_rows": rank_rows,
                "event_name": forecast.get("event_name"),
                "last_updated": forecast.get("last_updated"),
                "todo_rows": todo_rows,
                "review_items": review_items,
            }
        ),
    }
    return todo_rows, review



if __name__ == "__main__":
    main()
