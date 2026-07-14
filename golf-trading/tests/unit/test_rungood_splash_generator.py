from __future__ import annotations

from scripts import generate_rungood_splash_portfolios as generator
from src.fantasy.splash.models import (
    DataGolfScoreAnchor,
    SplashContestPlayerPool,
    SplashPlayer,
    SplashPlayerMapping,
    SplashPlayerMappingReviewItem,
    SplashTier,
)


def test_missing_splash_datagolf_rank_is_excluded_not_hard_review() -> None:
    player_pool = SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=(
            SplashTier(
                tier_id=1,
                number_per_tier=1,
                metric_name="datagolf_rank",
                max_players=2,
                players=(
                    _player("ranked", "Ranked Player", 10),
                    _player("unranked", "Unranked Player", None),
                ),
                inputs_hash="tier",
            ),
        ),
        player_mappings=(
            SplashPlayerMapping(
                splash_player_id="ranked",
                splash_player_name="Ranked Player",
                splash_datagolf_rank=10,
                datagolf_player_id="dg-ranked",
                datagolf_player_name="Ranked Player",
                datagolf_rank=10,
                inputs_hash="mapping",
            ),
        ),
        review_items=(
            SplashPlayerMappingReviewItem(
                splash_player_id="unranked",
                splash_player_name="Unranked Player",
                splash_datagolf_rank=None,
                reason="missing_splash_datagolf_rank",
                candidates=(),
                inputs_hash="review",
            ),
        ),
        inputs_hash="pool",
    )

    anchors = (_anchor("dg-ranked"),)
    eligible_mappings = generator._eligible_mappings(player_pool, anchors)

    assert generator._hard_review_items(player_pool, anchors) == []
    assert [player.name for player in generator._eligible_players_by_tier(player_pool, eligible_mappings)[1]] == [
        "Ranked Player"
    ]
    assert generator._ineligible_player_summary(player_pool, eligible_mappings) == {
        "policy": "players_missing_positive_splash_datagolf_rank_or_score_anchor_are_excluded_as_insufficient_data",
        "missing_datagolf_rank_by_tier": {"1": ["Unranked Player"]},
        "missing_datagolf_rank_count": 1,
        "missing_score_anchor_by_tier": {},
        "missing_score_anchor_count": 0,
    }


def test_ranked_mapping_failures_remain_hard_review() -> None:
    player_pool = SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=(
            SplashTier(
                tier_id=1,
                number_per_tier=1,
                metric_name="datagolf_rank",
                max_players=1,
                players=(_player("mismatch", "Rank Mismatch", 45),),
                inputs_hash="tier",
            ),
        ),
        player_mappings=(),
        review_items=(
            SplashPlayerMappingReviewItem(
                splash_player_id="mismatch",
                splash_player_name="Rank Mismatch",
                splash_datagolf_rank=45,
                reason="datagolf_rank_mismatch",
                candidates=("dg-rank-mismatch|Rank Mismatch|rank=44",),
                inputs_hash="review",
            ),
        ),
        inputs_hash="pool",
    )

    assert generator._hard_review_items(player_pool, ()) == [
        "tier_1_has_0_anchored_players_for_1_required",
        "unresolved_mapping:Rank Mismatch:datagolf_rank_mismatch",
    ]


def test_missing_score_anchor_excludes_player_until_tier_is_empty() -> None:
    player_pool = SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=(
            SplashTier(
                tier_id=1,
                number_per_tier=1,
                metric_name="datagolf_rank",
                max_players=2,
                players=(
                    _player("anchored", "Anchored Player", 10),
                    _player("missing-anchor", "Missing Anchor", 20),
                ),
                inputs_hash="tier",
            ),
        ),
        player_mappings=(
            _mapping("anchored", "Anchored Player", "dg-anchored", 10),
            _mapping("missing-anchor", "Missing Anchor", "dg-missing", 20),
        ),
        review_items=(),
        inputs_hash="pool",
    )
    anchors = (_anchor("dg-anchored"),)
    eligible_mappings = generator._eligible_mappings(player_pool, anchors)

    assert generator._hard_review_items(player_pool, anchors) == []
    assert [player.name for player in generator._eligible_players_by_tier(player_pool, eligible_mappings)[1]] == [
        "Anchored Player"
    ]
    assert generator._ineligible_player_summary(player_pool, eligible_mappings)[
        "missing_score_anchor_by_tier"
    ] == {"1": ["Missing Anchor"]}


def test_missing_score_anchor_blocks_when_tier_has_no_anchored_players() -> None:
    player_pool = SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=(
            SplashTier(
                tier_id=1,
                number_per_tier=1,
                metric_name="datagolf_rank",
                max_players=1,
                players=(_player("missing-anchor", "Missing Anchor", 20),),
                inputs_hash="tier",
            ),
        ),
        player_mappings=(_mapping("missing-anchor", "Missing Anchor", "dg-missing", 20),),
        review_items=(),
        inputs_hash="pool",
    )

    assert generator._hard_review_items(player_pool, ()) == [
        "tier_1_has_0_anchored_players_for_1_required"
    ]


def test_external_ownership_maps_datagolf_projection_to_splash_player_id() -> None:
    player_pool = SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=(),
        player_mappings=(
            _mapping("splash-ben", "Ben Griffin", "24968", 18),
            _mapping("splash-missing", "Missing Projection", "missing", 200),
        ),
        review_items=(),
        inputs_hash="pool",
    )

    ownership = generator._external_ownership_by_player_id(
        player_pool,
        {
            "projections": [
                {"dg_id": 24968, "player_name": "Griffin, Ben", "proj_ownership": 26.47},
                {"dg_id": 99999, "player_name": "Other, Player", "proj_ownership": 10.0},
            ]
        },
    )

    assert ownership == {"splash-ben": 26.47}


def _player(splash_player_id: str, name: str, datagolf_rank: int | None) -> SplashPlayer:
    return SplashPlayer(
        splash_player_id=splash_player_id,
        slate_player_id=f"slate-{splash_player_id}",
        slate_id="slate",
        name=name,
        tier_id=1,
        datagolf_rank=datagolf_rank,
        world_rank=datagolf_rank,
        scoring_avg=None,
        country=None,
        is_selectable=True,
        attributes={},
        inputs_hash=f"hash-{splash_player_id}",
    )


def _mapping(
    splash_player_id: str,
    name: str,
    datagolf_player_id: str,
    datagolf_rank: int,
) -> SplashPlayerMapping:
    return SplashPlayerMapping(
        splash_player_id=splash_player_id,
        splash_player_name=name,
        splash_datagolf_rank=datagolf_rank,
        datagolf_player_id=datagolf_player_id,
        datagolf_player_name=name,
        datagolf_rank=datagolf_rank,
        inputs_hash=f"mapping-{splash_player_id}",
    )


def _anchor(datagolf_player_id: str) -> DataGolfScoreAnchor:
    return DataGolfScoreAnchor(
        datagolf_player_id=datagolf_player_id,
        player_name="Ranked Player",
        datagolf_rank=10,
        make_cut_probability=0.75,
        made_cut_score_mean=-5.0,
        made_cut_score_sd=4.0,
        cut_rounds_score_mean=2.0,
        cut_rounds_score_sd=3.0,
        inputs_hash="anchor",
    )
