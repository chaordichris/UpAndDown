"""Tests for the Splash preflight integrity gate (SP-1)."""

from __future__ import annotations

from dataclasses import replace

from src.fantasy.splash.integrity import (
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    check_anchor_sanity,
    check_fixture_freshness,
    check_missing_anchors,
    check_tier_anchor_coverage,
    check_tier_pool_depth,
    check_unranked_players,
    check_unresolved_mappings,
    report_to_artifact,
    run_preflight,
)
from src.fantasy.splash.models import (
    DataGolfScoreAnchor,
    SplashContestPlayerPool,
    SplashPlayer,
    SplashPlayerMapping,
    SplashPlayerMappingReviewItem,
    SplashTier,
)


def _player(splash_id: str, name: str, rank: int | None, tier_id: int = 1) -> SplashPlayer:
    return SplashPlayer(
        splash_player_id=splash_id,
        slate_player_id=f"slate-{splash_id}",
        slate_id="slate",
        name=name,
        tier_id=tier_id,
        datagolf_rank=rank,
        world_rank=rank,
        scoring_avg=None,
        country=None,
        is_selectable=True,
        attributes={},
        inputs_hash=f"hash-{splash_id}",
    )


def _mapping(splash_id: str, name: str, dg_id: str, rank: int) -> SplashPlayerMapping:
    return SplashPlayerMapping(
        splash_player_id=splash_id,
        splash_player_name=name,
        splash_datagolf_rank=rank,
        datagolf_player_id=dg_id,
        datagolf_player_name=name,
        datagolf_rank=rank,
        inputs_hash=f"mapping-{splash_id}",
    )


def _anchor(dg_id: str, name: str = "Player") -> DataGolfScoreAnchor:
    return DataGolfScoreAnchor(
        datagolf_player_id=dg_id,
        player_name=name,
        datagolf_rank=10,
        make_cut_probability=0.75,
        made_cut_score_mean=-5.0,
        made_cut_score_sd=4.0,
        cut_rounds_score_mean=2.0,
        cut_rounds_score_sd=3.0,
        inputs_hash=f"anchor-{dg_id}",
    )


def _tier(tier_id: int, players: tuple[SplashPlayer, ...], required: int = 1) -> SplashTier:
    return SplashTier(
        tier_id=tier_id,
        number_per_tier=required,
        metric_name=None,
        max_players=len(players),
        players=players,
        inputs_hash=f"tier-{tier_id}",
    )


def _pool(
    tiers: tuple[SplashTier, ...],
    mappings: tuple[SplashPlayerMapping, ...],
    review_items: tuple[SplashPlayerMappingReviewItem, ...] = (),
) -> SplashContestPlayerPool:
    return SplashContestPlayerPool(
        contest_id="contest",
        slate_id="slate",
        tiers=tiers,
        player_mappings=mappings,
        review_items=review_items,
        inputs_hash="pool",
    )


def _clean_pool() -> tuple[SplashContestPlayerPool, tuple[DataGolfScoreAnchor, ...]]:
    """Two tiers, fully mapped and anchored, with selection depth."""
    players_t1 = tuple(_player(f"p1{i}", f"Tier1 P{i}", 10 + i, 1) for i in range(3))
    players_t2 = tuple(_player(f"p2{i}", f"Tier2 P{i}", 40 + i, 2) for i in range(3))
    all_players = players_t1 + players_t2
    mappings = tuple(
        _mapping(p.splash_player_id, p.name, f"dg-{p.splash_player_id}", p.datagolf_rank)
        for p in all_players
    )
    anchors = tuple(_anchor(f"dg-{p.splash_player_id}", p.name) for p in all_players)
    pool = _pool((_tier(1, players_t1), _tier(2, players_t2)), mappings)
    return pool, anchors


class TestTierAnchorCoverage:
    def test_passes_when_all_tiers_covered(self) -> None:
        pool, anchors = _clean_pool()
        check = check_tier_anchor_coverage(pool, anchors)
        assert check.passed
        assert check.severity == SEVERITY_BLOCK

    def test_blocks_and_names_the_failing_tier(self) -> None:
        pool, anchors = _clean_pool()
        anchors_missing_t2 = tuple(a for a in anchors if "p2" not in a.datagolf_player_id)
        check = check_tier_anchor_coverage(pool, anchors_missing_t2)
        assert not check.passed
        assert "tier 2: 0 anchored of 1 required" in check.detail
        assert "build_splash_enriched_score_anchors" in check.remediation
        assert check.data["coverage_by_tier"]["2"]["anchored"] == 0

    def test_reproduces_generator_blocking_condition(self) -> None:
        # The July rungood failure: mapped player, zero anchors → coverage blocks.
        player = _player("solo", "Solo Player", 20)
        pool = _pool(
            (_tier(1, (player,)),),
            (_mapping("solo", "Solo Player", "dg-solo", 20),),
        )
        check = check_tier_anchor_coverage(pool, ())
        assert not check.passed


