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
from datetime import datetime, timezone

import pytest

from src.pricing.fair_price import FairPriceResult, METHOD_HARVILLE
from src.risk.edge import EdgeResult, compute_edge, compute_two_way_edges

NOW = datetime(2024, 3, 11, 14, 0, 0, tzinfo=timezone.utc)
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
