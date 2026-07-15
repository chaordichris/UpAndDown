"""Typed Splash fantasy contest domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SplashScoringConfig:
    tournament_rounds: int
    cut_rounds_played: int
    missed_round_penalty_points: float
    cut_probability_prior_strength: float
    inputs_hash: str


@dataclass(frozen=True)
class DataGolfScoreAnchor:
    datagolf_player_id: str
    player_name: str
    datagolf_rank: int
    make_cut_probability: float
    made_cut_score_mean: float
    made_cut_score_sd: float
    cut_rounds_score_mean: float
    cut_rounds_score_sd: float
    inputs_hash: str


@dataclass(frozen=True)
class SplashPlayerScoreDistribution:
    splash_player_id: str
    splash_player_name: str
    datagolf_player_id: str
    datagolf_player_name: str
    simulations: int
    score_samples: tuple[float, ...]
    mean_score: float
    sd_score: float
    p10_score: float
    p50_score: float
    p90_score: float
    simulated_make_cut_rate: float
    simulated_missed_rounds_mean: float
    model_version: str
    inputs_hash: str


@dataclass(frozen=True)
class SplashLineup:
    lineup_id: str
    player_ids: tuple[str, ...]
    entry_fee_cents: int
    inputs_hash: str


@dataclass(frozen=True)
class SplashLineupSimulationResult:
    lineup_id: str
    simulations: int
    expected_payout_cents: float
    roi: float
    cash_probability: float
    top_10_probability: float
    win_probability: float
    profit_variance_cents: float
    drawdown_contribution_cents: float
    mean_score: float
    inputs_hash: str


@dataclass(frozen=True)
class SplashOpponentLineupAssumptions:
    public_contest_size: int
    seed: int
    datagolf_rank_weight: float = 1.0
    tier_position_weight: float = 1.0
    external_ownership_by_player_id: dict[str, float] = field(default_factory=dict)
    ownership_concentration: float = 1.0
    ownership_uncertainty_sd: float = 0.0
    sensitivity_concentration_multipliers: tuple[float, ...] = (0.75, 1.0, 1.25)
    sensitivity_roi_threshold: float = 0.1
    inputs_hash: str = ""


@dataclass(frozen=True)
class SplashLineupDuplicationEstimate:
    lineup_key: tuple[str, ...]
    lineup_ids: tuple[str, ...]
    duplicate_count: int
    inputs_hash: str


@dataclass(frozen=True)
class SplashOpponentLineupPool:
    lineups: tuple[SplashLineup, ...]
    duplicate_estimates: tuple[SplashLineupDuplicationEstimate, ...]
    max_duplicate_count: int
    duplicated_entry_count: int
    duplicated_entry_share: float
    assumption_log: dict[str, Any]
    inputs_hash: str


@dataclass(frozen=True)
class SplashOpponentSimulationResult:
    target_results: tuple[SplashLineupSimulationResult, ...]
    opponent_pool: SplashOpponentLineupPool
    target_duplication_counts: dict[str, int]
    assumption_log: dict[str, Any]
    inputs_hash: str


@dataclass(frozen=True)
class SplashOwnershipSensitivityScenario:
    label: str
    ownership_concentration: float
    result: SplashOpponentSimulationResult
    inputs_hash: str


@dataclass(frozen=True)
class SplashOwnershipSensitivityReport:
    scenarios: tuple[SplashOwnershipSensitivityScenario, ...]
    roi_range_by_lineup: dict[str, float]
    expected_payout_range_cents_by_lineup: dict[str, float]
    ev_dependency_flags: dict[str, bool]
    sensitivity_roi_threshold: float
    inputs_hash: str


@dataclass(frozen=True)
class SplashPortfolioOptimizationConfig:
    portfolio_name: str
    max_entries: int
    bankroll_cents: int
    minimum_marginal_ev_cents: float
    max_golfer_exposure_count: int
    max_shared_players_between_lineups: int
    half_kelly_fraction: float = 0.5
    inputs_hash: str = ""


@dataclass(frozen=True)
class SplashPortfolioCandidate:
    lineup: SplashLineup
    simulation_result: SplashLineupSimulationResult
    expected_profit_cents: float
    expected_log_growth: float
    half_kelly_adjusted_ev_cents: float
    target_duplication_count: int
    inputs_hash: str


@dataclass(frozen=True)
class SplashPortfolioEntry:
    rank: int
    lineup: SplashLineup
    candidate: SplashPortfolioCandidate
    marginal_adjusted_ev_cents: float
    inputs_hash: str


@dataclass(frozen=True)
class SplashLineupPortfolio:
    portfolio_name: str
    entries: tuple[SplashPortfolioEntry, ...]
    total_entry_fee_cents: int
    expected_payout_cents: float
    expected_profit_cents: float
    expected_roi: float
    expected_log_growth: float
    half_kelly_adjusted_ev_cents: float
    golfer_exposures: dict[str, int]
    assumption_log: dict[str, Any]
    hard_review_items: tuple[str, ...]
    inputs_hash: str


@dataclass(frozen=True)
class SplashFantasyReportConfig:
    bankroll_cents: int
    half_kelly_fraction: float
    minimum_portfolio_ev_cents: float
    minimum_ev_to_sd_ratio: float
    max_ror_probability: float
    ror_simulations: int
    ror_seed: int
    paper_only_drawdown_threshold: float = 0.25
    halt_drawdown_threshold: float = 0.35
    inputs_hash: str = ""


@dataclass(frozen=True)
class SplashManualLineup:
    entry_number: int
    lineup_id: str
    player_ids: tuple[str, ...]
    player_names: tuple[str, ...]
    marginal_ev_cents: float
    expected_profit_cents: float
    inputs_hash: str


@dataclass(frozen=True)
class SplashFantasyReport:
    portfolio_name: str
    recommendation: str
    no_play_reasons: tuple[str, ...]
    recommended_entries: int
    total_stake_cents: int
    half_kelly_fraction_used: float
    marginal_ev_by_lineup_cents: tuple[tuple[str, float], ...]
    portfolio_ev_cents: float
    portfolio_variance_cents: float
    portfolio_sd_cents: float
    ev_to_sd_ratio: float | None
    ror_estimate: dict[str, Any]
    manual_lineups: tuple[SplashManualLineup, ...]
    assumption_log: dict[str, Any]
    inputs_hash: str


@dataclass(frozen=True)
class SplashPayout:
    label: str
    start_rank: int
    end_rank: int
    amount_cents: int
    order: int
    inputs_hash: str


@dataclass(frozen=True)
class SplashSlate:
    splash_id: str
    name: str
    status: str
    start_date: datetime | None
    end_date: datetime | None
    sport: str | None
    league: str | None
    purse_cents: int | None
    inputs_hash: str


@dataclass(frozen=True)
class SplashRosterRule:
    expected_picks_count: int
    number_of_tiers: int
    number_per_tier: int
    drop_worst_count: int
    metric_name: str | None
    score_type: str | None
    description: str | None
    inputs_hash: str


@dataclass(frozen=True)
class SplashScoringRule:
    description: str
    points: float | None
    inputs_hash: str


@dataclass(frozen=True)
class SplashPlayer:
    splash_player_id: str
    slate_player_id: str
    slate_id: str
    name: str
    tier_id: int | None
    datagolf_rank: int | None
    world_rank: int | None
    scoring_avg: float | None
    country: str | None
    is_selectable: bool
    attributes: dict[str, Any] = field(repr=False)
    inputs_hash: str = ""


@dataclass(frozen=True)
class SplashPlayerMapping:
    splash_player_id: str
    splash_player_name: str
    splash_datagolf_rank: int
    datagolf_player_id: str
    datagolf_player_name: str
    datagolf_rank: int
    inputs_hash: str


@dataclass(frozen=True)
class SplashPlayerMappingReviewItem:
    splash_player_id: str
    splash_player_name: str
    splash_datagolf_rank: int | None
    reason: str
    candidates: tuple[str, ...]
    inputs_hash: str


@dataclass(frozen=True)
class SplashTier:
    tier_id: int
    number_per_tier: int
    metric_name: str | None
    max_players: int | None
    players: tuple[SplashPlayer, ...]
    inputs_hash: str


@dataclass(frozen=True)
class SplashContestPlayerPool:
    contest_id: str
    slate_id: str
    tiers: tuple[SplashTier, ...]
    player_mappings: tuple[SplashPlayerMapping, ...]
    review_items: tuple[SplashPlayerMappingReviewItem, ...]
    inputs_hash: str


@dataclass(frozen=True)
class SplashContest:
    splash_id: str
    name: str
    contest_type: str
    status: str
    entry_fee_cents: int
    entry_fee_dollars: float
    prize_pool_cents: int
    prize_pool_dollars: float
    filled_entries: int | None
    max_entries: int | None
    max_entries_per_user: int | None
    payout_ladder: tuple[SplashPayout, ...]
    scoring_rules: tuple[SplashScoringRule, ...]
    roster_rule: SplashRosterRule
    slates: tuple[SplashSlate, ...]
    tiers: tuple[SplashTier, ...]
    inputs_hash: str
