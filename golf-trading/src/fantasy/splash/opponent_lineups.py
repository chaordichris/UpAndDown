"""Opponent lineup generation and ownership sensitivity for Splash contests."""

from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from src.fantasy.splash.lineup_simulator import lineup_from_players, simulate_lineup_outcomes
from src.fantasy.splash.models import (
    SplashLineup,
    SplashLineupDuplicationEstimate,
    SplashLineupSimulationResult,
    SplashOpponentLineupAssumptions,
    SplashOpponentLineupPool,
    SplashOpponentSimulationResult,
    SplashOwnershipSensitivityReport,
    SplashOwnershipSensitivityScenario,
    SplashPayout,
    SplashPlayer,
    SplashScoringRule,
)
from src.storage.hashing import stable_hash

LOGGER = logging.getLogger(__name__)
OPPONENT_GENERATOR_VERSION = "splash-opponent-lineups-v1"


def generate_opponent_lineup_pool(
    *,
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    entry_fee_cents: int,
    assumptions: SplashOpponentLineupAssumptions,
    reserved_lineup_count: int = 0,
) -> SplashOpponentLineupPool:
    """Generate a public-field opponent pool from configurable ownership assumptions."""
    _validate_generation_inputs(
        players_by_tier=players_by_tier,
        tier_requirements=tier_requirements,
        entry_fee_cents=entry_fee_cents,
        assumptions=assumptions,
        reserved_lineup_count=reserved_lineup_count,
    )
    assumption_log = _assumption_log(assumptions, reserved_lineup_count=reserved_lineup_count)
    LOGGER.info("Generating Splash opponent lineup pool with assumptions: %s", assumption_log)

    rng = random.Random(assumptions.seed)
    weights_by_tier = {
        tier_id: _tier_player_weights(
            tier_id=tier_id,
            players=players,
            assumptions=assumptions,
            rng=rng,
        )
        for tier_id, players in players_by_tier.items()
    }
    opponent_count = assumptions.public_contest_size - reserved_lineup_count
    lineups = tuple(
        _generate_one_lineup(
            lineup_id=f"opponent-{index + 1}",
            weights_by_tier=weights_by_tier,
            tier_requirements=tier_requirements,
            entry_fee_cents=entry_fee_cents,
            rng=rng,
        )
        for index in range(opponent_count)
    )
    duplicate_estimates = _duplication_estimates(lineups)
    duplicated_entry_count = sum(
        estimate.duplicate_count - 1
        for estimate in duplicate_estimates
        if estimate.duplicate_count > 1
    )
    result_hash = stable_hash(
        {
            "generator_version": OPPONENT_GENERATOR_VERSION,
            "players_by_tier": players_by_tier,
            "tier_requirements": tier_requirements,
            "entry_fee_cents": entry_fee_cents,
            "assumption_log": assumption_log,
            "lineups": lineups,
            "duplicates": duplicate_estimates,
        }
    )
    return SplashOpponentLineupPool(
        lineups=lineups,
        duplicate_estimates=duplicate_estimates,
        max_duplicate_count=max((estimate.duplicate_count for estimate in duplicate_estimates), default=0),
        duplicated_entry_count=duplicated_entry_count,
        duplicated_entry_share=round(duplicated_entry_count / opponent_count, 6)
        if opponent_count
        else 0.0,
        assumption_log=assumption_log,
        inputs_hash=result_hash,
    )


