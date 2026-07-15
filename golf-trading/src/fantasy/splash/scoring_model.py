"""DataGolf-anchored posterior predictive Splash score simulation."""

from __future__ import annotations

import math
import random
from statistics import fmean
from typing import Any

from src.fantasy.splash.models import (
    DataGolfScoreAnchor,
    SplashPlayerMapping,
    SplashPlayerScoreDistribution,
    SplashScoringConfig,
)
from src.storage.hashing import stable_hash

MODEL_VERSION = "splash-datagolf-score-v1"


def datagolf_score_anchor_from_row(row: dict[str, Any]) -> DataGolfScoreAnchor:
    """Parse one DataGolf score-anchor row required by the Splash score model."""
    anchor = DataGolfScoreAnchor(
        datagolf_player_id=str(row["player_id"]),
        player_name=str(row["player_name"]),
        datagolf_rank=int(row["datagolf_rank"]),
        make_cut_probability=float(row["make_cut_probability"]),
        made_cut_score_mean=float(row["made_cut_score_mean"]),
        made_cut_score_sd=float(row["made_cut_score_sd"]),
        cut_rounds_score_mean=float(row["cut_rounds_score_mean"]),
        cut_rounds_score_sd=float(row["cut_rounds_score_sd"]),
        inputs_hash="",
    )
    _validate_anchor(anchor)
    return DataGolfScoreAnchor(
        datagolf_player_id=anchor.datagolf_player_id,
        player_name=anchor.player_name,
        datagolf_rank=anchor.datagolf_rank,
        make_cut_probability=anchor.make_cut_probability,
        made_cut_score_mean=anchor.made_cut_score_mean,
        made_cut_score_sd=anchor.made_cut_score_sd,
        cut_rounds_score_mean=anchor.cut_rounds_score_mean,
        cut_rounds_score_sd=anchor.cut_rounds_score_sd,
        inputs_hash=stable_hash(row),
    )


def splash_scoring_config_from_rules(
    *,
    tournament_rounds: int = 4,
    cut_rounds_played: int = 2,
    missed_round_penalty_points: float = 8.0,
    cut_probability_prior_strength: float = 80.0,
) -> SplashScoringConfig:
    """Build the scoring transform used for total-strokes Splash contests."""
    config = SplashScoringConfig(
        tournament_rounds=tournament_rounds,
        cut_rounds_played=cut_rounds_played,
        missed_round_penalty_points=missed_round_penalty_points,
        cut_probability_prior_strength=cut_probability_prior_strength,
        inputs_hash="",
    )
    _validate_config(config)
    return SplashScoringConfig(
        tournament_rounds=config.tournament_rounds,
        cut_rounds_played=config.cut_rounds_played,
        missed_round_penalty_points=config.missed_round_penalty_points,
        cut_probability_prior_strength=config.cut_probability_prior_strength,
        inputs_hash=stable_hash(
            {
                "tournament_rounds": tournament_rounds,
                "cut_rounds_played": cut_rounds_played,
                "missed_round_penalty_points": missed_round_penalty_points,
                "cut_probability_prior_strength": cut_probability_prior_strength,
            }
        ),
    )


def simulate_player_score_distributions(
    mappings: tuple[SplashPlayerMapping, ...],
    datagolf_anchors: tuple[DataGolfScoreAnchor, ...],
    scoring_config: SplashScoringConfig,
    *,
    simulations: int,
    seed: int,
) -> tuple[SplashPlayerScoreDistribution, ...]:
    """Simulate posterior predictive Splash score distributions for mapped players.

    DataGolf remains the anchor: make-cut probability and score moments come
    from DataGolf rows. The simulator only adds posterior uncertainty around
    those anchors and applies the Splash missed-round penalty mixture.
    """
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    _validate_config(scoring_config)

    anchors_by_id = {anchor.datagolf_player_id: anchor for anchor in datagolf_anchors}
    missing_anchor_ids = [
        mapping.datagolf_player_id
        for mapping in mappings
        if mapping.datagolf_player_id not in anchors_by_id
    ]
    if missing_anchor_ids:
        raise ValueError(f"Missing DataGolf score anchors: {sorted(missing_anchor_ids)}")

    rng = random.Random(seed)
    distributions = []
    for mapping in mappings:
        anchor = anchors_by_id[mapping.datagolf_player_id]
        _validate_anchor(anchor)
        samples, make_cut_flags, missed_rounds = _simulate_one_player(
            anchor,
            scoring_config,
            simulations=simulations,
            rng=rng,
        )
        sample_hash = stable_hash(
            {
                "model_version": MODEL_VERSION,
                "mapping": mapping,
                "anchor": anchor,
                "scoring_config": scoring_config,
                "simulations": simulations,
                "seed": seed,
            }
        )
        distributions.append(
            SplashPlayerScoreDistribution(
                splash_player_id=mapping.splash_player_id,
                splash_player_name=mapping.splash_player_name,
                datagolf_player_id=mapping.datagolf_player_id,
                datagolf_player_name=mapping.datagolf_player_name,
                simulations=simulations,
                score_samples=tuple(round(score, 4) for score in samples),
                mean_score=round(fmean(samples), 4),
                sd_score=round(_sample_sd(samples), 4),
                p10_score=round(_quantile(samples, 0.10), 4),
                p50_score=round(_quantile(samples, 0.50), 4),
                p90_score=round(_quantile(samples, 0.90), 4),
                simulated_make_cut_rate=round(fmean(make_cut_flags), 4),
                simulated_missed_rounds_mean=round(fmean(missed_rounds), 4),
                model_version=MODEL_VERSION,
                inputs_hash=sample_hash,
            )
        )
    return tuple(distributions)


