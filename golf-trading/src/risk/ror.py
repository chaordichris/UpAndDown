"""Risk-of-ruin estimation for phase-gate reviews."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskOfRuinEstimate:
    """Monte Carlo drawdown risk over a fixed future bet horizon."""

    simulations: int
    bet_count: int
    paper_only_hits: int
    halt_hits: int
    paper_only_probability: float
    halt_probability: float
    worst_drawdown_pct: float
    median_terminal_bankroll: float


def estimate_risk_of_ruin(
    *,
    starting_bankroll: float,
    peak_bankroll: float,
    bet_count: int,
    simulations: int,
    stake_fraction: float,
    expected_return_per_staked_dollar: float,
    return_sd_per_staked_dollar: float,
    paper_only_threshold: float,
    halt_threshold: float,
    seed: int | None = None,
) -> RiskOfRuinEstimate:
    """Estimate drawdown-brake hit rates over a future bet sequence.

    Returns are sampled as per-staked-dollar P&L, then scaled by
    ``current_bankroll * stake_fraction``. Drawdown is measured against a rolling
    peak bankroll, matching the drawdown brake's survival-first framing.
    """
    _validate_inputs(
        starting_bankroll=starting_bankroll,
        peak_bankroll=peak_bankroll,
        bet_count=bet_count,
        simulations=simulations,
        stake_fraction=stake_fraction,
        return_sd_per_staked_dollar=return_sd_per_staked_dollar,
        paper_only_threshold=paper_only_threshold,
        halt_threshold=halt_threshold,
    )

    rng = random.Random(seed)
    paper_only_hits = 0
    halt_hits = 0
    worst_drawdown = 0.0
    terminal_bankrolls: list[float] = []

    for _ in range(simulations):
        bankroll = starting_bankroll
        rolling_peak = max(peak_bankroll, starting_bankroll)
        hit_paper_only = False
        hit_halt = False

        for _ in range(bet_count):
            sampled_return = _sample_return(
                rng=rng,
                expected_return=expected_return_per_staked_dollar,
                return_sd=return_sd_per_staked_dollar,
            )
            bankroll += bankroll * stake_fraction * sampled_return
            if bankroll <= 0:
                bankroll = 0.0
                hit_paper_only = True
                hit_halt = True
                worst_drawdown = 1.0
                break

            rolling_peak = max(rolling_peak, bankroll)
            drawdown = (rolling_peak - bankroll) / rolling_peak
            worst_drawdown = max(worst_drawdown, drawdown)
            if drawdown >= paper_only_threshold:
                hit_paper_only = True
            if drawdown >= halt_threshold:
                hit_halt = True
                break

        paper_only_hits += int(hit_paper_only)
        halt_hits += int(hit_halt)
        terminal_bankrolls.append(bankroll)

    terminal_bankrolls.sort()
    median_terminal = _median(terminal_bankrolls)
    return RiskOfRuinEstimate(
        simulations=simulations,
        bet_count=bet_count,
        paper_only_hits=paper_only_hits,
        halt_hits=halt_hits,
        paper_only_probability=paper_only_hits / simulations,
        halt_probability=halt_hits / simulations,
        worst_drawdown_pct=worst_drawdown * 100.0,
        median_terminal_bankroll=median_terminal,
    )


def _sample_return(
    *,
    rng: random.Random,
    expected_return: float,
    return_sd: float,
) -> float:
    if return_sd == 0:
        return expected_return
    return rng.gauss(expected_return, return_sd)


def _median(values: list[float]) -> float:
    midpoint = len(values) // 2
    if len(values) % 2 == 1:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def _validate_inputs(
    *,
    starting_bankroll: float,
    peak_bankroll: float,
    bet_count: int,
    simulations: int,
    stake_fraction: float,
    return_sd_per_staked_dollar: float,
    paper_only_threshold: float,
    halt_threshold: float,
) -> None:
    if starting_bankroll <= 0:
        raise ValueError("starting_bankroll must be positive.")
    if peak_bankroll <= 0:
        raise ValueError("peak_bankroll must be positive.")
    if bet_count <= 0:
        raise ValueError("bet_count must be positive.")
    if simulations <= 0:
        raise ValueError("simulations must be positive.")
    if not 0 < stake_fraction <= 1:
        raise ValueError("stake_fraction must be in (0, 1].")
    if return_sd_per_staked_dollar < 0:
        raise ValueError("return_sd_per_staked_dollar must be non-negative.")
    if not 0 < paper_only_threshold <= halt_threshold <= 1:
        raise ValueError("drawdown thresholds must satisfy 0 < paper_only <= halt <= 1.")
