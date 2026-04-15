"""
Unit tests for src/normalization/vig.py

Property invariants tested:
  - Output probs always sum to 1.0 (within tolerance)
  - Every output prob is in (0, 1)
  - Each output prob <= corresponding input prob (vig can only shrink probs)

Known-answer tests:
  - 2-way symmetric market (equal vig distribution)
  - 2-way asymmetric market (favourite / underdog)
  - 3-way market (e.g. 3-ball)
  - Large outright field (150 players)

Edge cases:
  - Near-zero hold (1%)
  - Extreme hold (15%+)
  - Two-outcome market
  - Large field (150 outcomes)
"""

from __future__ import annotations

import math
import pytest

from src.normalization.vig import (
    remove_vig,
    remove_vig_multiplicative,
    remove_vig_power,
    VigRemovalResult,
)

SUM_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def assert_valid_result(result: VigRemovalResult, n: int) -> None:
    """Common assertions for any vig removal result."""
    assert len(result.no_vig_probs) == n, "Output length must match input."
    assert math.isclose(sum(result.no_vig_probs), 1.0, abs_tol=SUM_TOLERANCE), (
        f"Output probs sum to {sum(result.no_vig_probs)}, not 1.0"
    )
    for q in result.no_vig_probs:
        assert 0 < q < 1, f"Output prob {q} is out of (0, 1)"
    assert result.hold_pct >= 0, "Hold percentage must be non-negative."


# ---------------------------------------------------------------------------
# Known-answer: multiplicative method
# ---------------------------------------------------------------------------

def test_multiplicative_symmetric_two_way() -> None:
    """Equal two-way market with 10% hold: each output prob should be 0.50."""
    # Both sides at -110: implied = 100/210 ≈ 0.5238 each → sum ≈ 1.0476
    p = 0.5238
    probs = [p, p]
    result = remove_vig_multiplicative(probs)
    assert_valid_result(result, 2)
    assert math.isclose(result.no_vig_probs[0], result.no_vig_probs[1], rel_tol=1e-5)
    assert math.isclose(sum(probs) - 1.0, result.hold_pct / 100.0, rel_tol=1e-5)


def test_multiplicative_asymmetric_two_way() -> None:
    """Favourite/underdog market. Multiplicative preserves ratio."""
    # -145 favourite: implied ≈ 0.5918; +120 underdog: implied = 100/220 ≈ 0.4545
    probs = [0.5918, 0.4545]
    result = remove_vig_multiplicative(probs)
    assert_valid_result(result, 2)
    # Ratio of output probs must equal ratio of input probs
    ratio_in = probs[0] / probs[1]
    ratio_out = result.no_vig_probs[0] / result.no_vig_probs[1]
    assert math.isclose(ratio_in, ratio_out, rel_tol=1e-5)


def test_multiplicative_three_way() -> None:
    """3-ball market (3 outcomes, typical ~5% hold)."""
    probs = [0.37, 0.35, 0.33]  # sum = 1.05
    result = remove_vig_multiplicative(probs)
    assert_valid_result(result, 3)
    assert math.isclose(result.hold_pct, 5.0, rel_tol=1e-3)


def test_multiplicative_large_field() -> None:
    """150-player outright field; multiplicative should still produce valid output."""
    # Spread probability uniformly + small uniform overround
    base_prob = 1.0 / 150
    hold = 0.12  # 12% hold is realistic for outrights
    probs = [base_prob * (1 + hold)] * 150
    result = remove_vig_multiplicative(probs)
    assert_valid_result(result, 150)
    assert math.isclose(result.hold_pct, hold * 100, rel_tol=1e-3)


def test_multiplicative_each_output_leq_input() -> None:
    """Every no-vig probability must be <= the corresponding input probability."""
    probs = [0.55, 0.52]  # sum = 1.07
    result = remove_vig_multiplicative(probs)
    for raw, no_vig in zip(result.raw_probs, result.no_vig_probs):
        assert no_vig <= raw + 1e-10, f"No-vig prob {no_vig} > raw prob {raw}"


# ---------------------------------------------------------------------------
# Known-answer: power method
# ---------------------------------------------------------------------------

def test_power_symmetric_two_way() -> None:
    """Power method on symmetric market: both probs should converge to 0.50."""
    probs = [0.5238, 0.5238]
    result = remove_vig_power(probs)
    assert_valid_result(result, 2)
    assert math.isclose(result.no_vig_probs[0], 0.5, abs_tol=1e-3)
    assert math.isclose(result.no_vig_probs[1], 0.5, abs_tol=1e-3)


def test_power_asymmetric_two_way() -> None:
    """Power method on asymmetric market: underdog gets slightly more than multiplicative."""
    probs = [0.70, 0.36]  # sum = 1.06
    mult = remove_vig_multiplicative(probs)
    power = remove_vig_power(probs)
    assert_valid_result(power, 2)
    # Underdog (lower prob) should get a slightly higher no-vig prob with power method
    # compared to multiplicative — power method favours underdogs
    assert power.no_vig_probs[1] >= mult.no_vig_probs[1] - 1e-6


def test_power_large_field() -> None:
    """Power method on large outright field must converge and sum to 1.0."""
    n = 150
    base = 1.0 / n
    probs = [base * 1.10] * n  # uniform 10% hold
    result = remove_vig_power(probs)
    assert_valid_result(result, n)


def test_power_method_string() -> None:
    """remove_vig(method='power') routes to power method."""
    probs = [0.55, 0.52]
    result = remove_vig(probs, method="power")
    assert result.method == "power"
    assert_valid_result(result, 2)


# ---------------------------------------------------------------------------
# remove_vig dispatcher
# ---------------------------------------------------------------------------

def test_dispatcher_multiplicative() -> None:
    probs = [0.55, 0.52]
    result = remove_vig(probs, method="multiplicative")
    assert result.method == "multiplicative"
    assert_valid_result(result, 2)


def test_dispatcher_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="Unknown vig removal method"):
        remove_vig([0.55, 0.52], method="shin")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_near_zero_hold() -> None:
    """Market with 1% hold should still produce valid output."""
    probs = [0.505, 0.505]  # sum = 1.01
    for method in ("multiplicative", "power"):
        result = remove_vig(probs, method=method)
        assert_valid_result(result, 2)
        assert math.isclose(result.hold_pct, 1.0, rel_tol=1e-3)


def test_extreme_hold() -> None:
    """Market with 15% hold should still produce valid output."""
    probs = [0.60, 0.55]  # sum = 1.15
    for method in ("multiplicative", "power"):
        result = remove_vig(probs, method=method)
        assert_valid_result(result, 2)
        assert math.isclose(result.hold_pct, 15.0, rel_tol=1e-3)


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------

def test_empty_probs_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        remove_vig([])


def test_zero_prob_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        remove_vig([0.0, 0.5])


def test_negative_prob_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        remove_vig([-0.1, 1.05])


def test_prob_gte_one_raises() -> None:
    with pytest.raises(ValueError, match="< 1.0"):
        remove_vig([1.0, 0.1])
