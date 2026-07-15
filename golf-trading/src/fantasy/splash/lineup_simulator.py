"""Splash lineup simulation over sampled golfer score outcomes."""

from __future__ import annotations

from statistics import fmean

from src.fantasy.splash.models import (
    SplashLineup,
    SplashLineupSimulationResult,
    SplashPayout,
    SplashPlayerScoreDistribution,
    SplashScoringRule,
)
from src.storage.hashing import stable_hash

SIMULATOR_VERSION = "splash-lineup-sim-v1"


def lineup_from_players(
    *,
    lineup_id: str,
    player_ids: tuple[str, ...],
    entry_fee_cents: int,
) -> SplashLineup:
    if entry_fee_cents <= 0:
        raise ValueError("entry_fee_cents must be positive")
    return SplashLineup(
        lineup_id=lineup_id,
        player_ids=player_ids,
        entry_fee_cents=entry_fee_cents,
        inputs_hash=stable_hash(
            {
                "lineup_id": lineup_id,
                "player_ids": player_ids,
                "entry_fee_cents": entry_fee_cents,
            }
        ),
    )


def outcomes_from_score_distributions(
    distributions: tuple[SplashPlayerScoreDistribution, ...],
) -> dict[str, tuple[float, ...]]:
    return {
        distribution.splash_player_id: distribution.score_samples
        for distribution in distributions
    }


def simulate_lineup_outcomes(
    *,
    lineups: tuple[SplashLineup, ...],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    player_tiers: dict[str, int],
    tier_requirements: dict[int, int],
    drop_worst_count: int,
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    field_size: int,
) -> tuple[SplashLineupSimulationResult, ...]:
    """Simulate contest metrics for tier-valid lineups.

    Lower Splash score is better. Tied lineups split the payout slots they
    occupy, so a two-way tie for first averages first- and second-place payout.
    """
    _validate_inputs(
        lineups=lineups,
        sampled_golfer_outcomes=sampled_golfer_outcomes,
        player_tiers=player_tiers,
        tier_requirements=tier_requirements,
        drop_worst_count=drop_worst_count,
        field_size=field_size,
    )
    simulations = _simulation_count(sampled_golfer_outcomes)
    payout_by_rank = _payout_by_rank(payout_ladder)
    lineup_scores = {
        lineup.lineup_id: [
            score_lineup(
                lineup=lineup,
                sampled_golfer_outcomes=sampled_golfer_outcomes,
                simulation_index=index,
                drop_worst_count=drop_worst_count,
            )
            for index in range(simulations)
        ]
        for lineup in lineups
    }
    payouts_by_lineup = {lineup.lineup_id: [] for lineup in lineups}
    ranks_by_lineup = {lineup.lineup_id: [] for lineup in lineups}

    for index in range(simulations):
        scores = [(lineup.lineup_id, lineup_scores[lineup.lineup_id][index]) for lineup in lineups]
        for tied_ids, start_rank, end_rank in _rank_groups(scores):
            payout = _tie_adjusted_payout(start_rank, end_rank, payout_by_rank)
            for lineup_id in tied_ids:
                payouts_by_lineup[lineup_id].append(payout)
                ranks_by_lineup[lineup_id].append(start_rank)

    return tuple(
        _result_for_lineup(
            lineup=lineup,
            scores=lineup_scores[lineup.lineup_id],
            payouts=payouts_by_lineup[lineup.lineup_id],
            ranks=ranks_by_lineup[lineup.lineup_id],
            scoring_rules=scoring_rules,
            payout_ladder=payout_ladder,
            drop_worst_count=drop_worst_count,
            field_size=field_size,
        )
        for lineup in lineups
    )


def score_lineup(
    *,
    lineup: SplashLineup,
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    simulation_index: int,
    drop_worst_count: int,
) -> float:
    scores = [
        sampled_golfer_outcomes[player_id][simulation_index]
        for player_id in lineup.player_ids
    ]
    if drop_worst_count < 0:
        raise ValueError("drop_worst_count must be non-negative")
    if drop_worst_count >= len(scores):
        raise ValueError("drop_worst_count must be less than lineup size")
    kept_scores = sorted(scores)[: len(scores) - drop_worst_count]
    return sum(kept_scores)


def payout_for_rank(rank: int, payout_ladder: tuple[SplashPayout, ...]) -> int:
    if rank <= 0:
        raise ValueError("rank must be positive")
    for payout in payout_ladder:
        if payout.start_rank <= rank <= payout.end_rank:
            return payout.amount_cents
    return 0


