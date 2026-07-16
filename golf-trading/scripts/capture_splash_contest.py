"""Capture read-only Splash contest detail and tier player-pool fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.client import (  # noqa: E402
    SplashReadOnlyClient,
    contest_id_from_ref,
    slate_id_from_contest_detail,
)
from src.fantasy.splash.parser import parse_contest_detail, parse_player_pool  # noqa: E402
from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture public Splash contest/player-pool JSON without auth."
    )
    parser.add_argument(
        "--contest-id",
        required=True,
        help="Raw Splash contest UUID or full Splash contest URL. Lobby URLs are rejected.",
    )
    parser.add_argument("--slate-id")
    parser.add_argument(
        "--tiers",
        nargs="+",
        type=int,
        default=None,
        help="Explicit tier IDs to capture. Default: auto-detect from the contest's own roster rules.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--contest-output")
    parser.add_argument("--player-pools-output")
    parser.add_argument("--base-url", default="https://api.splashsports.com/contests-service/api")
    args = parser.parse_args()

    try:
        artifact = capture_splash_contest(
            contest_id=args.contest_id,
            slate_id=args.slate_id,
            tiers=tuple(args.tiers) if args.tiers is not None else None,
            limit=args.limit,
            contest_output=Path(args.contest_output) if args.contest_output else None,
            player_pools_output=Path(args.player_pools_output) if args.player_pools_output else None,
            base_url=args.base_url,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(artifact, indent=2, sort_keys=True))


def capture_splash_contest(
    *,
    contest_id: str,
    slate_id: str | None,
    tiers: tuple[int, ...] | None,
    limit: int,
    contest_output: Path | None,
    player_pools_output: Path | None,
    base_url: str,
) -> dict[str, Any]:
    """Capture fixture JSON and return a small audit manifest.

    ``tiers=None`` (the default) auto-detects the tier range from the
    contest's own roster rules rather than trusting a caller-supplied guess
    — different Splash contests have different tier counts (a major's
    deeper field can mean 7-8 tiers instead of the common 6), so a fixed
    default silently under-captures for any contest that doesn't match it.
    """
    resolved_contest_id = contest_id_from_ref(contest_id)
    client = SplashReadOnlyClient(base_url=base_url)
    contest_fixture = client.contest_detail_fixture(resolved_contest_id)
    contest = parse_contest_detail(contest_fixture)
    resolved_tiers = tiers if tiers is not None else tuple(
        range(1, contest.roster_rule.number_of_tiers + 1)
    )
    resolved_slate_id = slate_id or slate_id_from_contest_detail(contest_fixture)
    pools_fixture = client.capture_tier_player_pools(
        contest_id=resolved_contest_id,
        slate_id=resolved_slate_id,
        tier_ids=resolved_tiers,
        limit=limit,
    )
    parsed_tiers = {
        tier_id: parse_player_pool(pools_fixture[str(tier_id)], tier_id=tier_id)
        for tier_id in resolved_tiers
    }

    if contest_output is not None:
        _write_json(contest_output, contest_fixture)
    if player_pools_output is not None:
        _write_json(player_pools_output, pools_fixture)

    manifest = {
        "contest": {
            "id": contest.splash_id,
            "name": contest.name,
            "entry_fee_cents": contest.entry_fee_cents,
            "max_entries": contest.max_entries,
            "max_entries_per_user": contest.max_entries_per_user,
            "filled_entries": contest.filled_entries,
            "number_of_tiers": contest.roster_rule.number_of_tiers,
            "number_per_tier": contest.roster_rule.number_per_tier,
            "drop_worst_count": contest.roster_rule.drop_worst_count,
        },
        "contest_ref": contest_id,
        "resolved_contest_id": resolved_contest_id,
        "slate_id": resolved_slate_id,
        "tiers": {
            str(tier_id): {
                "player_count": len(tier.players),
                "total": tier.max_players,
                "missing_datagolf_rank_count": sum(
                    1 for player in tier.players if player.datagolf_rank is None
                ),
                "unselectable_count": sum(
                    1 for player in tier.players if not player.is_selectable
                ),
            }
            for tier_id, tier in parsed_tiers.items()
        },
        "outputs": {
            "contest_output": str(contest_output) if contest_output else None,
            "player_pools_output": str(player_pools_output) if player_pools_output else None,
        },
    }
    return {**manifest, "artifact_hash": stable_hash(manifest)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
