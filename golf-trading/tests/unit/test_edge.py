"""
Unit tests for src/risk/edge.py

Covers:
  - compute_edge: correct edge calculation, threshold checks, sleeve labelling
  - compute_two_way_edges: vig removed once for both sides; edges sum to zero
    for a fair market (no alpha); positive edge on one side means negative on other
  - Core vs convex sleeve routing
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from src.pricing.fair_price import METHOD_HARVILLE, FairPriceResult
from src.risk.edge import EdgeResult, apply_fdr_control, compute_edge, compute_two_way_edges

NOW = datetime(2024, 3, 11, 14, 0, 0, tzinfo=UTC)
TOL = 1e-5


def _fair(datagolf_id: str, fair_prob: float, market_type: str = "matchup_2ball",
          opponent_id: str | None = None) -> FairPriceResult:
    return FairPriceResult(
        market_type=market_type,
        datagolf_id=datagolf_id,
        opponent_id=opponent_id,
        fair_prob=fair_prob,
        method=METHOD_HARVILLE,
        as_of=NOW,
    )


# ---------------------------------------------------------------------------
# compute_edge
# ---------------------------------------------------------------------------

def test_edge_positive_when_fair_gt_book() -> None:
    """Fair = 0.55, book -110 → no-vig ≈ 0.50 → edge ≈ +0.05."""
    fair = _fair("scheffler", 0.55)
    # -110 / -110 two-way market; implied each = 100/210 ≈ 0.5238, sum ≈ 1.0476
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.edge > 0
    assert math.isclose(result.book_no_vig_prob, 0.5, abs_tol=0.01)


def test_edge_negative_when_fair_lt_book() -> None:
    """Fair = 0.40, book -110 → no-vig ≈ 0.50 → edge ≈ -0.10."""
    fair = _fair("mcilroy", 0.40)
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.edge < 0
    assert not result.passes_threshold


def test_edge_passes_threshold_core() -> None:
    """Edge of 5% should pass the 3% core threshold."""
    fair = _fair("scheffler", 0.55)
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.passes_threshold


def test_edge_fails_convex_threshold() -> None:
    """5% edge on an outright (convex) market fails the 8% threshold."""
    fair = _fair("scheffler", 0.55, market_type="outright_win")
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.sleeve == "convex"
    assert not result.passes_threshold


def test_edge_passes_convex_threshold() -> None:
    """10% edge on outright passes the 8% convex threshold."""
    fair = _fair("scheffler", 0.60, market_type="outright_win")
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.passes_threshold


def test_edge_sleeve_core_for_matchup() -> None:
    fair = _fair("scheffler", 0.55, market_type="matchup_2ball")
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.sleeve == "core"


def test_edge_book_american_odds_preserved() -> None:
    fair = _fair("scheffler", 0.55)
    result = compute_edge(
        fair=fair,
        book_american_odds=-145,
        market_implied_probs=[0.592, 0.455],
        book_id="fanduel",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.book_american_odds == -145
    assert result.book_id == "fanduel"


def test_edge_uncertainty_fields_default_to_legacy_behavior() -> None:
    fair = _fair("scheffler", 0.55)
    result = compute_edge(
        fair=fair,
        book_american_odds=-110,
        market_implied_probs=[0.5238, 0.5238],
        book_id="dk",
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )
    assert result.edge_sd is None
    assert result.p_value is None
    assert result.passes_fdr is True


def test_apply_fdr_control_disabled_preserves_legacy_metadata() -> None:
    edge = _edge_result(edge=0.05, edge_sd=0.01, p_value=0.001, passes_fdr=False)

    result = apply_fdr_control([edge], enabled=False, q_core=0.20, q_convex=0.10)

    assert result[0].edge_sd == 0.01
    assert result[0].p_value is None
    assert result[0].passes_fdr is True


def test_apply_fdr_control_populates_p_values_by_sleeve() -> None:
    strong = _edge_result(datagolf_id="strong", edge=0.08, edge_sd=0.01)
    weak = _edge_result(datagolf_id="weak", edge=0.01, edge_sd=0.05)

    results = apply_fdr_control([strong, weak], enabled=True, q_core=0.20, q_convex=0.10)

    assert results[0].p_value is not None
    assert results[0].passes_fdr is True
    assert results[1].p_value is not None
    assert results[1].passes_fdr is False


def test_apply_fdr_control_requires_edge_sd_when_enabled() -> None:
    with pytest.raises(ValueError, match="edge_sd"):
        apply_fdr_control(
            [_edge_result(edge_sd=None)],
            enabled=True,
            q_core=0.20,
            q_convex=0.10,
        )


# ---------------------------------------------------------------------------
# compute_two_way_edges
# ---------------------------------------------------------------------------

def test_two_way_edges_both_sides_returned() -> None:
    fair_p1 = _fair("scheffler", 0.60, opponent_id="mcilroy")
    fair_p2 = _fair("mcilroy", 0.40, opponent_id="scheffler")
    e1, e2 = compute_two_way_edges(
        fair_p1, fair_p2,
        book_odds_p1=-145, book_odds_p2=120,
        book_id="dk",
        min_edge_core=0.03, min_edge_convex=0.08,
    )
    assert e1.datagolf_id == "scheffler"
    assert e2.datagolf_id == "mcilroy"


def test_two_way_edges_book_probs_sum_to_one() -> None:
    """After vig removal the two no-vig book probs must sum to 1.0."""
    fair_p1 = _fair("scheffler", 0.60, opponent_id="mcilroy")
    fair_p2 = _fair("mcilroy", 0.40, opponent_id="scheffler")
    e1, e2 = compute_two_way_edges(
        fair_p1, fair_p2,
        book_odds_p1=-145, book_odds_p2=120,
        book_id="dk",
        min_edge_core=0.03, min_edge_convex=0.08,
    )
    assert math.isclose(e1.book_no_vig_prob + e2.book_no_vig_prob, 1.0, abs_tol=1e-6)


def test_two_way_edges_opposite_signs() -> None:
    """If p1 has a positive edge, p2 should have a negative edge (same market)."""
    # DK prices scheffler at -110 (50% no-vig); fair is 60% → p1 has +10% edge
    fair_p1 = _fair("scheffler", 0.60, opponent_id="mcilroy")
    fair_p2 = _fair("mcilroy", 0.40, opponent_id="scheffler")
    e1, e2 = compute_two_way_edges(
        fair_p1, fair_p2,
        book_odds_p1=-110, book_odds_p2=-110,
        book_id="dk",
        min_edge_core=0.03, min_edge_convex=0.08,
    )
    assert e1.edge > 0
    assert e2.edge < 0


def test_two_way_edges_power_method() -> None:
    """Power vig removal should also produce valid results."""
    fair_p1 = _fair("scheffler", 0.60, opponent_id="mcilroy")
    fair_p2 = _fair("mcilroy", 0.40, opponent_id="scheffler")
    e1, e2 = compute_two_way_edges(
        fair_p1, fair_p2,
        book_odds_p1=-145, book_odds_p2=120,
        book_id="dk",
        min_edge_core=0.03, min_edge_convex=0.08,
        vig_method="power",
    )
    assert math.isclose(e1.book_no_vig_prob + e2.book_no_vig_prob, 1.0, abs_tol=1e-6)


def _edge_result(
    *,
    datagolf_id: str = "scheffler",
    edge: float = 0.05,
    edge_sd: float | None = 0.01,
    p_value: float | None = None,
    passes_fdr: bool = True,
    sleeve: str = "core",
) -> EdgeResult:
    return EdgeResult(
        datagolf_id=datagolf_id,
        opponent_id=None,
        market_type="matchup_2ball",
        book_id="dk",
        fair_prob=0.55,
        book_no_vig_prob=0.55 - edge,
        edge=edge,
        sleeve=sleeve,
        passes_threshold=True,
        book_american_odds=-110,
        edge_sd=edge_sd,
        p_value=p_value,
        passes_fdr=passes_fdr,
    )
