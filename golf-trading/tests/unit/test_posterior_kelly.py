from __future__ import annotations

import math

import pytest

from src.normalization.odds import american_to_decimal
from src.risk.posterior_kelly import compute_posterior_kelly_fraction


def test_zero_uncertainty_matches_fractional_kelly() -> None:
    decimal_odds = american_to_decimal(-110)
    result = compute_posterior_kelly_fraction(
        edge_mean=0.05,
        edge_sd=0.0,
        decimal_odds=decimal_odds,
        user_fraction=0.25,
    )

    expected = (0.05 / (decimal_odds - 1.0)) * 0.25
    assert result.approved
    assert math.isclose(result.posterior_kelly_fraction, expected, rel_tol=1e-12)
    assert math.isclose(result.fractional_kelly_fraction, expected, rel_tol=1e-12)


def test_uncertainty_reduces_kelly_fraction() -> None:
    decimal_odds = american_to_decimal(-110)
    low_uncertainty = compute_posterior_kelly_fraction(
        edge_mean=0.04,
        edge_sd=0.005,
        decimal_odds=decimal_odds,
        user_fraction=0.25,
    )
    high_uncertainty = compute_posterior_kelly_fraction(
        edge_mean=0.04,
        edge_sd=0.02,
        decimal_odds=decimal_odds,
        user_fraction=0.25,
    )

    assert high_uncertainty.approved
    assert high_uncertainty.posterior_kelly_fraction < low_uncertainty.posterior_kelly_fraction
    assert high_uncertainty.certainty_equivalent_edge == pytest.approx(0.0096)


def test_monotonic_non_increasing_as_uncertainty_rises() -> None:
    decimal_odds = american_to_decimal(120)
    fractions = [
        compute_posterior_kelly_fraction(
            edge_mean=0.06,
            edge_sd=edge_sd,
            decimal_odds=decimal_odds,
            user_fraction=0.25,
        ).posterior_kelly_fraction
        for edge_sd in [0.0, 0.01, 0.02, 0.03, 0.04]
    ]

    assert fractions == sorted(fractions, reverse=True)


def test_rejects_when_uncertainty_exceeds_fractional_edge() -> None:
    result = compute_posterior_kelly_fraction(
        edge_mean=0.03,
        edge_sd=0.10,
        decimal_odds=2.0,
        user_fraction=0.25,
    )

    assert not result.approved
    assert result.posterior_kelly_fraction == 0.0
    assert result.certainty_equivalent_edge < 0


@pytest.mark.parametrize(
    ("edge_mean", "edge_sd", "decimal_odds", "user_fraction", "message"),
    [
        (0.0, 0.01, 2.0, 0.25, "edge_mean"),
        (0.05, -0.01, 2.0, 0.25, "edge_sd"),
        (0.05, 0.01, 1.0, 0.25, "decimal_odds"),
        (0.05, 0.01, 2.0, 0.0, "user_fraction"),
    ],
)
def test_invalid_inputs_raise(
    edge_mean: float,
    edge_sd: float,
    decimal_odds: float,
    user_fraction: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        compute_posterior_kelly_fraction(
            edge_mean=edge_mean,
            edge_sd=edge_sd,
            decimal_odds=decimal_odds,
            user_fraction=user_fraction,
        )
