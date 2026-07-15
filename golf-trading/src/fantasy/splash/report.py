"""Splash fantasy portfolio report generation."""

from __future__ import annotations

import math
from typing import Any

from src.fantasy.splash.models import (
    SplashFantasyReport,
    SplashFantasyReportConfig,
    SplashLineupPortfolio,
    SplashManualLineup,
)
from src.risk.ror import estimate_risk_of_ruin
from src.storage.hashing import stable_hash

REPORT_VERSION = "splash-fantasy-report-v1"


def fantasy_report_config(
    *,
    bankroll_cents: int,
    half_kelly_fraction: float,
    minimum_portfolio_ev_cents: float = 0.0,
    minimum_ev_to_sd_ratio: float = 0.05,
    max_ror_probability: float = 0.05,
    ror_simulations: int = 2_000,
    ror_seed: int = 20260701,
    paper_only_drawdown_threshold: float = 0.25,
    halt_drawdown_threshold: float = 0.35,
) -> SplashFantasyReportConfig:
    config = SplashFantasyReportConfig(
        bankroll_cents=bankroll_cents,
        half_kelly_fraction=half_kelly_fraction,
        minimum_portfolio_ev_cents=minimum_portfolio_ev_cents,
        minimum_ev_to_sd_ratio=minimum_ev_to_sd_ratio,
        max_ror_probability=max_ror_probability,
        ror_simulations=ror_simulations,
        ror_seed=ror_seed,
        paper_only_drawdown_threshold=paper_only_drawdown_threshold,
        halt_drawdown_threshold=halt_drawdown_threshold,
        inputs_hash="",
    )
    _validate_report_config(config)
    return SplashFantasyReportConfig(
        bankroll_cents=config.bankroll_cents,
        half_kelly_fraction=config.half_kelly_fraction,
        minimum_portfolio_ev_cents=config.minimum_portfolio_ev_cents,
        minimum_ev_to_sd_ratio=config.minimum_ev_to_sd_ratio,
        max_ror_probability=config.max_ror_probability,
        ror_simulations=config.ror_simulations,
        ror_seed=config.ror_seed,
        paper_only_drawdown_threshold=config.paper_only_drawdown_threshold,
        halt_drawdown_threshold=config.halt_drawdown_threshold,
        inputs_hash=stable_hash(
            {
                "bankroll_cents": config.bankroll_cents,
                "half_kelly_fraction": config.half_kelly_fraction,
                "minimum_portfolio_ev_cents": config.minimum_portfolio_ev_cents,
                "minimum_ev_to_sd_ratio": config.minimum_ev_to_sd_ratio,
                "max_ror_probability": config.max_ror_probability,
                "ror_simulations": config.ror_simulations,
                "ror_seed": config.ror_seed,
                "paper_only_drawdown_threshold": config.paper_only_drawdown_threshold,
                "halt_drawdown_threshold": config.halt_drawdown_threshold,
            }
        ),
    )


def build_splash_fantasy_report(
    *,
    portfolio: SplashLineupPortfolio,
    player_names: dict[str, str],
    config: SplashFantasyReportConfig,
) -> SplashFantasyReport:
    """Build a manual-entry report from an optimized Splash portfolio."""
    _validate_report_config(config)
    portfolio_variance = sum(
        entry.candidate.simulation_result.profit_variance_cents
        for entry in portfolio.entries
    )
    portfolio_sd = math.sqrt(portfolio_variance) if portfolio_variance > 0 else 0.0
    ev_to_sd_ratio = (
        portfolio.expected_profit_cents / portfolio_sd
        if portfolio_sd > 0
        else None
    )
    ror_estimate = _ror_estimate(
        portfolio=portfolio,
        portfolio_variance_cents=portfolio_variance,
        config=config,
    )
    no_play_reasons = _no_play_reasons(
        portfolio=portfolio,
        config=config,
        ev_to_sd_ratio=ev_to_sd_ratio,
        ror_estimate=ror_estimate,
    )
    recommendation = "no play" if no_play_reasons else "play"
    manual_lineups = tuple(
        _manual_lineup(entry, player_names)
        for entry in portfolio.entries
    )
    marginal_ev_by_lineup = tuple(
        (entry.lineup.lineup_id, entry.marginal_adjusted_ev_cents)
        for entry in portfolio.entries
    )
    assumption_log: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "bankroll_cents": config.bankroll_cents,
        "half_kelly_fraction_used": config.half_kelly_fraction,
        "minimum_portfolio_ev_cents": config.minimum_portfolio_ev_cents,
        "minimum_ev_to_sd_ratio": config.minimum_ev_to_sd_ratio,
        "max_ror_probability": config.max_ror_probability,
        "portfolio_variance_method": "sum_lineup_profit_variances_no_covariance",
        "ror_method": ror_estimate["method"],
    }
    report_hash = stable_hash(
        {
            "report_version": REPORT_VERSION,
            "portfolio": portfolio,
            "player_names": player_names,
            "config": config,
            "portfolio_variance": portfolio_variance,
            "ror_estimate": ror_estimate,
            "no_play_reasons": no_play_reasons,
        }
    )
    return SplashFantasyReport(
        portfolio_name=portfolio.portfolio_name,
        recommendation=recommendation,
        no_play_reasons=tuple(no_play_reasons),
        recommended_entries=0 if recommendation == "no play" else len(portfolio.entries),
        total_stake_cents=0 if recommendation == "no play" else portfolio.total_entry_fee_cents,
        half_kelly_fraction_used=config.half_kelly_fraction,
        marginal_ev_by_lineup_cents=marginal_ev_by_lineup,
        portfolio_ev_cents=portfolio.expected_profit_cents,
        portfolio_variance_cents=round(portfolio_variance, 4),
        portfolio_sd_cents=round(portfolio_sd, 4),
        ev_to_sd_ratio=round(ev_to_sd_ratio, 6) if ev_to_sd_ratio is not None else None,
        ror_estimate=ror_estimate,
        manual_lineups=manual_lineups,
        assumption_log={**assumption_log, "inputs_hash": stable_hash(assumption_log)},
        inputs_hash=report_hash,
    )