class TestPoolDepth:
    def test_warns_when_tier_barely_clears_requirement(self) -> None:
        player = _player("solo", "Solo Player", 20)
        pool = _pool(
            (_tier(1, (player,), required=1),),
            (_mapping("solo", "Solo Player", "dg-solo", 20),),
        )
        check = check_tier_pool_depth(pool, (_anchor("dg-solo"),), min_depth_multiple=2.0)
        assert not check.passed
        assert check.severity == SEVERITY_WARN

    def test_passes_with_depth(self) -> None:
        pool, anchors = _clean_pool()
        assert check_tier_pool_depth(pool, anchors, 2.0).passed


class TestMappings:
    def test_blocks_on_unresolved_mapping_with_candidates(self) -> None:
        item = SplashPlayerMappingReviewItem(
            splash_player_id="x",
            splash_player_name="Rank Mismatch",
            splash_datagolf_rank=30,
            reason="datagolf_rank_mismatch",
            candidates=("Some Candidate",),
            inputs_hash="review",
        )
        pool = _pool((), (), review_items=(item,))
        check = check_unresolved_mappings(pool)
        assert not check.passed
        assert "Rank Mismatch: datagolf_rank_mismatch" in check.detail
        assert "Some Candidate" in check.detail
        assert "rank-overrides" in check.remediation

    def test_missing_rank_reason_is_not_blocking_here(self) -> None:
        item = SplashPlayerMappingReviewItem(
            splash_player_id="x",
            splash_player_name="No Rank",
            splash_datagolf_rank=None,
            reason="missing_splash_datagolf_rank",
            candidates=(),
            inputs_hash="review",
        )
        pool = _pool((), (), review_items=(item,))
        assert check_unresolved_mappings(pool).passed


class TestAnchorsAndPlayers:
    def test_missing_anchor_names_players(self) -> None:
        pool, anchors = _clean_pool()
        check = check_missing_anchors(pool, anchors[:-1])
        assert not check.passed
        assert check.severity == SEVERITY_WARN
        assert "Tier2 P2" in check.detail

    def test_unranked_players_warn(self) -> None:
        pool = _pool((_tier(1, (_player("u", "Unranked Guy", None),)),), ())
        check = check_unranked_players(pool)
        assert not check.passed
        assert "Unranked Guy" in check.detail

    def test_anchor_sanity_blocks_bad_probability_and_sd(self) -> None:
        bad_prob = replace(_anchor("a", "Bad Prob"), make_cut_probability=1.0)
        bad_sd = replace(_anchor("b", "Bad SD"), made_cut_score_sd=0.0)
        check = check_anchor_sanity((bad_prob, bad_sd))
        assert not check.passed
        assert "Bad Prob" in check.detail and "Bad SD" in check.detail

    def test_empty_anchor_set_blocks(self) -> None:
        assert not check_anchor_sanity(()).passed


class TestFreshness:
    def test_stale_fixture_blocks_with_age(self) -> None:
        check = check_fixture_freshness({"contest": 100.0, "anchors": 1.0}, 72.0)
        assert not check.passed
        assert "contest: 100.0h old" in check.detail
        assert "anchors" not in check.data["stale_fixtures"]

    def test_fresh_fixtures_pass(self) -> None:
        assert check_fixture_freshness({"contest": 1.0}, 72.0).passed


class TestRunPreflight:
    def test_clean_inputs_pass_end_to_end(self) -> None:
        pool, anchors = _clean_pool()
        report = run_preflight(pool, anchors, {"contest": 1.0})
        assert report.passed
        assert report.blocking_failures == ()
        assert len(report.inputs_hash) == 64

    def test_blocked_report_and_artifact_shape(self) -> None:
        pool, _ = _clean_pool()
        report = run_preflight(pool, (), {"contest": 100.0})
        assert not report.passed
        failing_ids = {c.check_id for c in report.blocking_failures}
        assert {"tier_anchor_coverage", "anchor_sanity", "fixture_freshness"} <= failing_ids
        artifact = report_to_artifact(report)
        assert artifact["passed"] is False
        assert artifact["blocking_failure_count"] == len(report.blocking_failures)
        assert all("remediation" in c for c in artifact["checks"])

    def test_deterministic_inputs_hash(self) -> None:
        pool, anchors = _clean_pool()
        a = run_preflight(pool, anchors)
        b = run_preflight(pool, anchors)
        assert a.inputs_hash == b.inputs_hash
