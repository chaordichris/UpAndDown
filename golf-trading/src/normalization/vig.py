"""
Vig (overround) removal.

Two methods are supported:

  multiplicative — each implied probability is divided by the overround total.
    Simple, symmetric, preserves relative probability ratios exactly.
    q_i = p_i / sum(p_j)

  power — find exponent k > 1 such that sum(p_i ^ k) = 1.0.
    Slightly more favourable to underdogs than multiplicative because
    larger probabilities shrink faster under exponentiation.
    Falls back to multiplicative if the solver doesn't converge.

Both methods guarantee output probabilities that sum to 1.0 within tolerance,
and every output probability is in (0, 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


_SUM_TOLERANCE = 1e-9   # acceptable deviation from 1.0 in output
_POWER_MAX_ITER = 200   # binary search iterations for power method
_POWER_CONVERGENCE = 1e-10  # target precision for power method


@dataclass(frozen=True)
class VigRemovalResult:
    """Result of a vig removal computation."""

    no_vig_probs: tuple[float, ...]   # probabilities summing to ~1.0
    hold_pct: float                   # book's overround as a percentage, e.g. 4.8
    method: str                       # "multiplicative" or "power"
    raw_probs: tuple[float, ...]      # original input (for audit)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def remove_vig(
    probs: list[float],
    method: str = "multiplicative",
) -> VigRemovalResult:
    """Remove vig from a list of implied probabilities.

    Args:
        probs: Implied probabilities from the book (should sum to > 1.0).
        method: "multiplicative" or "power".

    Returns:
        VigRemovalResult with no-vig probabilities, hold percentage, and metadata.

    Raises:
        ValueError: If probs is empty, contains non-positive values, or method is unknown.
    """
    _validate_probs(probs)
    if method == "multiplicative":
        return remove_vig_multiplicative(probs)
    elif method == "power":
        return remove_vig_power(probs)
    else:
        raise ValueError(f"Unknown vig removal method: {method!r}. Use 'multiplicative' or 'power'.")


def remove_vig_multiplicative(probs: list[float]) -> VigRemovalResult:
    """Proportional vig removal: divide each probability by the overround total.

    The simplest and most common method. Preserves relative probability ratios.
    """
    _validate_probs(probs)
    total = sum(probs)
    hold_pct = (total - 1.0) * 100.0
    no_vig = tuple(p / total for p in probs)
    return VigRemovalResult(
        no_vig_probs=no_vig,
        hold_pct=hold_pct,
        method="multiplicative",
        raw_probs=tuple(probs),
    )


def remove_vig_power(
    probs: list[float],
    max_iterations: int = _POWER_MAX_ITER,
) -> VigRemovalResult:
    """Power method: find exponent k > 1 such that sum(p_i ^ k) = 1.0.

    For each probability p_i, the no-vig probability q_i = p_i ^ k.

    Falls back to multiplicative if the binary search doesn't converge
    (e.g., near-zero hold, extreme vig, or single-outcome market).
    """
    _validate_probs(probs)
    total = sum(probs)
    hold_pct = (total - 1.0) * 100.0

    # If hold is negligible, skip solver and use multiplicative
    if abs(total - 1.0) < 1e-8:
        no_vig = tuple(probs)
        return VigRemovalResult(
            no_vig_probs=no_vig,
            hold_pct=hold_pct,
            method="power",
            raw_probs=tuple(probs),
        )

    # Binary search for k such that f(k) = sum(p_i^k) - 1.0 = 0
    # f(1) = total > 1 → f(1) > 0
    # f(large) → 0 (max prob dominates) → f(large) < 0 for large enough k
    k_lo, k_hi = 1.0, 1.0
    # Find an upper bound where sum < 1
    max_prob = max(probs)
    k_hi = 1.0
    for _ in range(64):
        k_hi *= 2.0
        if _sum_power(probs, k_hi) < 1.0:
            break
    else:
        # Could not bracket — fall back to multiplicative
        return remove_vig_multiplicative(probs)

    # Binary search
    k = 1.0
    for _ in range(max_iterations):
        k = (k_lo + k_hi) / 2.0
        s = _sum_power(probs, k)
        if abs(s - 1.0) < _POWER_CONVERGENCE:
            break
        if s > 1.0:
            k_lo = k
        else:
            k_hi = k
    else:
        # Did not converge — fall back to multiplicative
        return remove_vig_multiplicative(probs)

    no_vig = tuple(p ** k for p in probs)

    # Sanity-check the result; fall back if something went wrong
    if abs(sum(no_vig) - 1.0) > 1e-6 or any(q <= 0 or q >= 1 for q in no_vig):
        return remove_vig_multiplicative(probs)

    return VigRemovalResult(
        no_vig_probs=no_vig,
        hold_pct=hold_pct,
        method="power",
        raw_probs=tuple(probs),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sum_power(probs: list[float], k: float) -> float:
    return sum(p ** k for p in probs)


def _validate_probs(probs: list[float]) -> None:
    if not probs:
        raise ValueError("probs must not be empty.")
    if any(p <= 0.0 for p in probs):
        raise ValueError(f"All probabilities must be positive, got {probs}.")
    if any(p >= 1.0 for p in probs):
        raise ValueError(
            f"Individual probabilities must be < 1.0 (each outcome can't be certain), got {probs}."
        )
