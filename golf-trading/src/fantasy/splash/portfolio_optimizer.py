"""Portfolio construction for Splash lineups."""

from __future__ import annotations

import heapq
import itertools
import logging
from collections import Counter
from statistics import fmean
from typing import Any

from src.fantasy.splash.lineup_simulator import lineup_from_players
from src.fantasy.splash.models import (
    SplashLineup,
    SplashLineupPortfolio,
    SplashOpponentLineupAssumptions,
    SplashPayout,
    SplashPlayer,
    SplashPortfolioCandidate,
    SplashPortfolioEntry,
    SplashPortfolioOptimizationConfig,
    SplashScoringRule,
)
from src.fantasy.splash.opponent_lineups import simulate_lineup_with_generated_opponents
from src.storage.hashing import stable_hash

LOGGER = logging.getLogger(__name__)
PORTFOLIO_OPTIMIZER_VERSION = "splash-portfolio-optimizer-v1"


def portfolio_config(
    *,
    portfolio_name: str,
    max_entries: int,
    bankroll_cents: int,
    minimum_marginal_ev_cents: float,
    max_golfer_exposure_count: int,
    max_shared_players_between_lineups: int,
    half_kelly_fraction: float = 0.5,
) -> SplashPortfolioOptimizationConfig:
    config = SplashPortfolioOptimizationConfig(
        portfolio_name=portfolio_name,
        max_entries=max_entries,
        bankroll_cents=bankroll_cents,
        minimum_marginal_ev_cents=minimum_marginal_ev_cents,
        max_golfer_exposure_count=max_golfer_exposure_count,
        max_shared_players_between_lineups=max_shared_players_between_lineups,
        half_kelly_fraction=half_kelly_fraction,
        inputs_hash="",
    )
    _validate_config(config)
    return SplashPortfolioOptimizationConfig(
        portfolio_name=config.portfolio_name,
        max_entries=config.max_entries,
        bankroll_cents=config.bankroll_cents,
        minimum_marginal_ev_cents=config.minimum_marginal_ev_cents,
        max_golfer_exposure_count=config.max_golfer_exposure_count,
        max_shared_players_between_lineups=config.max_shared_players_between_lineups,
        half_kelly_fraction=config.half_kelly_fraction,
        inputs_hash=stable_hash(
            {
                "portfolio_name": config.portfolio_name,
                "max_entries": config.max_entries,
                "bankroll_cents": config.bankroll_cents,
                "minimum_marginal_ev_cents": config.minimum_marginal_ev_cents,
                "max_golfer_exposure_count": config.max_golfer_exposure_count,
                "max_shared_players_between_lineups": config.max_shared_players_between_lineups,
                "half_kelly_fraction": config.half_kelly_fraction,
            }
        ),
    )


def generate_tier_valid_lineups(
    *,
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    entry_fee_cents: int,
    lineup_id_prefix: str = "candidate",
    max_candidates: int | None = None,
) -> tuple[SplashLineup, ...]:
    """Enumerate tier-valid lineups in deterministic tier/player order."""
    if entry_fee_cents <= 0:
        raise ValueError("entry_fee_cents must be positive")
    if max_candidates is not None and max_candidates <= 0:
        raise ValueError("max_candidates must be positive when supplied")
    tier_choices = []
    for tier_id in sorted(tier_requirements):
        if tier_id not in players_by_tier:
            raise ValueError(f"Missing player pool for tier {tier_id}")
        required_count = tier_requirements[tier_id]
        players = players_by_tier[tier_id]
        if required_count <= 0:
            raise ValueError("tier requirements must be positive")
        if len(players) < required_count:
            raise ValueError(f"Tier {tier_id} does not have enough players")
        tier_choices.append(
            tuple(
                tuple(player.splash_player_id for player in choice)
                for choice in itertools.combinations(players, required_count)
            )
        )

    lineups = []
    for index, product_choice in enumerate(itertools.product(*tier_choices), start=1):
        if max_candidates is not None and len(lineups) >= max_candidates:
            break
        player_ids = tuple(player_id for tier_choice in product_choice for player_id in tier_choice)
        lineups.append(
            lineup_from_players(
                lineup_id=f"{lineup_id_prefix}-{index}",
                player_ids=player_ids,
                entry_fee_cents=entry_fee_cents,
            )
        )
    return tuple(lineups)


