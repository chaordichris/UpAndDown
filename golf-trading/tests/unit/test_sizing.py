"""
Unit tests for src/risk/sizing.py

Property invariants:
  - Stake is always ≥ 0
  - Stake never exceeds max_bet_fraction × total_bankroll
  - Stake is 0 when edge fails threshold
  - Stake is 0 when Kelly fraction is non-positive

Known-answer tests:
  - Core bet: edge=0.05, odds=-110, bankroll=$10000, 0.25x Kelly → expected stake
  - Convex bet: unit=0.5%, convex bankroll=$1000 → $5.00
"""

from __future__ import annotations

import math
import pytest

from src.pricing.fair_price import FairPriceResult, METHOD_HARVILLE
from src.risk.edge import EdgeResult
from src.risk.sizing import SizingResult, size_core_bet, size_convex_bet
from datetime import datetime, timezone

NOW = datetime(2024, 3, 11, tzinfo=timezone.utc)


def _edge(
    datagolf_id: str = "scheffler",
    market_type: str = "matchup_2ball",
    fair_prob: float = 0.55,
    book_no_vig_prob: float = 0.50,
    edge: float = 0.05,
    book_american_odds: int = -110,
    passes_threshold: bool = True,
    sleeve: str = "core",
) -> EdgeResult:
    return EdgeResult(
        datagolf_id=datagolf_id,
        opponent_id=None,
        market_type=market_type,
        book_id="dk",
        fair_prob=fair_prob,
        book_no_vig_prob=book_no_vig_prob,
        edge=edge,
        sleeve=sleeve,
        passes_threshold=passes_threshold,
        book_american_odds=book_american_odds,
    )


# ---------------------------------------------------------------------------
# Core bet (fractional Kelly)
# ---------------------------------------------------------------------------

def test_core_bet_known_answer() -> None:
    """
    edge=0.05, odds=-110 → decimal=1.909 → (odds-1)=0.909
    Kelly fraction = 0.05 / 0.909 ≈ 0.05500
    Stake = 0.25 × 0.05500 × $10000 ≈ $137.50
    """
    result = size_core_bet(
        edge=_edge(edge=0.05, book_american_odds=-110),
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=10.0,
        max_bet_fraction=0.02,
    )
    assert result.approved
    assert math.isclose(result.stake, 137.50, rel_tol=0.01)


def test_core_bet_capped_at_ceiling() -> None:
    """
    Large edge on small bankroll still can't exceed 2% ceiling.
    2% × $10000 = $200. If raw Kelly > $200, stake = $200.
    """
    result = size_core_bet(
        edge=_edge(edge=0.30, book_american_odds=200),  # big edge, +200 odds
        active_bankroll=10_000,
        total_bankroll=10_000,
        kelly_multiplier=0.25,
        min_bet_dollars=10.0,
        max_bet_fraction=0.02,
    )
    assert result.approved
    assert result.stake <= 0.02 * 10_000 + 0.01  # allow rounding


def test_core_bet_rejected_below_floor() -> None:
    """Tiny bankroll → computed stake below minimum → rejected."""
    result = size_core_bet(
        edge=_edge(edge=0.03, book_american_odds=-110),
        active_bankroll=100,      # very small
        total_bankroll=250,
        kelly_multiplier=0.25,
        min_bet_dollars=25.0,     # high floor
        max_bet_fraction=0.02,
    )
    assert not result.approved
    assert result.stake == 0.0


def test_core_bet_rejected_when_threshold_not_passed() -> None:
    result = size_core_bet(
        edge=_edge(passes_threshold=False),
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=10.0,
        max_bet_fraction=0.02,
    )
    assert not result.approved
    assert result.stake == 0.0


def test_core_bet_stake_always_nonnegative() -> None:
    """Property: stake is never negative."""
    for edge_val in [-0.10, 0.0, 0.01, 0.05, 0.20]:
        passes = edge_val >= 0.03
        result = size_core_bet(
            edge=_edge(edge=edge_val, passes_threshold=passes),
            active_bankroll=10_000,
            total_bankroll=25_000,
            kelly_multiplier=0.25,
            min_bet_dollars=10.0,
            max_bet_fraction=0.02,
        )
        assert result.stake >= 0.0


def test_core_bet_kelly_fraction_recorded() -> None:
    result = size_core_bet(
        edge=_edge(edge=0.05, book_american_odds=-110),
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=10.0,
        max_bet_fraction=0.02,
    )
    # Kelly fraction = 0.05 / (1.909-1) ≈ 0.055
    assert math.isclose(result.kelly_fraction, 0.055, rel_tol=0.02)


# ---------------------------------------------------------------------------
# Convex bet (fixed unit)
# ---------------------------------------------------------------------------

def test_convex_bet_known_answer() -> None:
    """0.5% × $1000 convex bankroll = $5.00."""
    result = size_convex_bet(
        edge=_edge(sleeve="convex", market_type="outright_win", passes_threshold=True),
        convex_bankroll=1_000,
        total_bankroll=10_000,
        unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    assert result.approved
    assert math.isclose(result.stake, 5.0, abs_tol=0.01)


def test_convex_bet_capped_at_ceiling() -> None:
    result = size_convex_bet(
        edge=_edge(sleeve="convex", passes_threshold=True),
        convex_bankroll=100_000,   # huge convex bankroll
        total_bankroll=200_000,
        unit_fraction=0.10,        # 10% unit would be $10k → above 2% ceiling
        min_bet_dollars=10.0,
        max_bet_fraction=0.02,
    )
    assert result.stake <= 0.02 * 200_000 + 0.01


def test_convex_bet_rejected_below_floor() -> None:
    result = size_convex_bet(
        edge=_edge(sleeve="convex", passes_threshold=True),
        convex_bankroll=100,
        total_bankroll=1_000,
        unit_fraction=0.005,  # $0.50 stake
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    assert not result.approved
    assert result.stake == 0.0


def test_convex_bet_rejected_when_threshold_not_passed() -> None:
    result = size_convex_bet(
        edge=_edge(passes_threshold=False, sleeve="convex"),
        convex_bankroll=1_000,
        total_bankroll=10_000,
        unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    assert not result.approved
