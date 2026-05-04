from __future__ import annotations

import pytest

from src.monitoring.attribution import compute_attribution
from src.storage.models import BetCandidate, BetOutcome, BetTicket, PlacedBet


def test_attribution_components_reconcile_to_realized_pnl() -> None:
    result = compute_attribution(
        placed_bet=_placed(actual_american_odds=-105, actual_stake=100.0),
        ticket=_ticket(proposed_american_odds=-110),
        candidate=_candidate(edge_pct=0.05),
        outcome=_outcome(result="win", profit_loss=95.24),
        flat_stake=100.0,
        code_version="test",
    )

    total = result.model_alpha + result.execution_drift + result.sizing_alpha + result.variance

    assert result.model_alpha == 5.0
    assert result.execution_drift == 4.33
    assert result.sizing_alpha == 0.0
    assert total == pytest.approx(result.realized_profit_loss)


def test_attribution_has_zero_execution_drift_at_recommended_line() -> None:
    result = compute_attribution(
        placed_bet=_placed(actual_american_odds=-110, actual_stake=100.0),
        ticket=_ticket(proposed_american_odds=-110),
        candidate=_candidate(edge_pct=0.05),
        outcome=_outcome(result="win", profit_loss=90.91),
        flat_stake=100.0,
        code_version="test",
    )

    assert result.execution_drift == 0.0


def test_attribution_tracks_sizing_alpha_against_flat_stake() -> None:
    result = compute_attribution(
        placed_bet=_placed(actual_american_odds=-110, actual_stake=125.0),
        ticket=_ticket(proposed_american_odds=-110),
        candidate=_candidate(edge_pct=0.05),
        outcome=_outcome(result="loss", profit_loss=-125.0),
        flat_stake=100.0,
        code_version="test",
    )

    assert result.model_alpha == 5.0
    assert result.sizing_alpha == 1.25
    assert result.execution_drift == 0.0
    assert result.variance == -131.25


def test_attribution_uses_raw_strategy_pnl_for_promo_bets() -> None:
    result = compute_attribution(
        placed_bet=_placed(actual_american_odds=-105, actual_stake=100.0),
        ticket=_ticket(proposed_american_odds=-105),
        candidate=_candidate(edge_pct=0.05),
        outcome=_outcome(result="win", profit_loss=142.86, profit_loss_raw=95.24),
        flat_stake=100.0,
        code_version="test",
    )

    total = result.model_alpha + result.execution_drift + result.sizing_alpha + result.variance
    assert total == pytest.approx(95.24)
    assert result.realized_profit_loss == 95.24


def _placed(*, actual_american_odds: int, actual_stake: float) -> PlacedBet:
    return PlacedBet(
        bet_id=1,
        ticket_id=1,
        book="dk",
        actual_american_odds=actual_american_odds,
        actual_stake=actual_stake,
        inputs_hash="placed-hash",
    )


def _ticket(*, proposed_american_odds: int) -> BetTicket:
    return BetTicket(
        ticket_id=1,
        candidate_id=1,
        sleeve="core",
        proposed_stake=100.0,
        proposed_american_odds=proposed_american_odds,
        sizing_method="fractional_kelly",
        approved=True,
        inputs_hash="ticket-hash",
    )


def _candidate(*, edge_pct: float) -> BetCandidate:
    return BetCandidate(
        candidate_id=1,
        tournament_id=1,
        market_type="matchup_2ball",
        side="player",
        player_id_1=1,
        book="dk",
        fair_prob=0.56,
        book_prob=0.51,
        edge_pct=edge_pct,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash="candidate-hash",
    )


def _outcome(*, result: str, profit_loss: float, profit_loss_raw: float | None = None) -> BetOutcome:
    return BetOutcome(
        outcome_id=1,
        bet_id=1,
        result=result,
        payout=profit_loss + 100.0,
        profit_loss=profit_loss,
        profit_loss_raw=profit_loss if profit_loss_raw is None else profit_loss_raw,
        inputs_hash="outcome-hash",
    )
