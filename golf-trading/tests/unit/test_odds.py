"""
Unit tests for src/normalization/odds.py

Tests cover:
  - Table-driven conversions: American → decimal → implied and back
  - Round-trip property: normalize_american(implied_to_american(p)).implied_prob ≈ p
  - Edge cases: even odds, heavy favorites, heavy underdogs
  - Invalid inputs raise ValueError
"""

from __future__ import annotations

import math
import pytest

from src.normalization.odds import (
    american_to_decimal,
    decimal_to_implied,
    decimal_to_american,
    implied_to_decimal,
    implied_to_american,
    normalize_american,
    normalize_decimal,
    normalize_implied,
    NormalizedOdds,
)

TOLERANCE = 1e-6  # floating-point comparison tolerance


# ---------------------------------------------------------------------------
# Table-driven: American → decimal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("american, expected_decimal", [
    # Standard favorites
    (-110, 1.909090909),
    (-120, 1.833333333),
    (-145, 1.689655172),
    (-200, 1.5),
    (-300, 1.333333333),
    (-500, 1.2),
    (-1000, 1.1),
    (-10000, 1.01),
    # Even money
    (+100, 2.0),
    # Underdogs
    (+110, 2.1),
    (+120, 2.2),
    (+150, 2.5),
    (+200, 3.0),
    (+300, 4.0),
    (+500, 6.0),
    (+1000, 11.0),
    (+5000, 51.0),
    (+50000, 501.0),
])
def test_american_to_decimal(american: float, expected_decimal: float) -> None:
    result = american_to_decimal(american)
    assert math.isclose(result, expected_decimal, rel_tol=TOLERANCE), (
        f"american_to_decimal({american}) = {result}, expected {expected_decimal}"
    )


# ---------------------------------------------------------------------------
# Table-driven: decimal → implied probability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decimal, expected_prob", [
    (2.0, 0.5),
    (1.5, 0.666666667),
    (1.909090909, 0.523809524),  # -110
    (4.0, 0.25),
    (11.0, 0.090909091),
    (1.01, 0.99009901),
    (501.0, 0.001996008),
])
def test_decimal_to_implied(decimal: float, expected_prob: float) -> None:
    result = decimal_to_implied(decimal)
    assert math.isclose(result, expected_prob, rel_tol=TOLERANCE)


# ---------------------------------------------------------------------------
# Table-driven: implied probability → American odds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prob, expected_american", [
    (0.5, -100.0),    # even money, can express as +100 or -100; we use -100 at threshold
    (0.5238, -110.0),  # standard -110 line (≈0.5238)
    (0.6667, -200.0),  # -200 line
    (0.25, 300.0),     # +300 underdog
    (0.1, 900.0),      # +900
    (0.333333, 200.0), # +200
])
def test_implied_to_american(prob: float, expected_american: float) -> None:
    result = implied_to_american(prob)
    # Use rel_tol because magnitudes vary greatly
    assert math.isclose(result, expected_american, rel_tol=1e-3), (
        f"implied_to_american({prob}) = {result:.2f}, expected {expected_american}"
    )


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("american", [-110, -145, -200, -500, +100, +120, +200, +500, +1000])
def test_american_round_trip(american: float) -> None:
    """American → decimal → implied → american should recover the original odds."""
    decimal = american_to_decimal(american)
    prob = decimal_to_implied(decimal)
    american_back = implied_to_american(prob)
    decimal_back = implied_to_decimal(prob)
    # Odds must match within 0.1% (floating-point noise only)
    assert math.isclose(decimal, decimal_back, rel_tol=1e-5)
    assert math.isclose(american, american_back, rel_tol=1e-3), (
        f"Round-trip failed for {american}: got {american_back:.2f}"
    )


@pytest.mark.parametrize("prob", [0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 0.99])
def test_implied_round_trip(prob: float) -> None:
    """implied → american → decimal → implied should recover the original prob."""
    american = implied_to_american(prob)
    decimal = american_to_decimal(american)
    prob_back = decimal_to_implied(decimal)
    assert math.isclose(prob, prob_back, rel_tol=1e-5)


# ---------------------------------------------------------------------------
# normalize_* helpers
# ---------------------------------------------------------------------------

def test_normalize_american_structure() -> None:
    odds = normalize_american(-110)
    assert isinstance(odds, NormalizedOdds)
    assert math.isclose(odds.decimal, 1.909090909, rel_tol=TOLERANCE)
    assert math.isclose(odds.implied_prob, 0.523809524, rel_tol=TOLERANCE)
    assert odds.american == -110


def test_normalize_decimal_structure() -> None:
    odds = normalize_decimal(2.0)
    assert math.isclose(odds.implied_prob, 0.5, rel_tol=TOLERANCE)
    assert odds.decimal == 2.0


def test_normalize_implied_structure() -> None:
    odds = normalize_implied(0.5)
    assert math.isclose(odds.decimal, 2.0, rel_tol=TOLERANCE)
    assert math.isclose(odds.implied_prob, 0.5, rel_tol=TOLERANCE)


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------

def test_american_zero_raises() -> None:
    with pytest.raises(ValueError, match="0 are undefined"):
        american_to_decimal(0)


def test_american_between_minus100_and_zero_raises() -> None:
    with pytest.raises(ValueError):
        american_to_decimal(-50)


def test_decimal_below_one_raises() -> None:
    with pytest.raises(ValueError, match=">= 1.0"):
        decimal_to_implied(0.5)


def test_decimal_zero_raises() -> None:
    with pytest.raises(ValueError):
        decimal_to_implied(0)


def test_implied_zero_raises() -> None:
    with pytest.raises(ValueError):
        implied_to_decimal(0.0)


def test_implied_above_one_raises() -> None:
    with pytest.raises(ValueError):
        implied_to_decimal(1.1)


def test_implied_to_american_one_raises() -> None:
    with pytest.raises(ValueError):
        implied_to_american(1.0)


def test_implied_to_american_zero_raises() -> None:
    with pytest.raises(ValueError):
        implied_to_american(0.0)
