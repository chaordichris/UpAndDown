"""Preflight integrity gate for the Splash weekly workflow (SP-1).

Answers "can this week's data support a lineup card?" *before* any
simulation spend, with a structured report where every failure names the
script that repairs it. The portfolio generator already fails closed on bad
data; this module makes that blockage diagnosable and remediable.

Pure functions over the same parsed objects the generator consumes, so the
gate can never drift from the generator's own eligibility rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.fantasy.splash.models import (
    DataGolfScoreAnchor,
    SplashContestPlayerPool,
)
from src.storage.hashing import stable_hash

INTEGRITY_VERSION = "splash-preflight-v1"

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"

# Remediation hints: every failure points at the script that fixes it.
_REMEDIATION_ANCHORS = (
    "capture DataGolf enrichment (scripts/capture_datagolf_splash_enrichment.py), "
    "then rebuild anchors (scripts/build_splash_enriched_score_anchors.py); "
    "scripts/build_splash_score_anchor_todo.py lists exactly which players are missing"
)
_REMEDIATION_MAPPINGS = (
    "resolve via rank overrides "
    "(artifacts/splash-capture/rungood-datagolf-player-rank-overrides.json), "
    "then rebuild the rank fixture (scripts/build_splash_datagolf_rank_fixture.py)"
)
_REMEDIATION_REBUILD_ANCHORS = (
    "rebuild anchors (scripts/build_splash_enriched_score_anchors.py); "
    "do not hand-edit anchor rows"
)
_REMEDIATION_RECAPTURE = (
    "re-run capture (scripts/capture_splash_contest.py / "
    "scripts/capture_datagolf_splash_enrichment.py) to refresh stale fixtures"
)


@dataclass(frozen=True)
class IntegrityCheck:
    check_id: str
    severity: str  # block | warn
    passed: bool
    detail: str
    remediation: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SplashPreflightReport:
    checks: tuple[IntegrityCheck, ...]
    inputs_hash: str

    @property
    def blocking_failures(self) -> tuple[IntegrityCheck, ...]:
        return tuple(
            c for c in self.checks if not c.passed and c.severity == SEVERITY_BLOCK
        )

    @property
    def warnings(self) -> tuple[IntegrityCheck, ...]:
        return tuple(
            c for c in self.checks if not c.passed and c.severity == SEVERITY_WARN
        )

    @property
    def passed(self) -> bool:
        return not self.blocking_failures


def _anchored_splash_ids(
    player_pool: SplashContestPlayerPool,
    anchors: tuple[DataGolfScoreAnchor, ...],
) -> set[str]:
    anchor_dg_ids = {anchor.datagolf_player_id for anchor in anchors}
    return {
        mapping.splash_player_id
        for mapping in player_pool.player_mappings
        if mapping.datagolf_player_id in anchor_dg_ids
    }


def check_tier_anchor_coverage(
    player_pool: SplashContestPlayerPool,
    anchors: tuple[DataGolfScoreAnchor, ...],
) -> IntegrityCheck:
    """Every tier must have at least its required slots covered by anchored players."""
    anchored_ids = _anchored_splash_ids(player_pool, anchors)
    coverage: dict[str, dict[str, int]] = {}
    failing: list[str] = []
    for tier in player_pool.tiers:
        anchored = sum(1 for p in tier.players if p.splash_player_id in anchored_ids)
        coverage[str(tier.tier_id)] = {
            "anchored": anchored,
            "required": tier.number_per_tier,
            "pool_size": len(tier.players),
        }
        if anchored < tier.number_per_tier:
            failing.append(
                f"tier {tier.tier_id}: {anchored} anchored of "
                f"{tier.number_per_tier} required ({len(tier.players)} in pool)"
            )
    return IntegrityCheck(
        check_id="tier_anchor_coverage",
        severity=SEVERITY_BLOCK,
        passed=not failing,
        detail="; ".join(failing) if failing else "all tiers covered",
        remediation=_REMEDIATION_ANCHORS if failing else "",
        data={"coverage_by_tier": coverage},
    )


def check_tier_pool_depth(
    player_pool: SplashContestPlayerPool,
    anchors: tuple[DataGolfScoreAnchor, ...],
    min_depth_multiple: float,
) -> IntegrityCheck:
    """Warn when a tier barely clears its requirement — no real choices left."""
    anchored_ids = _anchored_splash_ids(player_pool, anchors)
    shallow: list[str] = []
    for tier in player_pool.tiers:
        anchored = sum(1 for p in tier.players if p.splash_player_id in anchored_ids)
        needed = tier.number_per_tier * min_depth_multiple
        if anchored < needed:
            shallow.append(
                f"tier {tier.tier_id}: {anchored} anchored, want >= {needed:.0f} "
                f"({min_depth_multiple}x of {tier.number_per_tier})"
            )
    return IntegrityCheck(
        check_id="tier_pool_depth",
        severity=SEVERITY_WARN,
        passed=not shallow,
        detail="; ".join(shallow) if shallow else "all tiers have selection depth",
        remediation=_REMEDIATION_ANCHORS if shallow else "",
    )


def check_unresolved_mappings(player_pool: SplashContestPlayerPool) -> IntegrityCheck:
    """Splash→DataGolf mapping problems (rank mismatches, unmatched names)."""
    unresolved = [
        item
        for item in player_pool.review_items
        if item.reason != "missing_splash_datagolf_rank"
    ]
    details = [
        f"{item.splash_player_name}: {item.reason}"
        + (f" (candidates: {', '.join(item.candidates)})" if item.candidates else "")
        for item in unresolved
    ]
    return IntegrityCheck(
        check_id="unresolved_mappings",
        severity=SEVERITY_BLOCK,
        passed=not unresolved,
        detail="; ".join(details) if details else "all mappings resolved",
        remediation=_REMEDIATION_MAPPINGS if unresolved else "",
        data={"unresolved_count": len(unresolved)},
    )


def check_missing_anchors(
    player_pool: SplashContestPlayerPool,
    anchors: tuple[DataGolfScoreAnchor, ...],
) -> IntegrityCheck:
    """Mapped players without a score anchor (excluded by policy → warn).

    Tier coverage decides whether these gaps block; this check names names.
    """
    anchor_dg_ids = {anchor.datagolf_player_id for anchor in anchors}
    missing = sorted(
        mapping.splash_player_name
        for mapping in player_pool.player_mappings
        if mapping.datagolf_player_id not in anchor_dg_ids
    )
    return IntegrityCheck(
        check_id="missing_anchors",
        severity=SEVERITY_WARN,
        passed=not missing,
        detail=(
            f"{len(missing)} mapped players lack anchors: {', '.join(missing)}"
            if missing
            else "every mapped player has a score anchor"
        ),
        remediation=_REMEDIATION_ANCHORS if missing else "",
        data={"missing_players": missing},
    )


def check_unranked_players(player_pool: SplashContestPlayerPool) -> IntegrityCheck:
    """Players excluded for missing/nonpositive DataGolf rank (policy exclusion)."""
    unranked = sorted(
        player.name
        for tier in player_pool.tiers
        for player in tier.players
        if player.datagolf_rank is None or player.datagolf_rank <= 0
    )
    return IntegrityCheck(
        check_id="unranked_players",
        severity=SEVERITY_WARN,
        passed=not unranked,
        detail=(
            f"{len(unranked)} players lack a positive DataGolf rank: "
            f"{', '.join(unranked)}"
            if unranked
            else "all pool players carry a DataGolf rank"
        ),
        remediation=_REMEDIATION_MAPPINGS if unranked else "",
        data={"unranked_players": unranked},
    )


def check_anchor_sanity(anchors: tuple[DataGolfScoreAnchor, ...]) -> IntegrityCheck:
    """Anchor rows must be probabilistically sane before they price anything."""
    problems: list[str] = []
    for anchor in anchors:
        if not 0.0 < anchor.make_cut_probability < 1.0:
            problems.append(
                f"{anchor.player_name}: make_cut_probability "
                f"{anchor.make_cut_probability} outside (0, 1)"
            )
        if anchor.made_cut_score_sd <= 0 or anchor.cut_rounds_score_sd <= 0:
            problems.append(f"{anchor.player_name}: non-positive score SD")
        if anchor.datagolf_rank <= 0:
            problems.append(f"{anchor.player_name}: non-positive datagolf_rank")
    if not anchors:
        problems.append("anchor set is empty")
    return IntegrityCheck(
        check_id="anchor_sanity",
        severity=SEVERITY_BLOCK,
        passed=not problems,
        detail="; ".join(problems) if problems else f"{len(anchors)} anchors sane",
        remediation=_REMEDIATION_REBUILD_ANCHORS if problems else "",
    )


def check_fixture_freshness(
    fixture_ages_hours: dict[str, float],
    max_age_hours: float,
) -> IntegrityCheck:
    """Stale captures block: pricing this week's contest on last week's data."""
    stale = {
        name: round(age, 1)
        for name, age in sorted(fixture_ages_hours.items())
        if age > max_age_hours
    }
    return IntegrityCheck(
        check_id="fixture_freshness",
        severity=SEVERITY_BLOCK,
        passed=not stale,
        detail=(
            "; ".join(f"{n}: {a}h old (max {max_age_hours}h)" for n, a in stale.items())
            if stale
            else f"all fixtures within {max_age_hours}h"
        ),
        remediation=_REMEDIATION_RECAPTURE if stale else "",
        data={"stale_fixtures": stale},
    )


def run_preflight(
    player_pool: SplashContestPlayerPool,
    anchors: tuple[DataGolfScoreAnchor, ...],
    fixture_ages_hours: dict[str, float] | None = None,
    *,
    max_fixture_age_hours: float = 72.0,
    min_depth_multiple: float = 2.0,
) -> SplashPreflightReport:
    checks: list[IntegrityCheck] = [
        check_tier_anchor_coverage(player_pool, anchors),
        check_tier_pool_depth(player_pool, anchors, min_depth_multiple),
        check_unresolved_mappings(player_pool),
        check_missing_anchors(player_pool, anchors),
        check_unranked_players(player_pool),
        check_anchor_sanity(anchors),
    ]
    if fixture_ages_hours is not None:
        checks.append(check_fixture_freshness(fixture_ages_hours, max_fixture_age_hours))
    return SplashPreflightReport(
        checks=tuple(checks),
        inputs_hash=stable_hash(
            {
                "version": INTEGRITY_VERSION,
                "pool": player_pool.inputs_hash,
                "anchors": [a.inputs_hash for a in anchors],
                "max_fixture_age_hours": max_fixture_age_hours,
                "min_depth_multiple": min_depth_multiple,
            }
        ),
    )


def report_to_artifact(report: SplashPreflightReport) -> dict[str, Any]:
    return {
        "artifact_type": "splash_preflight_report",
        "version": INTEGRITY_VERSION,
        "passed": report.passed,
        "blocking_failure_count": len(report.blocking_failures),
        "warning_count": len(report.warnings),
        "checks": [
            {
                "check_id": c.check_id,
                "severity": c.severity,
                "passed": c.passed,
                "detail": c.detail,
                "remediation": c.remediation,
                "data": c.data,
            }
            for c in report.checks
        ],
        "inputs_hash": report.inputs_hash,
    }