def _validate_inputs(
    *,
    lineups: tuple[SplashLineup, ...],
    sampled_golfer_outcomes: dict[str, tuple[float, ...]],
    player_tiers: dict[str, int],
    tier_requirements: dict[int, int],
    drop_worst_count: int,
    field_size: int,
) -> None:
    if not lineups:
        raise ValueError("lineups must not be empty")
    if field_size != len(lineups):
        raise ValueError("field_size must equal the number of simulated lineups")
    if drop_worst_count < 0:
        raise ValueError("drop_worst_count must be non-negative")
    simulations = _simulation_count(sampled_golfer_outcomes)
    if simulations <= 0:
        raise ValueError("sampled_golfer_outcomes must include at least one simulation")

    for lineup in lineups:
        if lineup.entry_fee_cents <= 0:
            raise ValueError("lineup entry_fee_cents must be positive")
        if len(set(lineup.player_ids)) != len(lineup.player_ids):
            raise ValueError(f"Lineup {lineup.lineup_id} contains duplicate players")
        if len(lineup.player_ids) != sum(tier_requirements.values()):
            raise ValueError(f"Lineup {lineup.lineup_id} has the wrong player count")
        if drop_worst_count >= len(lineup.player_ids):
            raise ValueError("drop_worst_count must be less than lineup size")
        missing_scores = [
            player_id for player_id in lineup.player_ids if player_id not in sampled_golfer_outcomes
        ]
        if missing_scores:
            raise ValueError(f"Missing sampled outcomes for players: {missing_scores}")
        missing_tiers = [player_id for player_id in lineup.player_ids if player_id not in player_tiers]
        if missing_tiers:
            raise ValueError(f"Missing tier assignments for players: {missing_tiers}")
        tier_counts = {
            tier_id: sum(1 for player_id in lineup.player_ids if player_tiers[player_id] == tier_id)
            for tier_id in tier_requirements
        }
        if tier_counts != tier_requirements:
            raise ValueError(
                f"Lineup {lineup.lineup_id} violates tier requirements: {tier_counts}"
            )


def _simulation_count(sampled_golfer_outcomes: dict[str, tuple[float, ...]]) -> int:
    counts = {len(samples) for samples in sampled_golfer_outcomes.values()}
    if len(counts) != 1:
        raise ValueError("All sampled golfer outcome arrays must have the same length")
    return counts.pop()


def _payout_by_rank(payout_ladder: tuple[SplashPayout, ...]) -> dict[int, int]:
    payouts: dict[int, int] = {}
    for payout in payout_ladder:
        for rank in range(payout.start_rank, payout.end_rank + 1):
            payouts[rank] = payout.amount_cents
    return payouts


def _rank_groups(scores: list[tuple[str, float]]) -> list[tuple[tuple[str, ...], int, int]]:
    ordered = sorted(scores, key=lambda row: (row[1], row[0]))
    groups = []
    start_index = 0
    while start_index < len(ordered):
        score = ordered[start_index][1]
        end_index = start_index
        while end_index + 1 < len(ordered) and ordered[end_index + 1][1] == score:
            end_index += 1
        tied_ids = tuple(lineup_id for lineup_id, _ in ordered[start_index : end_index + 1])
        groups.append((tied_ids, start_index + 1, end_index + 1))
        start_index = end_index + 1
    return groups


def _tie_adjusted_payout(start_rank: int, end_rank: int, payout_by_rank: dict[int, int]) -> float:
    occupied_payouts = [
        payout_by_rank.get(rank, 0)
        for rank in range(start_rank, end_rank + 1)
    ]
    return fmean(occupied_payouts)


def _result_for_lineup(
    *,
    lineup: SplashLineup,
    scores: list[float],
    payouts: list[float],
    ranks: list[int],
    scoring_rules: tuple[SplashScoringRule, ...],
    payout_ladder: tuple[SplashPayout, ...],
    drop_worst_count: int,
    field_size: int,
) -> SplashLineupSimulationResult:
    profits = [payout - lineup.entry_fee_cents for payout in payouts]
    expected_payout = fmean(payouts)
    result_hash = stable_hash(
        {
            "simulator_version": SIMULATOR_VERSION,
            "lineup": lineup,
            "scores": scores,
            "payouts": payouts,
            "ranks": ranks,
            "scoring_rules": scoring_rules,
            "payout_ladder": payout_ladder,
            "drop_worst_count": drop_worst_count,
            "field_size": field_size,
        }
    )
    return SplashLineupSimulationResult(
        lineup_id=lineup.lineup_id,
        simulations=len(payouts),
        expected_payout_cents=round(expected_payout, 4),
        roi=round((expected_payout - lineup.entry_fee_cents) / lineup.entry_fee_cents, 6),
        cash_probability=round(sum(1 for payout in payouts if payout > 0) / len(payouts), 6),
        top_10_probability=round(sum(1 for rank in ranks if rank <= 10) / len(ranks), 6),
        win_probability=round(sum(1 for rank in ranks if rank == 1) / len(ranks), 6),
        profit_variance_cents=round(_population_variance(profits), 4),
        drawdown_contribution_cents=round(fmean(max(-profit, 0.0) for profit in profits), 4),
        mean_score=round(fmean(scores), 4),
        inputs_hash=result_hash,
    )


def _population_variance(values: list[float]) -> float:
    mean = fmean(values)
    return fmean((value - mean) ** 2 for value in values)
