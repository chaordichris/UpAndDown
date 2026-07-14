"""Evaluate discovered Splash lobby contests and build a capital plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.contest_evaluator import (  # noqa: E402
    SplashLobbyEvaluationConfig,
    build_splash_lobby_evaluation,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank discovered Splash contests and produce a manual capital plan."
    )
    parser.add_argument("--discovery-json", type=Path, required=True)
    parser.add_argument("--bankroll", type=float, required=True)
    parser.add_argument("--weekly-cap-fraction", type=float, default=0.05)
    parser.add_argument("--per-contest-cap-fraction", type=float, default=0.02)
    parser.add_argument("--max-entries-per-contest", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with args.discovery_json.open() as handle:
        discovery = json.load(handle)
    artifact = build_splash_lobby_evaluation(
        discovery,
        config=SplashLobbyEvaluationConfig(
            bankroll_dollars=args.bankroll,
            weekly_cap_fraction=args.weekly_cap_fraction,
            per_contest_cap_fraction=args.per_contest_cap_fraction,
            max_entries_per_contest=args.max_entries_per_contest,
        ),
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    print(render_evaluation_summary(artifact), file=sys.stderr)
    print(json.dumps(artifact, indent=2, sort_keys=True))


def render_evaluation_summary(artifact: dict) -> str:
    plan = artifact["capital_plan"]
    lines = [
        (
            f"Splash capital plan: ${plan['planned_spend_dollars']:.2f} planned "
            f"across {plan['planned_contest_count']} contests "
            f"({plan['planned_entries']} entries), "
            f"${plan['remaining_cap_dollars']:.2f} weekly cap remaining."
        )
    ]
    for row in artifact["contests"]:
        contest = row["contest"]
        capital = row["capital"]
        recommendation = row["recommendation"]
        lines.append(
            " - "
            f"{row['opportunity_score']:05.2f} | {recommendation['action']} | "
            f"{contest['name']} | ${contest['entry_fee_dollars']:.2f} | "
            f"{capital['recommended_entries']} entries | "
            f"${capital['recommended_spend_dollars']:.2f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
