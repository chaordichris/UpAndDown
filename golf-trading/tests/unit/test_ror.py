from __future__ import annotations

import pytest

from src.risk.ror import estimate_risk_of_ruin


def test_no_variance_positive_return_has_no_drawdown_risk() -> None:
    estimate = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_000,
        bet_count=100,
        simulations=25,
        stake_fraction=0.01,
        expected_return_per_staked_dollar=0.03,
        return_sd_per_staked_dollar=0.0,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=7,
    )

    assert estimate.paper_only_probability == 0.0
    assert estimate.halt_probability == 0.0
    assert estimate.worst_drawdown_pct == 0.0
    assert estimate.median_terminal_bankroll > 10_000


def test_deterministic_loss_hits_drawdown_brakes() -> None:
    estimate = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_000,
        bet_count=5,
        simulations=10,
        stake_fraction=0.10,
        expected_return_per_staked_dollar=-1.0,
        return_sd_per_staked_dollar=0.0,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=7,
    )

    assert estimate.paper_only_hits == 10
    assert estimate.halt_hits == 10
    assert estimate.paper_only_probability == 1.0
    assert estimate.halt_probability == 1.0


def test_same_seed_is_reproducible() -> None:
    first = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_500,
        bet_count=100,
        simulations=250,
        stake_fraction=0.015,
        expected_return_per_staked_dollar=0.02,
        return_sd_per_staked_dollar=1.0,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=20260430,
    )
    second = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_500,
        bet_count=100,
        simulations=250,
        stake_fraction=0.015,
        expected_return_per_staked_dollar=0.02,
        return_sd_per_staked_dollar=1.0,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=20260430,
    )

    assert first == second


def test_higher_variance_increases_drawdown_risk() -> None:
    low_variance = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_000,
        bet_count=100,
        simulations=2_000,
        stake_fraction=0.02,
        expected_return_per_staked_dollar=0.01,
        return_sd_per_staked_dollar=0.40,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=11,
    )
    high_variance = estimate_risk_of_ruin(
        starting_bankroll=10_000,
        peak_bankroll=10_000,
        bet_count=100,
        simulations=2_000,
        stake_fraction=0.02,
        expected_return_per_staked_dollar=0.01,
        return_sd_per_staked_dollar=1.50,
        paper_only_threshold=0.25,
        halt_threshold=0.35,
        seed=11,
    )

    assert high_variance.paper_only_probability > low_variance.paper_only_probability
    assert high_variance.halt_probability >= low_variance.halt_probability


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"starting_bankroll": 0}, "starting_bankroll"),
        ({"peak_bankroll": 0}, "peak_bankroll"),
        ({"bet_count": 0}, "bet_count"),
        ({"simulations": 0}, "simulations"),
        ({"stake_fraction": 0}, "stake_fraction"),
        ({"return_sd_per_staked_dollar": -0.01}, "return_sd"),
        ({"paper_only_threshold": 0.40, "halt_threshold": 0.35}, "drawdown thresholds"),
    ],
)
def test_invalid_inputs_raise(kwargs: dict[str, float], message: str) -> None:
    params = {
        "starting_bankroll": 10_000,
        "peak_bankroll": 10_000,
        "bet_count": 100,
        "simulations": 100,
        "stake_fraction": 0.01,
        "expected_return_per_staked_dollar": 0.02,
        "return_sd_per_staked_dollar": 1.0,
        "paper_only_threshold": 0.25,
        "halt_threshold": 0.35,
        "seed": 7,
    }
    params.update(kwargs)

    with pytest.raises(ValueError, match=message):
        estimate_risk_of_ruin(**params)
