"""Build Splash score anchors from captured DataGolf enrichment payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.io_utils import (  # noqa: E402
    fixture_path as _fixture_path,
    load_json as _load_json,
    write_json as _write_json,
)
from src.storage.hashing import stable_hash  # noqa: E402

SOURCE = "datagolf_enriched_sg_transform_score_anchor_for_splash_sensitivity"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert captured DataGolf enrichment payloads into Splash score anchors."
    )
    parser.add_argument("--datagolf-ranks-fixture", required=True)
    parser.add_argument("--pre-tournament-fixture", required=True)
    parser.add_argument("--player-decompositions-fixture", required=True)
    parser.add_argument("--fantasy-projections-fixture")
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--tournament-rounds", type=int, default=4)
    parser.add_argument("--cut-rounds-played", type=int, default=2)
    parser.add_argument("--made-cut-extra-sd", type=float, default=1.5)
    parser.add_argument("--cut-rounds-extra-sd", type=float, default=1.0)
    parser.add_argument("--missed-cut-relative-score-mean", type=float, default=2.0)
    parser.add_argument("--minimum-score-sd", type=float, default=1.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    rank_rows = _load_json(_fixture_path(root, args.datagolf_ranks_fixture))
    pre_tournament = _load_json(_fixture_path(root, args.pre_tournament_fixture))
    decompositions = _load_json(_fixture_path(root, args.player_decompositions_fixture))
    fantasy_projections = (
        _load_json(_fixture_path(root, args.fantasy_projections_fixture))
        if args.fantasy_projections_fixture
        else None
    )
    anchors, review = build_enriched_score_anchors(
        rank_rows,
        pre_tournament,
        decompositions,
        fantasy_projections=fantasy_projections,
        tournament_rounds=args.tournament_rounds,
        cut_rounds_played=args.cut_rounds_played,
        made_cut_extra_sd=args.made_cut_extra_sd,
        cut_rounds_extra_sd=args.cut_rounds_extra_sd,
        missed_cut_relative_score_mean=args.missed_cut_relative_score_mean,
        minimum_score_sd=args.minimum_score_sd,
    )
    _write_json(_fixture_path(root, args.output), anchors)
    _write_json(_fixture_path(root, args.review_output), review)
    print(
        json.dumps(
            {
                "anchor_count": len(anchors),
                "review_count": len(review["review_items"]),
                "output": args.output,
                "review_output": args.review_output,
                "artifact_hash": stable_hash({"anchors": anchors, "review": review}),
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_enriched_score_anchors(
    rank_rows: list[dict[str, Any]],
    pre_tournament: dict[str, Any],
    player_decompositions: dict[str, Any],
    *,
    fantasy_projections: dict[str, Any] | None,
    tournament_rounds: int,
    cut_rounds_played: int,
    made_cut_extra_sd: float,
    cut_rounds_extra_sd: float,
    missed_cut_relative_score_mean: float,
    minimum_score_sd: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return runnable Splash score anchors using DataGolf enrichment fields.

    DataGolf's player decomposition is strokes-gained per round versus an
    average PGA Tour field. Splash needs lower-is-better total-strokes scores,
    so this function converts SG to relative strokes by multiplying by the
    number of rounds and flipping the sign.
    """
    _validate_parameters(
        tournament_rounds=tournament_rounds,
        cut_rounds_played=cut_rounds_played,
        made_cut_extra_sd=made_cut_extra_sd,
        cut_rounds_extra_sd=cut_rounds_extra_sd,
        minimum_score_sd=minimum_score_sd,
    )
    forecast_by_id = _rows_by_id(pre_tournament.get("baseline", []))
    decomposition_by_id = _rows_by_id(player_decompositions.get("players", []))
    projection_by_id = _rows_by_id((fantasy_projections or {}).get("projections", []))

    anchors: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    for row in sorted(rank_rows, key=lambda item: int(item["datagolf_rank"])):
        player_id = str(row["player_id"])
        forecast_row = forecast_by_id.get(player_id)
        decomposition_row = decomposition_by_id.get(player_id)
        if forecast_row is None:
            review_items.append(_review_item(row, "missing_datagolf_pretournament_forecast"))
            continue
        if decomposition_row is None:
            review_items.append(_review_item(row, "missing_datagolf_player_decomposition"))
            continue
        make_cut_probability = _required_float(
            forecast_row,
            "make_cut",
            row,
            review_items,
        )
        final_pred = _required_float(
            decomposition_row,
            "final_pred",
            row,
            review_items,
        )
        player_sd = _required_float(
            decomposition_row,
            "std_deviation",
            row,
            review_items,
        )
        if make_cut_probability is None or final_pred is None or player_sd is None:
            continue

        projection_row = projection_by_id.get(player_id)
        if fantasy_projections is not None and projection_row is None:
            review_items.append(_review_item(row, "missing_optional_fantasy_projection"))

        made_cut_score_mean = -final_pred * tournament_rounds
        cut_rounds_score_mean = missed_cut_relative_score_mean - final_pred * cut_rounds_played
        made_cut_score_sd = max(
            minimum_score_sd,
            _combine_sd(player_sd, tournament_rounds, made_cut_extra_sd),
        )
        cut_rounds_score_sd = max(
            minimum_score_sd,
            _combine_sd(player_sd, cut_rounds_played, cut_rounds_extra_sd),
        )
        anchors.append(
            {
                "player_id": player_id,
                "player_name": row["player_name"],
                "datagolf_rank": int(row["datagolf_rank"]),
                "make_cut_probability": make_cut_probability,
                "made_cut_score_mean": round(made_cut_score_mean, 4),
                "made_cut_score_sd": round(made_cut_score_sd, 4),
                "cut_rounds_score_mean": round(cut_rounds_score_mean, 4),
                "cut_rounds_score_sd": round(cut_rounds_score_sd, 4),
                "source": SOURCE,
                "datagolf_inputs": {
                    "raw_datagolf_player_name": forecast_row.get("player_name"),
                    "decomposition_player_name": decomposition_row.get("player_name"),
                    "fantasy_projection_player_name": (
                        projection_row.get("player_name") if projection_row else None
                    ),
                    "final_pred_sg_per_round": final_pred,
                    "baseline_pred_sg_per_round": decomposition_row.get("baseline_pred"),
                    "std_deviation_sg_per_round": player_sd,
                    "sample_size": decomposition_row.get("sample_size"),
                    "win_probability": forecast_row.get("win"),
                    "top_5_probability": forecast_row.get("top_5"),
                    "top_10_probability": forecast_row.get("top_10"),
                    "top_20_probability": forecast_row.get("top_20"),
                    "top_50_probability": forecast_row.get("top_50"),
                    "draftkings_projected_points_total": (
                        projection_row.get("proj_points_total") if projection_row else None
                    ),
                    "draftkings_projected_ownership": (
                        projection_row.get("proj_ownership") if projection_row else None
                    ),
                    "draftkings_projection_std_dev": (
                        projection_row.get("std_dev") if projection_row else None
                    ),
                },
            }
        )

    review = {
        "policy": (
            "Runnable DataGolf-enriched Splash score anchors. Make-cut and finish "
            "probabilities come directly from DataGolf pre-tournament forecasts. "
            "Score moments are an auditable SG-to-relative-strokes transform from "
            "DataGolf player decompositions; they are not observed total-strokes "
            "score distributions."
        ),
        "event_name": pre_tournament.get("event_name") or player_decompositions.get("event_name"),
        "pre_tournament_last_updated": pre_tournament.get("last_updated"),
        "player_decompositions_last_updated": player_decompositions.get("last_updated"),
        "fantasy_projections_last_updated": (
            fantasy_projections.get("last_updated") if fantasy_projections else None
        ),
        "anchor_count": len(anchors),
        "review_count": len(review_items),
        "review_items": review_items,
        "parameters": {
            "tournament_rounds": tournament_rounds,
            "cut_rounds_played": cut_rounds_played,
            "made_cut_extra_sd": made_cut_extra_sd,
            "cut_rounds_extra_sd": cut_rounds_extra_sd,
            "missed_cut_relative_score_mean": missed_cut_relative_score_mean,
            "minimum_score_sd": minimum_score_sd,
        },
        "summary": _anchor_summary(anchors),
    }
    review["inputs_hash"] = stable_hash(
        {
            "rank_rows": rank_rows,
            "pre_tournament_last_updated": pre_tournament.get("last_updated"),
            "player_decompositions_last_updated": player_decompositions.get("last_updated"),
            "fantasy_projections_last_updated": (
                fantasy_projections.get("last_updated") if fantasy_projections else None
            ),
            "anchors": anchors,
            "review_items": review_items,
            "parameters": review["parameters"],
        }
    )
    return anchors, review


