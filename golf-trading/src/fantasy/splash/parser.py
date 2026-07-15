"""Parsers for public Splash contest API payloads."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.fantasy.splash.mapping import (
    DataGolfPlayerReference,
    datagolf_references_from_rows,
    map_players_to_datagolf,
)
from src.fantasy.splash.models import (
    SplashContest,
    SplashContestPlayerPool,
    SplashPayout,
    SplashPlayer,
    SplashRosterRule,
    SplashScoringRule,
    SplashSlate,
    SplashTier,
)
from src.storage.hashing import stable_hash


def parse_contest_detail(payload: dict[str, Any]) -> SplashContest:
    """Parse a Splash contest-detail capture envelope or response body."""
    body = _response_body(payload)
    inputs_hash = stable_hash(body)
    settings = body.get("settings") or {}
    tier_settings = body.get("tier_rules_settings") or {}
    entries = body.get("entries") or {}

    number_of_tiers_raw = tier_settings.get("numberOfTiers")
    if not number_of_tiers_raw or int(number_of_tiers_raw) <= 0:
        raise ValueError(
            "Splash contest payload is missing or has a non-positive "
            f"tier_rules_settings.numberOfTiers (got {number_of_tiers_raw!r}) — "
            "cannot determine contest tier structure. A response-shape drift "
            "would otherwise silently produce a zero-tier contest here."
        )

    roster_rule = SplashRosterRule(
        expected_picks_count=int(settings.get("expectedPicksCount") or 0),
        number_of_tiers=int(number_of_tiers_raw),
        number_per_tier=int(tier_settings.get("numberPerTier") or 0),
        drop_worst_count=int(settings.get("dropWorstCount") or 0),
        metric_name=tier_settings.get("metricName"),
        score_type=settings.get("scoreType"),
        description=body.get("roster_requirements"),
        inputs_hash=inputs_hash,
    )

    tiers = tuple(
        SplashTier(
            tier_id=tier_id,
            number_per_tier=roster_rule.number_per_tier,
            metric_name=roster_rule.metric_name,
            max_players=_optional_int((body.get("tier_rules") or {}).get("maxPlayersPerTier")),
            players=(),
            inputs_hash=inputs_hash,
        )
        for tier_id in range(1, roster_rule.number_of_tiers + 1)
    )

    return SplashContest(
        splash_id=str(body["id"]),
        name=str(body["name"]),
        contest_type=str(body["contest_type"]),
        status=str(body["status"]),
        entry_fee_cents=int(body["entry_fee"]),
        entry_fee_dollars=float(body["entry_fee_in_dollars"]),
        prize_pool_cents=int(body["prize_pool"]),
        prize_pool_dollars=float(body["prize_pool_in_dollars"]),
        filled_entries=_optional_int(entries.get("filled")),
        max_entries=_optional_int(entries.get("max")),
        max_entries_per_user=_optional_int(entries.get("max_per_user")),
        payout_ladder=tuple(_parse_payouts(body.get("payout_schedule") or [], inputs_hash)),
        scoring_rules=tuple(_parse_scoring_rules(body.get("rules") or "", inputs_hash)),
        roster_rule=roster_rule,
        slates=tuple(_parse_slates(body.get("slates") or [], inputs_hash)),
        tiers=tiers,
        inputs_hash=inputs_hash,
    )


def parse_player_pool(
    payload: dict[str, Any],
    *,
    tier_id: int | None = None,
) -> SplashTier:
    """Parse a Splash player-pool response into one tier of players."""
    body = _response_body(payload)
    inputs_hash = stable_hash(body)
    players = tuple(_parse_player(row, tier_id, inputs_hash) for row in body.get("data", []))

    return SplashTier(
        tier_id=tier_id or 0,
        number_per_tier=1,
        metric_name="datagolf_rank" if any(p.datagolf_rank is not None for p in players) else None,
        max_players=body.get("total"),
        players=players,
        inputs_hash=inputs_hash,
    )


def parse_contest_player_pool(
    contest: SplashContest,
    player_pool_payloads_by_tier: dict[int | str, dict[str, Any]],
    datagolf_player_rows: list[dict[str, Any]] | tuple[DataGolfPlayerReference, ...],
) -> SplashContestPlayerPool:
    """Parse all tier player-pool pages and attach deterministic DG mappings."""
    normalized_payloads = {
        int(tier_id): payload for tier_id, payload in player_pool_payloads_by_tier.items()
    }
    expected_tier_ids = {tier.tier_id for tier in contest.tiers}
    supplied_tier_ids = set(normalized_payloads)
    missing_tiers = expected_tier_ids - supplied_tier_ids
    if missing_tiers:
        raise ValueError(f"Missing Splash player-pool payloads for tier ids: {sorted(missing_tiers)}")

    contest_tiers = {tier.tier_id: tier for tier in contest.tiers}
    tiers = []
    for tier_id in sorted(expected_tier_ids):
        parsed_tier = parse_player_pool(normalized_payloads[tier_id], tier_id=tier_id)
        contest_tier = contest_tiers[tier_id]
        tiers.append(
            SplashTier(
                tier_id=tier_id,
                number_per_tier=contest_tier.number_per_tier,
                metric_name=contest_tier.metric_name,
                max_players=parsed_tier.max_players,
                players=parsed_tier.players,
                inputs_hash=stable_hash([contest_tier, parsed_tier]),
            )
        )

    players = tuple(player for tier in tiers for player in tier.players)
    datagolf_players = (
        datagolf_player_rows
        if all(isinstance(row, DataGolfPlayerReference) for row in datagolf_player_rows)
        else datagolf_references_from_rows(list(datagolf_player_rows))
    )
    mappings, review_items = map_players_to_datagolf(players, tuple(datagolf_players))

    if not contest.slates:
        raise ValueError("Splash contest has no slates for player-pool extraction")

    return SplashContestPlayerPool(
        contest_id=contest.splash_id,
        slate_id=contest.slates[0].splash_id,
        tiers=tuple(tiers),
        player_mappings=mappings,
        review_items=review_items,
        inputs_hash=stable_hash(
            {
                "contest": contest,
                "tiers": tiers,
                "mappings": mappings,
                "review_items": review_items,
            }
        ),
    )


def _response_body(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("response_body", payload)
    if not isinstance(body, dict):
        raise TypeError("Splash payload response_body must be a JSON object")
    return body


def _parse_payouts(rows: list[dict[str, Any]], inputs_hash: str) -> list[SplashPayout]:
    return [
        SplashPayout(
            label=str(row["label"]),
            start_rank=_rank_bounds(str(row["label"]))[0],
            end_rank=_rank_bounds(str(row["label"]))[1],
            amount_cents=_money_to_cents(str(row["value"])),
            order=int(row.get("order") or 0),
            inputs_hash=inputs_hash,
        )
        for row in rows
    ]


def _rank_bounds(label: str) -> tuple[int, int]:
    ranks = [int(value) for value in re.findall(r"\d+", label)]
    if not ranks:
        raise ValueError(f"Could not parse payout rank label: {label}")
    if len(ranks) == 1:
        return ranks[0], ranks[0]
    return ranks[0], ranks[1]


def _money_to_cents(value: str) -> int:
    clean = value.replace("$", "").replace(",", "").strip()
    return int((Decimal(clean) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_scoring_rules(rules: str, inputs_hash: str) -> list[SplashScoringRule]:
    parsed = []
    for line in rules.splitlines():
        description = line.strip()
        if not description:
            continue
        match = re.match(r"^(-?\d+(?:\.\d+)?)\s+fantasy points?", description)
        parsed.append(
            SplashScoringRule(
                description=description,
                points=float(match.group(1)) if match else None,
                inputs_hash=inputs_hash,
            )
        )
    return parsed


def _parse_slates(rows: list[dict[str, Any]], inputs_hash: str) -> list[SplashSlate]:
    slates = []
    for row in rows:
        state = _first_game_state(row)
        purse = row.get("purse") or {}
        slates.append(
            SplashSlate(
                splash_id=str(row["id"]),
                name=str(row["name"]),
                status=str(row["status"]),
                start_date=_parse_datetime(row.get("start_date")),
                end_date=_parse_datetime(row.get("end_date")),
                sport=state.get("sport"),
                league=state.get("league"),
                purse_cents=_optional_int(purse.get("current")),
                inputs_hash=inputs_hash,
            )
        )
    return slates


def _first_game_state(slate: dict[str, Any]) -> dict[str, Any]:
    games = slate.get("games") or []
    if not games:
        return {}
    state = games[0].get("state") or {}
    return state if isinstance(state, dict) else {}


def _parse_player(row: dict[str, Any], tier_id: int | None, inputs_hash: str) -> SplashPlayer:
    attributes = row.get("attributes") or {}
    return SplashPlayer(
        splash_player_id=str(row["playerId"]),
        slate_player_id=str(row["id"]),
        slate_id=str(row["slateId"]),
        name=str(row["name"]),
        tier_id=tier_id,
        datagolf_rank=_optional_int(attributes.get("datagolf_rank")),
        world_rank=_optional_int(attributes.get("world_rank")),
        scoring_avg=_optional_float(attributes.get("scoring_avg")),
        country=attributes.get("country"),
        is_selectable=bool(row.get("isPlayerSelectable")),
        attributes=dict(attributes),
        inputs_hash=inputs_hash,
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