def generate_projected_tier_valid_lineups(
    *,
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    drop_worst_count: int,
    entry_fee_cents: int,
    lineup_id_prefix: str = "candidate",
    max_candidates: int,
) -> tuple[SplashLineup, ...]:
    """Generate the best projected tier-valid lineups by simulated mean score."""
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    if drop_worst_count < 0:
        raise ValueError("drop_worst_count must be non-negative")
    score_means = _score_means_for_players(players_by_tier, sampled_golfer_outcomes)
    scored_lineups = heapq.nsmallest(
        max_candidates,
        _iter_projected_lineup_keys(
            players_by_tier=players_by_tier,
            tier_requirements=tier_requirements,
            score_means=score_means,
            drop_worst_count=drop_worst_count,
        ),
        key=lambda item: (item[0], item[1]),
    )
    return tuple(
        lineup_from_players(
            lineup_id=f"{lineup_id_prefix}-{index}",
            player_ids=player_ids,
            entry_fee_cents=entry_fee_cents,
        )
        for index, (_, player_ids) in enumerate(scored_lineups, start=1)
    )


def evaluate_lineup_candidates(
    *,
    candidate_lineups: tuple[SplashLineup, ...],
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    drop_worst_count: int,
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    opponent_assumptions: SplashOpponentLineupAssumptions,
    portfolio_config: SplashPortfolioOptimizationConfig,
    evaluation_batch_size: int = 50,
) -> tuple[SplashPortfolioCandidate, ...]:
    """Evaluate candidates in batches against generated public fields."""
    _validate_config(portfolio_config)
    if evaluation_batch_size <= 0:
        raise ValueError("evaluation_batch_size must be positive")
    candidates = []
    for batch_start in range(0, len(candidate_lineups), evaluation_batch_size):
        batch = candidate_lineups[batch_start : batch_start + evaluation_batch_size]
        simulation = simulate_lineup_with_generated_opponents(
            target_lineups=batch,
            players_by_tier=players_by_tier,
            tier_requirements=tier_requirements,
            sampled_golfer_outcomes=sampled_golfer_outcomes,
            drop_worst_count=drop_worst_count,
            scoring_rules=scoring_rules,
            payout_ladder=payout_ladder,
            assumptions=opponent_assumptions,
        )
        results_by_lineup_id = {
            result.lineup_id: result for result in simulation.target_results
        }
        for lineup in batch:
            candidates.append(
                portfolio_candidate_from_result(
                    lineup=lineup,
                    simulation_result=results_by_lineup_id[lineup.lineup_id],
                    bankroll_cents=portfolio_config.bankroll_cents,
                    half_kelly_fraction=portfolio_config.half_kelly_fraction,
                    target_duplication_count=simulation.target_duplication_counts[lineup.lineup_id],
                )
            )
    return tuple(candidates)


def portfolio_candidate_from_result(
    *,
    lineup: SplashLineup,
    simulation_result,
    bankroll_cents: int,
    half_kelly_fraction: float,
    target_duplication_count: int = 1,
) -> SplashPortfolioCandidate:
    if bankroll_cents <= 0:
        raise ValueError("bankroll_cents must be positive")
    if not 0.0 < half_kelly_fraction <= 1.0:
        raise ValueError("half_kelly_fraction must be in (0, 1]")
    expected_profit = simulation_result.expected_payout_cents - lineup.entry_fee_cents
    variance_penalty = simulation_result.profit_variance_cents / (2 * bankroll_cents)
    adjusted_ev = expected_profit - (half_kelly_fraction * variance_penalty)
    expected_log_growth = (
        expected_profit / bankroll_cents
        - simulation_result.profit_variance_cents / (2 * bankroll_cents * bankroll_cents)
    )
    candidate_hash = stable_hash(
        {
            "optimizer_version": PORTFOLIO_OPTIMIZER_VERSION,
            "lineup": lineup,
            "simulation_result": simulation_result,
            "bankroll_cents": bankroll_cents,
            "half_kelly_fraction": half_kelly_fraction,
            "target_duplication_count": target_duplication_count,
        }
    )
    return SplashPortfolioCandidate(
        lineup=lineup,
        simulation_result=simulation_result,
        expected_profit_cents=round(expected_profit, 4),
        expected_log_growth=round(expected_log_growth, 10),
        half_kelly_adjusted_ev_cents=round(adjusted_ev, 4),
        target_duplication_count=target_duplication_count,
        inputs_hash=candidate_hash,
    )