def score_distributions_to_records(
    distributions: tuple[SplashPlayerScoreDistribution, ...],
) -> list[dict[str, Any]]:
    """Return JSON-ready score distribution records with provenance."""
    return [
        {
            "splash_player_id": distribution.splash_player_id,
            "splash_player_name": distribution.splash_player_name,
            "datagolf_player_id": distribution.datagolf_player_id,
            "datagolf_player_name": distribution.datagolf_player_name,
            "simulations": distribution.simulations,
            "score_samples": list(distribution.score_samples),
            "summary": {
                "mean_score": distribution.mean_score,
                "sd_score": distribution.sd_score,
                "p10_score": distribution.p10_score,
                "p50_score": distribution.p50_score,
                "p90_score": distribution.p90_score,
                "simulated_make_cut_rate": distribution.simulated_make_cut_rate,
                "simulated_missed_rounds_mean": distribution.simulated_missed_rounds_mean,
            },
            "provenance": {
                "model_version": distribution.model_version,
                "inputs_hash": distribution.inputs_hash,
            },
        }
        for distribution in distributions
    ]


def _simulate_one_player(
    anchor: DataGolfScoreAnchor,
    scoring_config: SplashScoringConfig,
    *,
    simulations: int,
    rng: random.Random,
) -> tuple[list[float], list[float], list[float]]:
    alpha = anchor.make_cut_probability * scoring_config.cut_probability_prior_strength
    beta = (1.0 - anchor.make_cut_probability) * scoring_config.cut_probability_prior_strength
    missed_round_count = scoring_config.tournament_rounds - scoring_config.cut_rounds_played
    missed_round_penalty = missed_round_count * scoring_config.missed_round_penalty_points

    samples: list[float] = []
    make_cut_flags: list[float] = []
    missed_rounds: list[float] = []
    for _ in range(simulations):
        posterior_make_cut_probability = rng.betavariate(alpha, beta)
        made_cut = rng.random() < posterior_make_cut_probability
        if made_cut:
            score = rng.gauss(anchor.made_cut_score_mean, anchor.made_cut_score_sd)
            make_cut_flags.append(1.0)
            missed_rounds.append(0.0)
        else:
            score = rng.gauss(anchor.cut_rounds_score_mean, anchor.cut_rounds_score_sd)
            score += missed_round_penalty
            make_cut_flags.append(0.0)
            missed_rounds.append(float(missed_round_count))
        samples.append(score)
    return samples, make_cut_flags, missed_rounds


def _validate_anchor(anchor: DataGolfScoreAnchor) -> None:
    if not 0.0 < anchor.make_cut_probability < 1.0:
        raise ValueError("make_cut_probability must be between 0 and 1")
    if anchor.made_cut_score_sd <= 0.0:
        raise ValueError("made_cut_score_sd must be positive")
    if anchor.cut_rounds_score_sd <= 0.0:
        raise ValueError("cut_rounds_score_sd must be positive")


def _validate_config(config: SplashScoringConfig) -> None:
    if config.tournament_rounds <= 0:
        raise ValueError("tournament_rounds must be positive")
    if not 0 < config.cut_rounds_played < config.tournament_rounds:
        raise ValueError("cut_rounds_played must be between 0 and tournament_rounds")
    if config.missed_round_penalty_points < 0.0:
        raise ValueError("missed_round_penalty_points must be non-negative")
    if config.cut_probability_prior_strength <= 0.0:
        raise ValueError("cut_probability_prior_strength must be positive")


def _sample_sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = fmean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[int(index)]
    weight = index - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight
