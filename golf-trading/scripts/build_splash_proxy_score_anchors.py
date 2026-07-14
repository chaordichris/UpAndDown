"""Build explicitly labeled proxy score anchors from DataGolf forecast TODO rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert score-anchor TODO rows into runnable proxy anchors."
    )
    parser.add_argument("--todo-fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--best-made-cut-mean", type=float, default=-8.5)
    parser.add_argument("--worst-made-cut-mean", type=float, default=-1.5)
    parser.add_argument("--best-cut-rounds-mean", type=float, default=1.5)
    parser.add_argument("--worst-cut-rounds-mean", type=float, default=5.0)
    parser.add_argument("--made-cut-score-sd", type=float, default=5.5)
    parser.add_argument("--cut-rounds-score-sd", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    todo_rows = _load_json(_fixture_path(root, args.todo_fixture))
    anchors, review = build_proxy_score_anchors(
        todo_rows,
        best_made_cut_mean=args.best_made_cut_mean,
        worst_made_cut_mean=args.worst_made_cut_mean,
        best_cut_rounds_mean=args.best_cut_rounds_mean,
        worst_cut_rounds_mean=args.worst_cut_rounds_mean,
        made_cut_score_sd=args.made_cut_score_sd,
        cut_rounds_score_sd=args.cut_rounds_score_sd,
    )
    _write_json(_fixture_path(root, args.output), anchors)
    _write_json(_fixture_path(root, args.review_output), review)
    print(
        json.dumps(
            {
                "anchor_count": len(anchors),
                "output": args.output,
                "review_output": args.review_output,
                "artifact_hash": stable_hash({"anchors": anchors, "review": review}),
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_proxy_score_anchors(
    todo_rows: list[dict[str, Any]],
    *,
    best_made_cut_mean: float,
    worst_made_cut_mean: float,
    best_cut_rounds_mean: float,
    worst_cut_rounds_mean: float,
    made_cut_score_sd: float,
    cut_rounds_score_sd: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if made_cut_score_sd <= 0 or cut_rounds_score_sd <= 0:
        raise ValueError("proxy score standard deviations must be positive")
    if best_made_cut_mean >= worst_made_cut_mean:
        raise ValueError("best_made_cut_mean must be lower than worst_made_cut_mean")
    if best_cut_rounds_mean >= worst_cut_rounds_mean:
        raise ValueError("best_cut_rounds_mean must be lower than worst_cut_rounds_mean")

    ranked_rows = sorted(todo_rows, key=lambda row: int(row["datagolf_rank"]))
    ranks = [int(row["datagolf_rank"]) for row in ranked_rows]
    best_rank = min(ranks)
    worst_rank = max(ranks)
    rank_span = max(1, worst_rank - best_rank)

    anchors = []
    for row in ranked_rows:
        rank = int(row["datagolf_rank"])
        rank_strength = (worst_rank - rank) / rank_span
        made_cut_mean = _interpolate(worst_made_cut_mean, best_made_cut_mean, rank_strength)
        cut_rounds_mean = _interpolate(worst_cut_rounds_mean, best_cut_rounds_mean, rank_strength)
        anchors.append(
            {
                "player_id": str(row["player_id"]),
                "player_name": row["player_name"],
                "datagolf_rank": rank,
                "make_cut_probability": row["make_cut_probability"],
                "made_cut_score_mean": round(made_cut_mean, 4),
                "made_cut_score_sd": made_cut_score_sd,
                "cut_rounds_score_mean": round(cut_rounds_mean, 4),
                "cut_rounds_score_sd": cut_rounds_score_sd,
                "source": "proxy_rank_scaled_score_anchor_for_splash_sensitivity",
                "proxy_inputs": {
                    "rank_strength": round(rank_strength, 6),
                    "raw_datagolf_player_name": row.get("raw_datagolf_player_name"),
                    "win_probability": row.get("win_probability"),
                    "top_10_probability": row.get("top_10_probability"),
                    "top_20_probability": row.get("top_20_probability"),
                },
            }
        )
    review = {
        "policy": (
            "Runnable proxy anchors. Make-cut probabilities come from DataGolf. "
            "Score moments are rank-scaled conservative placeholders and must not "
            "be treated as observed DataGolf score distributions."
        ),
        "anchor_count": len(anchors),
        "parameters": {
            "best_made_cut_mean": best_made_cut_mean,
            "worst_made_cut_mean": worst_made_cut_mean,
            "best_cut_rounds_mean": best_cut_rounds_mean,
            "worst_cut_rounds_mean": worst_cut_rounds_mean,
            "made_cut_score_sd": made_cut_score_sd,
            "cut_rounds_score_sd": cut_rounds_score_sd,
            "best_rank": best_rank,
            "worst_rank": worst_rank,
        },
        "inputs_hash": stable_hash({"todo_rows": todo_rows, "anchors": anchors}),
    }
    return anchors, review


def _interpolate(worst_value: float, best_value: float, strength: float) -> float:
    return worst_value + (best_value - worst_value) * strength


def _fixture_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    with path.open() as file:
        return json.load(file)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