def optimize_lineup_portfolio(
    *,
    candidates: tuple[SplashPortfolioCandidate, ...],
    config: SplashPortfolioOptimizationConfig,
    hard_review_items: tuple[str, ...] = (),
) -> SplashLineupPortfolio:
    """Greedily select a constrained lineup portfolio by adjusted EV."""
    _validate_config(config)
    assumption_log: dict[str, Any] = {
        "optimizer_version": PORTFOLIO_OPTIMIZER_VERSION,
        "portfolio_name": config.portfolio_name,
        "objective": "expected_profit_minus_half_kelly_variance_penalty",
        "selection_method": "deterministic_greedy",
        "max_entries": config.max_entries,
        "bankroll_cents": config.bankroll_cents,
        "minimum_marginal_ev_cents": config.minimum_marginal_ev_cents,
        "max_golfer_exposure_count": config.max_golfer_exposure_count,
        "max_shared_players_between_lineups": config.max_shared_players_between_lineups,
        "half_kelly_fraction": config.half_kelly_fraction,
    }
    LOGGER.info("Optimizing Splash lineup portfolio with assumptions: %s", assumption_log)
    selected_entries: list[SplashPortfolioEntry] = []
    golfer_exposures: Counter[str] = Counter()
    selected_keys: set[tuple[str, ...]] = set()

    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.half_kelly_adjusted_ev_cents,
            item.expected_profit_cents,
            -item.target_duplication_count,
            item.lineup.lineup_id,
        ),
        reverse=True,
    ):
        if len(selected_entries) >= config.max_entries:
            break
        if candidate.half_kelly_adjusted_ev_cents < config.minimum_marginal_ev_cents:
            continue
        lineup_key = tuple(candidate.lineup.player_ids)
        if lineup_key in selected_keys:
            continue
        if not _passes_exposure_cap(candidate.lineup, golfer_exposures, config):
            continue
        if not _passes_correlation_cap(candidate.lineup, selected_entries, config):
            continue

        selected_keys.add(lineup_key)
        golfer_exposures.update(candidate.lineup.player_ids)
        selected_entries.append(
            SplashPortfolioEntry(
                rank=len(selected_entries) + 1,
                lineup=candidate.lineup,
                candidate=candidate,
                marginal_adjusted_ev_cents=candidate.half_kelly_adjusted_ev_cents,
                inputs_hash=stable_hash(
                    {
                        "rank": len(selected_entries) + 1,
                        "lineup": candidate.lineup,
                        "candidate": candidate,
                    }
                ),
            )
        )

    return _portfolio_from_entries(
        entries=tuple(selected_entries),
        config=config,
        assumption_log=assumption_log,
        hard_review_items=hard_review_items,
    )