def _manual_lineup(entry, player_names: dict[str, str]) -> SplashManualLineup:
    player_names_tuple = tuple(
        player_names.get(player_id, player_id)
        for player_id in entry.lineup.player_ids
    )
    return SplashManualLineup(
        entry_number=entry.rank,
        lineup_id=entry.lineup.lineup_id,
        player_ids=entry.lineup.player_ids,
        player_names=player_names_tuple,
        marginal_ev_cents=entry.marginal_adjusted_ev_cents,
        expected_profit_cents=entry.candidate.expected_profit_cents,
        inputs_hash=stable_hash(
            {
                "entry_number": entry.rank,
                "lineup": entry.lineup,
                "player_names": player_names_tuple,
                "marginal_ev_cents": entry.marginal_adjusted_ev_cents,
            }
        ),
    )


def _ror_estimate(
    *,
    portfolio: SplashLineupPortfolio,
    portfolio_variance_cents: float,
    config: SplashFantasyReportConfig,
) -> dict[str, Any]:
    if not portfolio.entries or portfolio.total_entry_fee_cents <= 0:
        return {
            "method": "not_applicable_no_entries",
            "paper_only_probability": 0.0,
            "halt_probability": 0.0,
            "simulations": 0,
        }
    return_sd = (
        math.sqrt(portfolio_variance_cents) / portfolio.total_entry_fee_cents
        if portfolio_variance_cents > 0
        else 0.0
    )
    estimate = estimate_risk_of_ruin(
        starting_bankroll=config.bankroll_cents / 100,
        peak_bankroll=config.bankroll_cents / 100,
        bet_count=1,
        simulations=config.ror_simulations,
        stake_fraction=portfolio.total_entry_fee_cents / config.bankroll_cents,
        expected_return_per_staked_dollar=portfolio.expected_profit_cents
        / portfolio.total_entry_fee_cents,
        return_sd_per_staked_dollar=return_sd,
        paper_only_threshold=config.paper_only_drawdown_threshold,
        halt_threshold=config.halt_drawdown_threshold,
        seed=config.ror_seed,
    )
    return {
        "method": "single_portfolio_normal_return_monte_carlo",
        "paper_only_probability": round(estimate.paper_only_probability, 6),
        "halt_probability": round(estimate.halt_probability, 6),
        "worst_drawdown_pct": round(estimate.worst_drawdown_pct, 4),
        "median_terminal_bankroll_dollars": round(estimate.median_terminal_bankroll, 2),
        "simulations": estimate.simulations,
        "seed": config.ror_seed,
    }


def _no_play_reasons(
    *,
    portfolio: SplashLineupPortfolio,
    config: SplashFantasyReportConfig,
    ev_to_sd_ratio: float | None,
    ror_estimate: dict[str, Any],
) -> list[str]:
    reasons = []
    if portfolio.hard_review_items:
        reasons.append("too_uncertain:hard_review_items_present")
    if not portfolio.entries:
        reasons.append("no_qualified_lineups")
    if portfolio.expected_profit_cents <= config.minimum_portfolio_ev_cents:
        reasons.append("negative_or_insufficient_edge")
    if ev_to_sd_ratio is None:
        # A degenerate zero-variance portfolio with real entries is a red
        # flag, not a pass — fail closed instead of silently skipping the
        # volatility gate (an empty portfolio is separately caught above).
        if portfolio.entries:
            reasons.append("too_uncertain:no_variance_signal")
    elif ev_to_sd_ratio < config.minimum_ev_to_sd_ratio:
        reasons.append("too_uncertain:ev_to_sd_below_threshold")
    if ror_estimate["paper_only_probability"] > config.max_ror_probability:
        reasons.append("too_uncertain:ror_above_threshold")
    return reasons


def _validate_report_config(config: SplashFantasyReportConfig) -> None:
    if config.bankroll_cents <= 0:
        raise ValueError("bankroll_cents must be positive")
    if not 0.0 < config.half_kelly_fraction <= 1.0:
        raise ValueError("half_kelly_fraction must be in (0, 1]")
    if config.minimum_ev_to_sd_ratio < 0:
        raise ValueError("minimum_ev_to_sd_ratio must be non-negative")
    if not 0.0 <= config.max_ror_probability <= 1.0:
        raise ValueError("max_ror_probability must be between 0 and 1")
    if config.ror_simulations <= 0:
        raise ValueError("ror_simulations must be positive")
    if not 0 < config.paper_only_drawdown_threshold <= config.halt_drawdown_threshold <= 1:
        raise ValueError("drawdown thresholds must satisfy 0 < paper_only <= halt <= 1")
