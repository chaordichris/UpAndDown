"""Build Splash-to-DataGolf rank rows from captured Splash tiers and DG player list."""

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
from src.fantasy.splash.parser import parse_player_pool  # noqa: E402
from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build DataGolf mapping rows for a captured Splash player-pool fixture."
    )
    parser.add_argument("--player-pools-fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--datagolf-player-list-fixture")
    parser.add_argument("--manual-overrides-fixture")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    player_pools = _load_json(_fixture_path(root, args.player_pools_fixture))
    datagolf_players = (
        _load_json(_fixture_path(root, args.datagolf_player_list_fixture))
        if args.datagolf_player_list_fixture
        else fetch_datagolf_player_list()
    )
    manual_overrides = (
        _load_json(_fixture_path(root, args.manual_overrides_fixture))
        if args.manual_overrides_fixture
        else []
    )
    rows, review = build_rank_rows(player_pools, datagolf_players, manual_overrides)
    _write_json(_fixture_path(root, args.output), rows)
    _write_json(_fixture_path(root, args.review_output), review)
    print(
        json.dumps(
            {
                "mapped_count": len(rows),
                "review_count": len(review["review_items"]),
                "output": args.output,
                "review_output": args.review_output,
                "artifact_hash": stable_hash({"rows": rows, "review": review}),
            },
            indent=2,
            sort_keys=True,
        )
    )


def fetch_datagolf_player_list() -> list[dict[str, Any]]:
    load_dotenv(".env")
    api_key = os.getenv("DATAGOLF_API_KEY")
    if not api_key:
        raise RuntimeError("DATAGOLF_API_KEY is not set")
    response = httpx.get(
        "https://feeds.datagolf.com/get-player-list",
        params={"key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise TypeError("DataGolf player list response must be a JSON array")
    return data


def build_rank_rows(
    player_pools_fixture: dict[str, Any],
    datagolf_players: list[dict[str, Any]],
    manual_overrides: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    datagolf_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in datagolf_players:
        display_name = _datagolf_display_name(str(row["player_name"]))
        datagolf_by_name.setdefault(_name_key(display_name), []).append(row)

    overrides_by_name = {
        _name_key(str(row["splash_player_name"])): row
        for row in manual_overrides or []
    }
    rows: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    for tier_id, tier_payload in sorted(player_pools_fixture.items(), key=lambda item: int(item[0])):
        tier = parse_player_pool(tier_payload, tier_id=int(tier_id))
        for player in tier.players:
            if player.datagolf_rank is None or player.datagolf_rank <= 0:
                review_items.append(
                    {
                        "tier_id": tier.tier_id,
                        "splash_player_name": player.name,
                        "splash_datagolf_rank": player.datagolf_rank,
                        "status": "excluded_missing_splash_datagolf_rank",
                        "candidates": [],
                    }
                )
                continue
            candidates = datagolf_by_name.get(_name_key(player.name), [])
            override = overrides_by_name.get(_name_key(player.name))
            if override is not None:
                if int(override["datagolf_rank"]) != player.datagolf_rank:
                    raise ValueError(
                        f"Manual override rank for {player.name} does not match Splash rank"
                    )
                rows.append(
                    {
                        "player_id": str(override["player_id"]),
                        "player_name": player.name,
                        "datagolf_rank": player.datagolf_rank,
                        "source": "manual_datagolf_field_override",
                        "raw_datagolf_player_name": override["raw_datagolf_player_name"],
                        "splash_tier": tier.tier_id,
                        "splash_player_id": player.splash_player_id,
                        "review_note": override.get("review_note"),
                    }
                )
                continue
            if len(candidates) != 1:
                review_items.append(
                    {
                        "tier_id": tier.tier_id,
                        "splash_player_name": player.name,
                        "splash_datagolf_rank": player.datagolf_rank,
                        "status": "no_exact_datagolf_name_match"
                        if not candidates
                        else "ambiguous_exact_datagolf_name_match",
                        "candidates": [
                            {
                                "dg_id": candidate.get("dg_id"),
                                "player_name": candidate.get("player_name"),
                                "display_name": _datagolf_display_name(str(candidate["player_name"])),
                            }
                            for candidate in candidates
                        ],
                    }
                )
                continue
            candidate = candidates[0]
            rows.append(
                {
                    "player_id": str(candidate["dg_id"]),
                    "player_name": player.name,
                    "datagolf_rank": player.datagolf_rank,
                    "source": "datagolf_player_list_exact_name_plus_splash_datagolf_rank",
                    "raw_datagolf_player_name": candidate["player_name"],
                    "splash_tier": tier.tier_id,
                    "splash_player_id": player.splash_player_id,
                }
            )

    review = {
        "policy": "DataGolf IDs come from exact normalized name matches after Last, First display conversion; ranks come from captured Splash datagolf_rank.",
        "mapped_count": len(rows),
        "review_count": len(review_items),
        "review_items": review_items,
        "manual_override_count": len(manual_overrides or []),
        "inputs_hash": stable_hash(
            {
                "player_pools_fixture": player_pools_fixture,
                "datagolf_player_count": len(datagolf_players),
                "manual_overrides": manual_overrides or [],
                "mapped_rows": rows,
                "review_items": review_items,
            }
        ),
    }
    return rows, review


def _datagolf_display_name(name: str) -> str:
    if "," not in name:
        return " ".join(name.split())
    last, first = [part.strip() for part in name.split(",", 1)]
    return " ".join(f"{first} {last}".split())


def _name_key(name: str) -> str:
    return " ".join(name.casefold().split())


if __name__ == "__main__":
    main()