def _portfolio_from_entries(
    *,
    entries: tuple[SplashPortfolioEntry, ...],
    config: SplashPortfolioOptimizationConfig,
    assumption_log: dict[str, Any],
    hard_review_items: tuple[str, ...],
) -> SplashLineupPortfolio:
    total_entry_fee = sum(entry.lineup.entry_fee_cents for entry in entries)
    expected_payout = sum(entry.candidate.simulation_result.expected_payout_cents for entry in entries)
    expected_profit = sum(entry.candidate.expected_profit_cents for entry in entries)
    adjusted_ev = sum(entry.candidate.half_kelly_adjusted_ev_cents for entry in entries)
    expected_log_growth = sum(entry.candidate.expected_log_growth for entry in entries)
    golfer_exposures = dict(Counter(player_id for entry in entries for player_id in entry.lineup.player_ids))
    portfolio_hash = stable_hash(
        {
            "optimizer_version": PORTFOLIO_OPTIMIZER_VERSION,
            "config": config,
            "entries": entries,
            "assumption_log": assumption_log,
            "hard_review_items": hard_review_items,
        }
    )
    return SplashLineupPortfolio(
        portfolio_name=config.portfolio_name,
        entries=entries,
        total_entry_fee_cents=total_entry_fee,
        expected_payout_cents=round(expected_payout, 4),
        expected_profit_cents=round(expected_profit, 4),
        expected_roi=round(expected_profit / total_entry_fee, 6) if total_entry_fee else 0.0,
        expected_log_growth=round(expected_log_growth, 10),
        half_kelly_adjusted_ev_cents=round(adjusted_ev, 4),
        golfer_exposures=golfer_exposures,
        assumption_log={**assumption_log, "inputs_hash": stable_hash(assumption_log)},
        hard_review_items=hard_review_items,
        inputs_hash=portfolio_hash,
    )


def _validate_config(config: SplashPortfolioOptimizationConfig) -> None:
    if config.max_entries <= 0:
        raise ValueError("max_entries must be positive")
    if config.bankroll_cents <= 0:
        raise ValueError("bankroll_cents must be positive")
    if config.max_golfer_exposure_count <= 0:
        raise ValueError("max_golfer_exposure_count must be positive")
    if config.max_shared_players_between_lineups < 0:
        raise ValueError("max_shared_players_between_lineups must be non-negative")
    if not 0.0 < config.half_kelly_fraction <= 1.0:
        raise ValueError("half_kelly_fraction must be in (0, 1]")


def _score_means_for_players(
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
) -> dict[str, float]:
    score_means: dict[str, float] = {}
    missing_scores = []
    for player in (player for tier in players_by_tier.values() for player in tier):
        samples = sampled_golfer_outcomes.get(player.splash_player_id)
        if not samples:
            missing_scores.append(player.splash_player_id)
            continue
        score_means[player.splash_player_id] = fmean(samples)
    if missing_scores:
        raise ValueError(f"Missing sampled outcomes for players: {sorted(missing_scores)}")
    return score_means


def _iter_projected_lineup_keys(
    *,
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    score_means: dict[str, float],
    drop_worst_count: int,
):
    tier_choices = []
    for tier_id in sorted(tier_requirements):
        if tier_id not in players_by_tier:
            raise ValueError(f"Missing player pool for tier {tier_id}")
        required_count = tier_requirements[tier_id]
        players = players_by_tier[tier_id]
        if required_count <= 0:
            raise ValueError("tier requirements must be positive")
        if len(players) < required_count:
            raise ValueError(f"Tier {tier_id} does not have enough players")
        tier_choices.append(
            tuple(
                tuple(player.splash_player_id for player in choice)
                for choice in itertools.combinations(players, required_count)
            )
        )

    for product_choice in itertools.product(*tier_choices):
        player_ids = tuple(player_id for tier_choice in product_choice for player_id in tier_choice)
        if drop_worst_count >= len(player_ids):
            raise ValueError("drop_worst_count must be less than lineup size")
        projected_scores = sorted(score_means[player_id] for player_id in player_ids)
        projected_lineup_score = sum(projected_scores[: len(projected_scores) - drop_worst_count])
        yield projected_lineup_score, player_ids


def _passes_exposure_cap(
    lineup: SplashLineup,
    golfer_exposures: Counter[str],
    config: SplashPortfolioOptimizationConfig,
) -> bool:
    return all(
        golfer_exposures[player_id] + 1 <= config.max_golfer_exposure_count
        for player_id in lineup.player_ids
    )


def _passes_correlation_cap(
    lineup: SplashLineup,
    selected_entries: list[SplashPortfolioEntry],
    config: SplashPortfolioOptimizationConfig,
) -> bool:
    player_ids = set(lineup.player_ids)
    return all(
        len(player_ids & set(entry.lineup.player_ids)) <= config.max_shared_players_between_lineups
        for entry in selected_entries
    )