def simulate_lineup_with_generated_opponents(
    *,
    target_lineups: tuple[SplashLineup, ...],
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    drop_worst_count: int,
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    assumptions: SplashOpponentLineupAssumptions,
) -> SplashOpponentSimulationResult:
    """Evaluate target lineups against a generated public contest field."""
    if not target_lineups:
        raise ValueError("target_lineups must not be empty")
    opponent_pool = generate_opponent_lineup_pool(
        players_by_tier=players_by_tier,
        tier_requirements=tier_requirements,
        entry_fee_cents=target_lineups[0].entry_fee_cents,
        assumptions=assumptions,
        reserved_lineup_count=len(target_lineups),
    )
    all_lineups = target_lineups + opponent_pool.lineups
    player_tiers = _player_tiers(players_by_tier)
    all_results = simulate_lineup_outcomes(
        lineups=all_lineups,
        sampled_golfer_outcomes=sampled_golfer_outcomes,
        player_tiers=player_tiers,
        tier_requirements=tier_requirements,
        drop_worst_count=drop_worst_count,
        scoring_rules=scoring_rules,
        payout_ladder=payout_ladder,
        field_size=assumptions.public_contest_size,
    )
    target_ids = {lineup.lineup_id for lineup in target_lineups}
    target_results = tuple(result for result in all_results if result.lineup_id in target_ids)
    lineups_by_key = Counter(tuple(lineup.player_ids) for lineup in all_lineups)
    target_duplication_counts = {
        lineup.lineup_id: lineups_by_key[tuple(lineup.player_ids)]
        for lineup in target_lineups
    }
    assumption_log = {
        **opponent_pool.assumption_log,
        "target_lineup_count": len(target_lineups),
        "target_duplication_counts": target_duplication_counts,
    }
    result_hash = stable_hash(
        {
            "generator_version": OPPONENT_GENERATOR_VERSION,
            "target_lineups": target_lineups,
            "opponent_pool": opponent_pool,
            "target_results": target_results,
            "target_duplication_counts": target_duplication_counts,
            "drop_worst_count": drop_worst_count,
            "scoring_rules": scoring_rules,
            "payout_ladder": payout_ladder,
        }
    )
    return SplashOpponentSimulationResult(
        target_results=target_results,
        opponent_pool=opponent_pool,
        target_duplication_counts=target_duplication_counts,
        assumption_log=assumption_log,
        inputs_hash=result_hash,
    )


def run_opponent_ownership_sensitivity(
    *,
    target_lineups: tuple[SplashLineup, ...],
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    drop_worst_count: int,
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    assumptions: SplashOpponentLineupAssumptions,
) -> SplashOwnershipSensitivityReport:
    """Run EV sensitivity over ownership concentration assumptions."""
    scenarios = tuple(
        _sensitivity_scenario(
            multiplier=multiplier,
            target_lineups=target_lineups,
            players_by_tier=players_by_tier,
            tier_requirements=tier_requirements,
            sampled_golfer_outcomes=sampled_golfer_outcomes,
            drop_worst_count=drop_worst_count,
            scoring_rules=scoring_rules,
            payout_ladder=payout_ladder,
            assumptions=assumptions,
        )
        for multiplier in assumptions.sensitivity_concentration_multipliers
    )
    if not scenarios:
        raise ValueError("sensitivity_concentration_multipliers must not be empty")

    roi_range_by_lineup: dict[str, float] = {}
    payout_range_by_lineup: dict[str, float] = {}
    ev_dependency_flags: dict[str, bool] = {}
    for lineup in target_lineups:
        scenario_results = [
            _result_by_lineup_id(scenario.result.target_results, lineup.lineup_id)
            for scenario in scenarios
        ]
        roi_values = [result.roi for result in scenario_results]
        payout_values = [result.expected_payout_cents for result in scenario_results]
        roi_range = round(max(roi_values) - min(roi_values), 6)
        payout_range = round(max(payout_values) - min(payout_values), 4)
        roi_range_by_lineup[lineup.lineup_id] = roi_range
        payout_range_by_lineup[lineup.lineup_id] = payout_range
        ev_dependency_flags[lineup.lineup_id] = roi_range > assumptions.sensitivity_roi_threshold

    report_hash = stable_hash(
        {
            "generator_version": OPPONENT_GENERATOR_VERSION,
            "scenarios": scenarios,
            "roi_range_by_lineup": roi_range_by_lineup,
            "expected_payout_range_cents_by_lineup": payout_range_by_lineup,
            "sensitivity_roi_threshold": assumptions.sensitivity_roi_threshold,
        }
    )
    return SplashOwnershipSensitivityReport(
        scenarios=scenarios,
        roi_range_by_lineup=roi_range_by_lineup,
        expected_payout_range_cents_by_lineup=payout_range_by_lineup,
        ev_dependency_flags=ev_dependency_flags,
        sensitivity_roi_threshold=assumptions.sensitivity_roi_threshold,
        inputs_hash=report_hash,
    )


