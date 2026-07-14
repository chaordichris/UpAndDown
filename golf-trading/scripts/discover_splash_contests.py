"""Discover public Splash lobby contests without auth."""

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
    league_id_from_lobby_url,
)
from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover public Splash contests from a league lobby without auth."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--league-id", help="Raw Splash league UUID.")
    source.add_argument("--lobby-url", help="Full Splash /contest-lobby URL with league= UUID.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-full", action="store_true", default=False)
    parser.add_argument("--include-hidden", action="store_true", default=False)
    parser.add_argument("--contest-type")
    parser.add_argument("--output")
    parser.add_argument("--base-url", default="https://api.splashsports.com/contests-service/api")
    args = parser.parse_args()

    try:
        manifest = discover_splash_contests(
            league_id=args.league_id,
            lobby_url=args.lobby_url,
            limit=args.limit,
            offset=args.offset,
            include_full=args.include_full,
            include_hidden=args.include_hidden,
            contest_type=args.contest_type,
            output=Path(args.output) if args.output else None,
            base_url=args.base_url,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(render_discovery_summary(manifest), file=sys.stderr)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def discover_splash_contests(
    *,
    league_id: str | None,
    lobby_url: str | None,
    limit: int,
    offset: int,
    include_full: bool,
    include_hidden: bool,
    contest_type: str | None,
    output: Path | None,
    base_url: str,
) -> dict[str, Any]:
    """Search public Splash contests and return an auditable manifest."""
    resolved_league_id = league_id or league_id_from_lobby_url(str(lobby_url))
    client = SplashReadOnlyClient(base_url=base_url)
    result = client.search_contests(
        league_id=resolved_league_id,
        limit=limit,
        offset=offset,
        include_full=include_full,
        hide_unlisted=not include_hidden,
        contest_type=contest_type,
    )
    contests = [_contest_summary(row) for row in _contest_rows(result.response_body)]

    manifest = {
        "source": {
            "league_id": resolved_league_id,
            "lobby_url": lobby_url,
        },
        "request": {
            "base_url": base_url,
            "endpoint": "/contests/search",
            "method": "POST",
            "limit": limit,
            "offset": offset,
            "include_full": include_full,
            "include_hidden": include_hidden,
            "contest_type": contest_type,
            "body": result.request_body,
        },
        "response": {
            "url": result.url,
            "status": result.response_status,
            "body": result.response_body,
        },
        "contests": contests,
        "contest_count": len(contests),
    }
    manifest = {**manifest, "artifact_hash": stable_hash(manifest)}

    if output is not None:
        _write_json(output, manifest)

    return manifest


def render_discovery_summary(manifest: dict[str, Any]) -> str:
    """Render a compact human-readable contest list."""
    lines = [
        (
            f"Discovered {manifest['contest_count']} Splash contests "
            f"for league {manifest['source']['league_id']}"
        )
    ]
    for contest in manifest["contests"]:
        entries = contest["entries"]
        entry_fee = _money_label(contest["entry_fee_dollars"], contest["entry_fee_cents"])
        prize_pool = _money_label(contest["prize_pool_dollars"], contest["prize_pool_cents"])
        lines.append(
            " - "
            f"{contest['id']} | {contest['name']} | {entry_fee} entry | "
            f"{prize_pool} prizes | {contest['start_date']} | {contest['status']} | "
            f"{entries['filled']}/{entries['max']} entries | "
            f"max/user {entries['max_per_user']} | {contest['contest_type']}"
        )
    return "\n".join(lines)


def _contest_rows(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = response_body.get("data") or response_body.get("contests") or []
    if not isinstance(rows, list):
        raise TypeError("Splash contests search response data must be a list")
    return rows


def _contest_summary(row: dict[str, Any]) -> dict[str, Any]:
    entries = row.get("entries") or {}
    settings = row.get("settings") or {}
    league = row.get("league") or {}
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "contest_type": row.get("contest_type"),
        "contest_type_alt_text": row.get("contest_type_alt_text"),
        "entry_fee_cents": row.get("entry_fee"),
        "entry_fee_dollars": row.get("entry_fee_in_dollars"),
        "prize_pool_cents": row.get("prize_pool"),
        "prize_pool_dollars": row.get("prize_pool_in_dollars"),
        "start_date": row.get("start_date"),
        "status": row.get("status"),
        "entries": {
            "filled": entries.get("filled"),
            "max": entries.get("max"),
            "max_per_user": entries.get("max_per_user"),
        },
        "scoring_type": settings.get("scoreType"),
        "expected_picks_count": settings.get("expectedPicksCount"),
        "drop_worst_count": settings.get("dropWorstCount"),
        "league": {
            "id": league.get("id"),
            "name": league.get("name"),
            "sport": league.get("sport"),
        },
    }


def _money_label(dollars: Any, cents: Any) -> str:
    if dollars is not None:
        return f"${float(dollars):g}"
    if cents is not None:
        return f"${int(cents) / 100:g}"
    return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
