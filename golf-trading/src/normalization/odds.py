"""
Odds normalization: convert between American, decimal, and implied probability formats.

All functions are pure (no I/O, no side effects). Inputs are validated;
invalid values raise ValueError with a descriptive message.

American odds convention:
  Positive (+120): profit on a $100 stake. Decimal = 1 + american/100.
  Negative (-145): stake required to profit $100. Decimal = 1 + 100/abs(american).

Implied probability:
  prob = 1 / decimal
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedOdds:
    """A single set of odds expressed in all three formats."""

    american: float   # raw American odds (may be non-integer after conversion)
    decimal: float    # decimal odds >= 1.0
    implied_prob: float  # implied probability in (0, 1]


# ---------------------------------------------------------------------------
# Primitive converters
# ---------------------------------------------------------------------------

def american_to_decimal(american: float) -> float:
    """Convert American odds to decimal odds.

    Args:
        american: American odds (e.g., +120 or -145). Must not be 0 or in (-100, 0).

    Returns:
        Decimal odds >= 1.0.

    Raises:
        ValueError: If american == 0 or is between -100 and 0 exclusive (undefined).
    """
    if american == 0:
        raise ValueError("American odds of 0 are undefined.")
    if -100 < american < 0:
        raise ValueError(
            f"American odds between -100 and 0 (exclusive) are undefined, got {american}."
        )
    if american > 0:
        return 1.0 + american / 100.0
    else:  # american <= -100
        return 1.0 + 100.0 / abs(american)


def decimal_to_implied(decimal: float) -> float:
    """Convert decimal odds to implied probability.

    Args:
        decimal: Decimal odds. Must be > 1.0 (strictly; 1.0 would imply certainty).

    Returns:
        Implied probability in (0, 1).

    Raises:
        ValueError: If decimal <= 0.
    """
    if decimal <= 0:
        raise ValueError(f"Decimal odds must be positive, got {decimal}.")
    if decimal < 1.0:
        raise ValueError(
            f"Decimal odds must be >= 1.0 (cannot imply probability > 1), got {decimal}."
        )
    return 1.0 / decimal


def implied_to_decimal(prob: float) -> float:
    """Convert implied probability to decimal odds.

    Args:
        prob: Implied probability in (0, 1].

    Returns:
        Decimal odds >= 1.0.

    Raises:
        ValueError: If prob is not in (0, 1].
    """
    if prob <= 0.0 or prob > 1.0:
        raise ValueError(
            f"Implied probability must be in (0, 1], got {prob}."
        )
    return 1.0 / prob


def implied_to_american(prob: float) -> float:
    """Convert implied probability to American odds.

    By convention:
      prob >= 0.5 (favorite) → negative American odds
      prob <  0.5 (underdog) → positive American odds

    Args:
        prob: Implied probability in (0, 1).

    Returns:
        American odds (float; callers may round to int if desired).

    Raises:
        ValueError: If prob is not in (0, 1).
    """
    if prob <= 0.0 or prob >= 1.0:
        raise ValueError(
            f"Implied probability must be strictly in (0, 1), got {prob}."
        )
    if prob >= 0.5:
        return -100.0 * prob / (1.0 - prob)
    else:
        return 100.0 * (1.0 - prob) / prob


def decimal_to_american(decimal: float) -> float:
    """Convert decimal odds to American odds (inverse of american_to_decimal)."""
    prob = decimal_to_implied(decimal)
    return implied_to_american(prob)


# ---------------------------------------------------------------------------
# Convenience normalizers — call these from application code
# ---------------------------------------------------------------------------

def normalize_american(american: float) -> NormalizedOdds:
    """Produce a NormalizedOdds from American odds."""
    decimal = american_to_decimal(american)
    prob = decimal_to_implied(decimal)
    return NormalizedOdds(american=american, decimal=decimal, implied_prob=prob)


def normalize_decimal(decimal: float) -> NormalizedOdds:
    """Produce a NormalizedOdds from decimal odds."""
    prob = decimal_to_implied(decimal)
    american = implied_to_american(prob)
    return NormalizedOdds(american=american, decimal=decimal, implied_prob=prob)


def normalize_implied(prob: float) -> NormalizedOdds:
    """Produce a NormalizedOdds from an implied probability."""
    decimal = implied_to_decimal(prob)
    american = implied_to_american(prob)
    return NormalizedOdds(american=american, decimal=decimal, implied_prob=prob)
