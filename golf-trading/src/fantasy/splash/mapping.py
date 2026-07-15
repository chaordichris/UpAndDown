"""Deterministic Splash to DataGolf player ID mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.fantasy.splash.models import (
    SplashPlayer,
    SplashPlayerMapping,
    SplashPlayerMappingReviewItem,
)
from src.storage.hashing import stable_hash


@dataclass(frozen=True)
class DataGolfPlayerReference:
    datagolf_player_id: str
    name: str
    datagolf_rank: int


def datagolf_references_from_rows(rows: list[dict[str, Any]]) -> tuple[DataGolfPlayerReference, ...]:
    """Build DataGolf references from rows that already include rank evidence."""
    return tuple(
        DataGolfPlayerReference(
            datagolf_player_id=str(row["player_id"]),
            name=str(row["player_name"]),
            datagolf_rank=int(_rank_value(row)),
        )
        for row in rows
    )


def map_players_to_datagolf(
    players: tuple[SplashPlayer, ...],
    datagolf_players: tuple[DataGolfPlayerReference, ...],
) -> tuple[tuple[SplashPlayerMapping, ...], tuple[SplashPlayerMappingReviewItem, ...]]:
    """Map players only when exact normalized name and rank both agree."""
    by_name: dict[str, list[DataGolfPlayerReference]] = {}
    for player in datagolf_players:
        by_name.setdefault(_name_key(player.name), []).append(player)

    mappings: list[SplashPlayerMapping] = []
    review_items: list[SplashPlayerMappingReviewItem] = []

    for player in players:
        inputs_hash = stable_hash(
            {
                "splash_player_id": player.splash_player_id,
                "splash_name": player.name,
                "splash_datagolf_rank": player.datagolf_rank,
                "datagolf_candidates": by_name.get(_name_key(player.name), []),
            }
        )
        candidates = by_name.get(_name_key(player.name), [])
        if player.datagolf_rank is None:
            review_items.append(
                _review_item(player, "missing_splash_datagolf_rank", candidates, inputs_hash)
            )
            continue
        if not candidates:
            review_items.append(_review_item(player, "no_exact_name_match", (), inputs_hash))
            continue
        if len(candidates) > 1:
            review_items.append(_review_item(player, "ambiguous_exact_name_match", candidates, inputs_hash))
            continue

        candidate = candidates[0]
        if candidate.datagolf_rank != player.datagolf_rank:
            review_items.append(_review_item(player, "datagolf_rank_mismatch", candidates, inputs_hash))
            continue

        mappings.append(
            SplashPlayerMapping(
                splash_player_id=player.splash_player_id,
                splash_player_name=player.name,
                splash_datagolf_rank=player.datagolf_rank,
                datagolf_player_id=candidate.datagolf_player_id,
                datagolf_player_name=candidate.name,
                datagolf_rank=candidate.datagolf_rank,
                inputs_hash=inputs_hash,
            )
        )

    return tuple(mappings), tuple(review_items)


def _rank_value(row: dict[str, Any]) -> Any:
    for key in ("datagolf_rank", "dg_rank", "rank"):
        if row.get(key) is not None:
            return row[key]
    raise KeyError("DataGolf player row must include datagolf_rank, dg_rank, or rank")


def _review_item(
    player: SplashPlayer,
    reason: str,
    candidates: tuple[DataGolfPlayerReference, ...] | list[DataGolfPlayerReference],
    inputs_hash: str,
) -> SplashPlayerMappingReviewItem:
    return SplashPlayerMappingReviewItem(
        splash_player_id=player.splash_player_id,
        splash_player_name=player.name,
        splash_datagolf_rank=player.datagolf_rank,
        reason=reason,
        candidates=tuple(
            f"{candidate.datagolf_player_id}|{candidate.name}|rank={candidate.datagolf_rank}"
            for candidate in candidates
        ),
        inputs_hash=inputs_hash,
    )


def _name_key(name: str) -> str:
    return " ".join(name.casefold().split())