def _sensitivity_scenario(
    *,
    multiplier: float,
    target_lineups: tuple[SplashLineup, ...],
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    drop_worst_count: int,
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    assumptions: SplashOpponentLineupAssumptions,
) -> SplashOwnershipSensitivityScenario:
    if multiplier <= 0:
        raise ValueError("sensitivity concentration multipliers must be positive")
    scenario_assumptions = replace(
        assumptions,
        ownership_concentration=assumptions.ownership_concentration * multiplier,
    )
    result = simulate_lineup_with_generated_opponents(
        target_lineups=target_lineups,
        players_by_tier=players_by_tier,
        tier_requirements=tier_requirements,
        sampled_golfer_outcomes=sampled_golfer_outcomes,
        drop_worst_count=drop_worst_count,
        scoring_rules=scoring_rules,
        payout_ladder=payout_ladder,
        assumptions=scenario_assumptions,
    )
    label = f"{multiplier:g}x"
    return SplashOwnershipSensitivityScenario(
        label=label,
        ownership_concentration=scenario_assumptions.ownership_concentration,
        result=result,
        inputs_hash=stable_hash(
            {
                "label": label,
                "multiplier": multiplier,
                "ownership_concentration": scenario_assumptions.ownership_concentration,
                "result": result,
            }
        ),
    )


def _validate_generation_inputs(
    *,
    players_by_tier: dict[int, tuple[SplashPlayer, ...]],
    tier_requirements: dict[int, int],
    entry_fee_cents: int,
    assumptions: SplashOpponentLineupAssumptions,
    reserved_lineup_count: int,
) -> None:
    if entry_fee_cents <= 0:
        raise ValueError("entry_fee_cents must be positive")
    if assumptions.public_contest_size <= 0:
        raise ValueError("public_contest_size must be positive")
    if reserved_lineup_count < 0:
        raise ValueError("reserved_lineup_count must be non-negative")
    if reserved_lineup_count > assumptions.public_contest_size:
        raise ValueError("reserved_lineup_count cannot exceed public_contest_size")
    if assumptions.datagolf_rank_weight < 0:
        raise ValueError("datagolf_rank_weight must be non-negative")
    if assumptions.tier_position_weight < 0:
        raise ValueError("tier_position_weight must be non-negative")
    if any(value < 0 for value in assumptions.external_ownership_by_player_id.values()):
        raise ValueError("external ownership priors must be non-negative")
    if assumptions.ownership_concentration <= 0:
        raise ValueError("ownership_concentration must be positive")
    if assumptions.ownership_uncertainty_sd < 0:
        raise ValueError("ownership_uncertainty_sd must be non-negative")
    missing_tiers = sorted(set(tier_requirements) - set(players_by_tier))
    if missing_tiers:
        raise ValueError(f"Missing player pools for tiers: {missing_tiers}")
    for tier_id, required_count in tier_requirements.items():
        if required_count <= 0:
            raise ValueError("tier requirements must be positive")
        if len(players_by_tier[tier_id]) < required_count:
            raise ValueError(f"Tier {tier_id} does not have enough players")


def _assumption_log(
    assumptions: SplashOpponentLineupAssumptions,
    *,
    reserved_lineup_count: int,
) -> dict[str, Any]:
    log = {
        "generator_version": OPPONENT_GENERATOR_VERSION,
        "public_contest_size": assumptions.public_contest_size,
        "reserved_lineup_count": reserved_lineup_count,
        "generated_opponent_count": assumptions.public_contest_size - reserved_lineup_count,
        "seed": assumptions.seed,
        "datagolf_rank_weight": assumptions.datagolf_rank_weight,
        "tier_position_weight": assumptions.tier_position_weight,
        "external_ownership_player_count": len(assumptions.external_ownership_by_player_id),
        "external_ownership_inputs_hash": stable_hash(assumptions.external_ownership_by_player_id)
        if assumptions.external_ownership_by_player_id
        else None,
        "ownership_concentration": assumptions.ownership_concentration,
        "ownership_uncertainty_sd": assumptions.ownership_uncertainty_sd,
        "sensitivity_concentration_multipliers": assumptions.sensitivity_concentration_multipliers,
        "sensitivity_roi_threshold": assumptions.sensitivity_roi_threshold,
    }
    log["inputs_hash"] = stable_hash(log)
    return log


