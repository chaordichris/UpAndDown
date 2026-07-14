"""Run the weekly read-only Splash lobby workflow."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.capture_splash_contest import capture_splash_contest  # noqa: E402
from scripts.discover_splash_contests import discover_splash_contests  # noqa: E402
from src.fantasy.splash.contest_evaluator import (  # noqa: E402
    SplashLobbyEvaluationConfig,
    build_splash_lobby_evaluation,
)
from src.storage.hashing import stable_hash  # noqa: E402

WORKFLOW_VERSION = "splash-weekly-workflow-v1"


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        manifest = run_splash_weekly_workflow(
            league_id=args.league_id,
            lobby_url=args.lobby_url,
            bankroll=args.bankroll,
            artifact_dir=args.artifact_dir,
            limit=args.limit,
            offset=args.offset,
            include_full=args.include_full,
            include_hidden=args.include_hidden,
            contest_type=args.contest_type,
            weekly_cap_fraction=args.weekly_cap_fraction,
            per_contest_cap_fraction=args.per_contest_cap_fraction,
            max_entries_per_contest=args.max_entries_per_contest,
            capture_top=args.capture_top,
            tiers=tuple(args.tiers),
            player_pool_limit=args.player_pool_limit,
            base_url=args.base_url,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(render_workflow_summary(manifest), file=sys.stderr)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover, evaluate, and prepare a weekly Splash contest workflow."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--league-id", help="Raw Splash league UUID.")
    source.add_argument("--lobby-url", help="Full Splash /contest-lobby URL with league= UUID.")
    parser.add_argument("--bankroll", type=float, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-full", action="store_true", default=False)
    parser.add_argument("--include-hidden", action="store_true", default=False)
    parser.add_argument("--contest-type", default="player_tier")
    parser.add_argument("--weekly-cap-fraction", type=float, default=0.05)
    parser.add_argument("--per-contest-cap-fraction", type=float, default=0.02)
    parser.add_argument("--max-entries-per-contest", type=int, default=8)
    parser.add_argument(
        "--capture-top",
        type=int,
        default=0,
        help="Optionally run read-only contest/detail player-pool capture for top N planned contests.",
    )
    parser.add_argument("--tiers", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--player-pool-limit", type=int, default=50)
    parser.add_argument("--base-url", default="https://api.splashsports.com/contests-service/api")
    return parser


def run_splash_weekly_workflow(
    *,
    league_id: str | None,
    lobby_url: str | None,
    bankroll: float,
    artifact_dir: Path,
    limit: int,
    offset: int,
    include_full: bool,
    include_hidden: bool,
    contest_type: str | None,
    weekly_cap_fraction: float,
    per_contest_cap_fraction: float,
    max_entries_per_contest: int,
    capture_top: int,
    tiers: tuple[int, ...],
    player_pool_limit: int,
    base_url: str,
) -> dict[str, Any]:
    """Run discovery/evaluation and optionally capture top public contests."""
    if capture_top < 0:
        raise ValueError("capture_top must be non-negative")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    discovery_path = artifact_dir / "discovery.json"
    evaluation_path = artifact_dir / "lobby-evaluation.json"
    workflow_path = artifact_dir / "weekly-workflow.json"

    discovery = discover_splash_contests(
        league_id=league_id,
        lobby_url=lobby_url,
        limit=limit,
        offset=offset,
        include_full=include_full,
        include_hidden=include_hidden,
        contest_type=contest_type,
        output=discovery_path,
        base_url=base_url,
    )
    evaluation = build_splash_lobby_evaluation(
        discovery,
        config=SplashLobbyEvaluationConfig(
            bankroll_dollars=bankroll,
            weekly_cap_fraction=weekly_cap_fraction,
            per_contest_cap_fraction=per_contest_cap_fraction,
            max_entries_per_contest=max_entries_per_contest,
        ),
    )
    _write_json(evaluation_path, evaluation)

    planned_contests = evaluation["capital_plan"]["planned_contests"]
    capture_artifacts = []
    for row in planned_contests[:capture_top]:
        capture_artifacts.append(
            _capture_contest_artifacts(
                row,
                artifact_dir=artifact_dir,
                tiers=tiers,
                player_pool_limit=player_pool_limit,
                base_url=base_url,
            )
        )

    manifest = {
        "artifact_type": "splash_weekly_workflow",
        "version": WORKFLOW_VERSION,
        "source": {
            "league_id": league_id,
            "lobby_url": lobby_url,
            "base_url": base_url,
        },
        "artifacts": {
            "artifact_dir": str(artifact_dir),
            "discovery_json": str(discovery_path),
            "discovery_artifact_hash": discovery["artifact_hash"],
            "evaluation_json": str(evaluation_path),
            "evaluation_artifact_hash": evaluation["artifact_hash"],
            "workflow_json": str(workflow_path),
            "capture_artifacts": capture_artifacts,
        },
        "capital_plan": evaluation["capital_plan"],
        "recommended_next_steps": _recommended_next_steps(
            evaluation,
            artifact_dir=artifact_dir,
            tiers=tiers,
            player_pool_limit=player_pool_limit,
        ),
        "console": {
            "command": _console_command(artifact_dir),
            "url": "http://127.0.0.1:8766",
        },
    }
    manifest = {**manifest, "artifact_hash": stable_hash(manifest)}
    _write_json(workflow_path, manifest)
    return manifest


def render_workflow_summary(manifest: dict[str, Any]) -> str:
    plan = manifest["capital_plan"]
    lines = [
        (
            f"Splash weekly workflow wrote {manifest['artifacts']['artifact_dir']} "
            f"with ${plan['planned_spend_dollars']:.2f} planned across "
            f"{plan['planned_contest_count']} contests."
        ),
        f"Console: {manifest['console']['command']}",
    ]
    for row in plan["planned_contests"]:
        lines.append(
            " - "
            f"{row['action']} | {row['name']} | {row['recommended_entries']} entries | "
            f"${row['recommended_spend_dollars']:.2f}"
        )
    if not plan["planned_contests"]:
        lines.append(" - No playable contests under the current caps.")
    return "\n".join(lines)


def _capture_contest_artifacts(
    row: dict[str, Any],
    *,
    artifact_dir: Path,
    tiers: tuple[int, ...],
    player_pool_limit: int,
    base_url: str,
) -> dict[str, Any]:
    contest_id = str(row["contest_id"])
    contest_dir = artifact_dir / "contests" / contest_id
    contest_output = contest_dir / "contest-detail.json"
    player_pools_output = contest_dir / "player-pools-by-tier.json"
    manifest = capture_splash_contest(
        contest_id=contest_id,
        slate_id=None,
        tiers=tiers,
        limit=player_pool_limit,
        contest_output=contest_output,
        player_pools_output=player_pools_output,
        base_url=base_url,
    )
    capture_manifest_path = contest_dir / "capture-manifest.json"
    _write_json(capture_manifest_path, manifest)
    return {
        "contest_id": contest_id,
        "contest_name": row["name"],
        "contest_detail_json": str(contest_output),
        "player_pools_json": str(player_pools_output),
        "capture_manifest_json": str(capture_manifest_path),
        "capture_artifact_hash": manifest["artifact_hash"],
    }


def _recommended_next_steps(
    evaluation: dict[str, Any],
    *,
    artifact_dir: Path,
    tiers: tuple[int, ...],
    player_pool_limit: int,
) -> list[dict[str, Any]]:
    steps = []
    for row in evaluation["capital_plan"]["planned_contests"]:
        contest_dir = artifact_dir / "contests" / str(row["contest_id"])
        steps.append(
            {
                "contest_id": row["contest_id"],
                "contest_name": row["name"],
                "action": row["action"],
                "recommended_entries": row["recommended_entries"],
                "recommended_spend_dollars": row["recommended_spend_dollars"],
                "capture_command": _capture_command(
                    contest_id=str(row["contest_id"]),
                    contest_detail_path=contest_dir / "contest-detail.json",
                    player_pools_path=contest_dir / "player-pools-by-tier.json",
                    tiers=tiers,
                    player_pool_limit=player_pool_limit,
                ),
            }
        )
    return steps


def _capture_command(
    *,
    contest_id: str,
    contest_detail_path: Path,
    player_pools_path: Path,
    tiers: tuple[int, ...],
    player_pool_limit: int,
) -> str:
    parts = [
        ".venv/bin/python",
        "scripts/capture_splash_contest.py",
        "--contest-id",
        contest_id,
        "--contest-output",
        str(contest_detail_path),
        "--player-pools-output",
        str(player_pools_path),
        "--limit",
        str(player_pool_limit),
        "--tiers",
        *[str(tier) for tier in tiers],
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _console_command(artifact_dir: Path) -> str:
    parts = [
        ".venv/bin/python",
        "scripts/splash_operator_console.py",
        "--artifact-dir",
        str(artifact_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8766",
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
