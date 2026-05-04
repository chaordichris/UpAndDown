"""P&L attribution for settled paper trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.normalization.odds import american_to_decimal
from src.storage.hashing import artifact_hash
from src.storage.models import BetAttribution, BetCandidate, BetOutcome, BetTicket, PlacedBet


@dataclass(frozen=True)
class AttributionResult:
    """Four-way P&L decomposition for one settled bet."""

    bet_id: int
    model_alpha: float
    execution_drift: float
    sizing_alpha: float
    variance: float
    realized_profit_loss: float
    flat_stake: float
    inputs_hash: str
    created_at: datetime


def compute_attribution(
    *,
    placed_bet: PlacedBet,
    ticket: BetTicket,
    candidate: BetCandidate,
    outcome: BetOutcome,
    flat_stake: float | None = None,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> AttributionResult:
    """Decompose realized P&L into model, execution, sizing, and variance.

    The MVP contract uses candidate edge as the expected model contribution.
    Execution drift is the raw-strategy P&L difference between the obtained
    line and the recommended line at the actual stake. Sizing alpha compares
    actual stake to a flat-stake baseline. Variance is the residual, so promos
    stay out of the model/execution attribution.
    """
    if ticket.proposed_american_odds is None:
        raise ValueError("Ticket is missing proposed American odds.")
    baseline_stake = placed_bet.actual_stake if flat_stake is None else flat_stake
    if baseline_stake < 0:
        raise ValueError("flat_stake must be non-negative.")

    strategy_profit_loss = outcome.profit_loss_raw
    if strategy_profit_loss is None:
        strategy_profit_loss = outcome.profit_loss
    realized = round(strategy_profit_loss, 2)
    recommended_line_pnl = _profit_loss(
        result=outcome.result,
        stake=placed_bet.actual_stake,
        american_odds=ticket.proposed_american_odds,
    )
    actual_line_pnl = _profit_loss(
        result=outcome.result,
        stake=placed_bet.actual_stake,
        american_odds=placed_bet.actual_american_odds,
    )
    model_alpha = round(candidate.edge_pct * baseline_stake, 2)
    sizing_alpha = round(candidate.edge_pct * (placed_bet.actual_stake - baseline_stake), 2)
    execution_drift = round(actual_line_pnl - recommended_line_pnl, 2)
    variance = round(realized - model_alpha - execution_drift - sizing_alpha, 2)
    created = created_at or datetime.now(UTC)
    inputs_hash = artifact_hash(
        artifact_type="bet_attribution",
        inputs={
            "bet_id": placed_bet.bet_id,
            "placed_hash": placed_bet.inputs_hash,
            "ticket_hash": ticket.inputs_hash,
            "candidate_hash": candidate.inputs_hash,
            "outcome_hash": outcome.inputs_hash,
            "flat_stake": baseline_stake,
            "model_alpha": model_alpha,
            "execution_drift": execution_drift,
            "sizing_alpha": sizing_alpha,
            "variance": variance,
            "realized_profit_loss": realized,
        },
        code_version=code_version,
    )

    return AttributionResult(
        bet_id=placed_bet.bet_id,
        model_alpha=model_alpha,
        execution_drift=execution_drift,
        sizing_alpha=sizing_alpha,
        variance=variance,
        realized_profit_loss=realized,
        flat_stake=baseline_stake,
        inputs_hash=inputs_hash,
        created_at=created,
    )


def persist_attribution(
    session: Session,
    attribution: AttributionResult,
) -> BetAttribution:
    """Insert an attribution row for one settled bet."""
    row = BetAttribution(
        bet_id=attribution.bet_id,
        model_alpha=attribution.model_alpha,
        execution_drift=attribution.execution_drift,
        sizing_alpha=attribution.sizing_alpha,
        variance=attribution.variance,
        realized_profit_loss=attribution.realized_profit_loss,
        flat_stake=attribution.flat_stake,
        inputs_hash=attribution.inputs_hash,
        created_at=attribution.created_at,
    )
    session.add(row)
    session.flush()
    return row


def record_attribution_for_bet_row(
    session: Session,
    placed_bet: PlacedBet,
    ticket: BetTicket,
    candidate: BetCandidate,
    outcome: BetOutcome,
    *,
    flat_stake: float | None = None,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> BetAttribution:
    """Compute and persist attribution from stored paper-trade rows."""
    if _attribution_exists(session, placed_bet.bet_id):
        raise ValueError(f"Bet {placed_bet.bet_id} already has attribution.")
    attribution = compute_attribution(
        placed_bet=placed_bet,
        ticket=ticket,
        candidate=candidate,
        outcome=outcome,
        flat_stake=flat_stake,
        created_at=created_at,
        code_version=code_version,
    )
    return persist_attribution(session, attribution)


def _attribution_exists(session: Session, bet_id: int) -> bool:
    return session.query(BetAttribution).filter_by(bet_id=bet_id).first() is not None


def _profit_loss(*, result: str, stake: float, american_odds: int) -> float:
    if result == "win":
        return round(stake * (american_to_decimal(american_odds) - 1.0), 2)
    if result == "loss":
        return round(-stake, 2)
    if result in {"push", "void"}:
        return 0.0
    if result == "dead_heat":
        return round((stake / 2.0) * (american_to_decimal(american_odds) - 1.0), 2)
    raise ValueError(f"Unknown settlement result: {result}")