def _tier_player_weights(
    *,
    tier_id: int,
    players: tuple[SplashPlayer, ...],
    assumptions: SplashOpponentLineupAssumptions,
    rng: random.Random,
) -> tuple[tuple[SplashPlayer, float], ...]:
    weighted_players = []
    tier_external_average = _tier_external_ownership_average(players, assumptions)
    for position, player in enumerate(players, start=1):
        if player.tier_id != tier_id:
            raise ValueError(f"Player {player.splash_player_id} has tier {player.tier_id}, expected {tier_id}")
        if player.datagolf_rank is None or player.datagolf_rank <= 0:
            raise ValueError(f"Player {player.splash_player_id} is missing a positive DataGolf rank")
        rank_component = (1.0 / player.datagolf_rank) ** assumptions.datagolf_rank_weight
        position_component = (1.0 / position) ** assumptions.tier_position_weight
        external_component = _external_ownership_component(
            player=player,
            tier_external_average=tier_external_average,
            assumptions=assumptions,
        )
        weight = (
            rank_component * position_component * external_component
        ) ** assumptions.ownership_concentration
        if assumptions.ownership_uncertainty_sd:
            weight *= rng.lognormvariate(0.0, assumptions.ownership_uncertainty_sd)
        weighted_players.append((player, weight))
    if sum(weight for _, weight in weighted_players) <= 0:
        raise ValueError("Opponent ownership weights must sum to a positive value")
    return tuple(weighted_players)


def _tier_external_ownership_average(
    players: tuple[SplashPlayer, ...],
    assumptions: SplashOpponentLineupAssumptions,
) -> float | None:
    ownership_values = [
        assumptions.external_ownership_by_player_id[player.splash_player_id]
        for player in players
        if player.splash_player_id in assumptions.external_ownership_by_player_id
    ]
    if not ownership_values:
        return None
    tier_average = sum(ownership_values) / len(ownership_values)
    return tier_average if tier_average > 0 else None


def _external_ownership_component(
    *,
    player: SplashPlayer,
    tier_external_average: float | None,
    assumptions: SplashOpponentLineupAssumptions,
) -> float:
    if tier_external_average is None:
        return 1.0
    ownership = assumptions.external_ownership_by_player_id.get(player.splash_player_id)
    if ownership is None:
        return 1.0
    return ownership / tier_external_average


def _generate_one_lineup(
    *,
    lineup_id: str,
    weights_by_tier: dict[int, tuple[tuple[SplashPlayer, float], ...]],
    tier_requirements: dict[int, int],
    entry_fee_cents: int,
    rng: random.Random,
) -> SplashLineup:
    player_ids: list[str] = []
    for tier_id in sorted(tier_requirements):
        selected = _weighted_sample_without_replacement(
            weights_by_tier[tier_id],
            tier_requirements[tier_id],
            rng,
        )
        player_ids.extend(player.splash_player_id for player in selected)
    return lineup_from_players(
        lineup_id=lineup_id,
        player_ids=tuple(player_ids),
        entry_fee_cents=entry_fee_cents,
    )


def _weighted_sample_without_replacement(
    weighted_players: tuple[tuple[SplashPlayer, float], ...],
    count: int,
    rng: random.Random,
) -> tuple[SplashPlayer, ...]:
    remaining = list(weighted_players)
    selected = []
    for _ in range(count):
        total_weight = sum(weight for _, weight in remaining)
        draw = rng.random() * total_weight
        cumulative = 0.0
        for index, (player, weight) in enumerate(remaining):
            cumulative += weight
            if draw <= cumulative:
                selected.append(player)
                remaining.pop(index)
                break
    return tuple(selected)


def _duplication_estimates(lineups: tuple[SplashLineup, ...]) -> tuple[SplashLineupDuplicationEstimate, ...]:
    ids_by_key: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for lineup in lineups:
        ids_by_key[tuple(lineup.player_ids)].append(lineup.lineup_id)
    return tuple(
        SplashLineupDuplicationEstimate(
            lineup_key=lineup_key,
            lineup_ids=tuple(lineup_ids),
            duplicate_count=len(lineup_ids),
            inputs_hash=stable_hash(
                {
                    "lineup_key": lineup_key,
                    "lineup_ids": lineup_ids,
                    "duplicate_count": len(lineup_ids),
                }
            ),
        )
        for lineup_key, lineup_ids in sorted(ids_by_key.items())
    )


def _player_tiers(players_by_tier: dict[int, tuple[SplashPlayer, ...]]) -> dict[str, int]:
    return {
        player.splash_player_id: tier_id
        for tier_id, players in players_by_tier.items()
        for player in players
    }


def _result_by_lineup_id(
    results: tuple[SplashLineupSimulationResult, ...],
    lineup_id: str,
) -> SplashLineupSimulationResult:
    for result in results:
        if result.lineup_id == lineup_id:
            return result
    raise KeyError(f"Missing sensitivity result for lineup {lineup_id}")
