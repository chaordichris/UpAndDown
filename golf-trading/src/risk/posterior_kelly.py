"""Edge-uncertainty-aware Kelly sizing primitives.

This module does not change the current sizing path. It provides the Batch C
math contract that can be wired behind a config flag once edge_sd is propagated
through candidates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PosteriorKellyResult:
    """Audit payload for one posterior Kelly calculation."""

    standard_kelly_fraction: float
    fractional_kelly_fraction: float
    uncertainty_penalty: float
    certainty_equivalent_edge: float
    posterior_kelly_fraction: float
    approved: bool
    reason: str


def compute_posterior_kelly_fraction(
    *,
    edge_mean: float,
    edge_sd: float,
    decimal_odds: float,
    user_fraction: float,
) -> PosteriorKellyResult:
    """Return a Kelly fraction after penalizing noisy edge estimates.

    The baseline full Kelly fraction is ``edge_mean / (decimal_odds - 1)``.
    The posterior path applies the configured user fraction first, then subtracts
    a Normal-posterior uncertainty penalty from the fractional edge:

      posterior = (edge_mean * user_fraction - edge_sd^2) / (decimal_odds - 1)

    This preserves the existing quarter-Kelly behavior when ``edge_sd == 0`` and
    shrinks toward no-bet as edge uncertainty grows.
    """
    _validate_inputs(
        edge_mean=edge_mean,
        edge_sd=edge_sd,
        decimal_odds=decimal_odds,
        user_fraction=user_fraction,
    )

    odds_profit = decimal_odds - 1.0
    standard_kelly = edge_mean / odds_profit
    fractional_kelly = standard_kelly * user_fraction
    uncertainty_penalty = edge_sd * edge_sd
    certainty_equivalent_edge = edge_mean * user_fraction - uncertainty_penalty

    if certainty_equivalent_edge <= 0:
        return PosteriorKellyResult(
            standard_kelly_fraction=standard_kelly,
            fractional_kelly_fraction=fractional_kelly,
            uncertainty_penalty=uncertainty_penalty,
            certainty_equivalent_edge=certainty_equivalent_edge,
            posterior_kelly_fraction=0.0,
            approved=False,
            reason="Edge uncertainty exceeds fractional edge.",
        )

    posterior_kelly = certainty_equivalent_edge / odds_profit
    return PosteriorKellyResult(
        standard_kelly_fraction=standard_kelly,
        fractional_kelly_fraction=fractional_kelly,
        uncertainty_penalty=uncertainty_penalty,
        certainty_equivalent_edge=certainty_equivalent_edge,
        posterior_kelly_fraction=posterior_kelly,
        approved=True,
        reason="Posterior Kelly approved.",
    )


def _validate_inputs(
    *,
    edge_mean: float,
    edge_sd: float,
    decimal_odds: float,
    user_fraction: float,
) -> None:
    if edge_mean <= 0:
        raise ValueError("edge_mean must be positive.")
    if edge_sd < 0:
        raise ValueError("edge_sd must be non-negative.")
    if decimal_odds <= 1.0:
        raise ValueError("decimal_odds must be greater than 1.0.")
    if not 0 < user_fraction <= 1:
        raise ValueError("user_fraction must be in (0, 1].")
