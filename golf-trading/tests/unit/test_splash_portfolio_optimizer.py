from __future__ import annotations

import src.fantasy.splash.portfolio_optimizer as portfolio_optimizer
from src.fantasy.splash.lineup_simulator import lineup_from_players
from src.fantasy.splash.models import (
    SplashLineupSimulationResult,
    SplashOpponentLineupAssumptions,
    SplashOpponentSimulationResult,
    SplashPortfolioOptimizationConfig,
)


def test_evaluate_lineup_candidates_batches_opponent_simulations(monkeypatch) -> None:
    calls = []

    def fake_simulate_lineup_with_generated_opponents(**kwargs):
        target_lineups = kwargs["target_lineups"]
        calls.append(tuple(lineup.lineup_id for lineup in target_lineups))
        return SplashOpponentSimulationResult(
            target_results=tuple(
                SplashLineupSimulationResult(
                    lineup_id=lineup.lineup_id,
                    simulations=10,
                    expected_payout_cents=125,
                    roi=0.25,
                    cash_probability=0.5,
                    top_10_probability=0.1,
                    win_probability=0.01,
                    profit_variance_cents=100,
                    drawdown_contribution_cents=0,
                    mean_score=0,
                    inputs_hash=f"result-{lineup.lineup_id}",
                )
                for lineup in target_lineups
            ),
            opponent_pool=None,
            target_duplication_counts={lineup.lineup_id: 1 for lineup in target_lineups},
            assumption_log={},
            inputs_hash="simulation",
        )

    monkeypatch.setattr(
        portfolio_optimizer,
        "simulate_lineup_with_generated_opponents",
        fake_simulate_lineup_with_generated_opponents,
    )
    lineups = tuple(
        lineup_from_players(
            lineup_id=f"lineup-{index}",
            player_ids=(f"p{index}",),
            entry_fee_cents=100,
        )
        for index in range(5)
    )

    candidates = portfolio_optimizer.evaluate_lineup_candidates(
        candidate_lineups=lineups,
        players_by_tier={},
        tier_requirements={},
        sampled_golfer_outcomes={},
        drop_worst_count=0,
        scoring_rules=(),
        payout_ladder=(),
        opponent_assumptions=SplashOpponentLineupAssumptions(public_contest_size=10, seed=1),
        portfolio_config=SplashPortfolioOptimizationConfig(
            portfolio_name="test",
            max_entries=5,
            bankroll_cents=10_000,
            minimum_marginal_ev_cents=0,
            max_golfer_exposure_count=5,
            max_shared_players_between_lineups=1,
        ),
        evaluation_batch_size=2,
    )

    assert [candidate.lineup.lineup_id for candidate in candidates] == [
        "lineup-0",
        "lineup-1",
        "lineup-2",
        "lineup-3",
        "lineup-4",
    ]
    assert calls == [
        ("lineup-0", "lineup-1"),
        ("lineup-2", "lineup-3"),
        ("lineup-4",),
    ]