def _combine_sd(sg_per_round_sd: float, rounds: int, extra_sd: float) -> float:
    return ((sg_per_round_sd * (rounds**0.5)) ** 2 + extra_sd**2) ** 0.5


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row["dg_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("dg_id") is not None
    }


def _required_float(
    source_row: dict[str, Any],
    key: str,
    rank_row: dict[str, Any],
    review_items: list[dict[str, Any]],
) -> float | None:
    value = source_row.get(key)
    if value is None:
        review_items.append(_review_item(rank_row, f"missing_required_{key}"))
        return None
    return float(value)


def _review_item(row: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "player_id": str(row["player_id"]),
        "player_name": row["player_name"],
        "datagolf_rank": row["datagolf_rank"],
        "status": status,
    }


def _anchor_summary(anchors: list[dict[str, Any]]) -> dict[str, Any]:
    if not anchors:
        return {}
    return {
        "made_cut_score_mean_min": min(anchor["made_cut_score_mean"] for anchor in anchors),
        "made_cut_score_mean_max": max(anchor["made_cut_score_mean"] for anchor in anchors),
        "made_cut_score_mean_avg": round(
            fmean(anchor["made_cut_score_mean"] for anchor in anchors),
            4,
        ),
        "made_cut_score_sd_avg": round(
            fmean(anchor["made_cut_score_sd"] for anchor in anchors),
            4,
        ),
        "cut_rounds_score_mean_avg": round(
            fmean(anchor["cut_rounds_score_mean"] for anchor in anchors),
            4,
        ),
        "cut_rounds_score_sd_avg": round(
            fmean(anchor["cut_rounds_score_sd"] for anchor in anchors),
            4,
        ),
    }


def _validate_parameters(
    *,
    tournament_rounds: int,
    cut_rounds_played: int,
    made_cut_extra_sd: float,
    cut_rounds_extra_sd: float,
    minimum_score_sd: float,
) -> None:
    if tournament_rounds <= 0:
        raise ValueError("tournament_rounds must be positive")
    if not 0 < cut_rounds_played < tournament_rounds:
        raise ValueError("cut_rounds_played must be between 0 and tournament_rounds")
    if made_cut_extra_sd < 0.0 or cut_rounds_extra_sd < 0.0:
        raise ValueError("extra standard deviations must be non-negative")
    if minimum_score_sd <= 0.0:
        raise ValueError("minimum_score_sd must be positive")



if __name__ == "__main__":
    main()
