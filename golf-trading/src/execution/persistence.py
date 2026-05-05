"""Persistence adapters for paper-trade execution artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from src.execution.promos import normalize_bet_class, settlement_amounts
from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.storage.hashing import artifact_hash
from src.storage.models import BetCandidate, BetOutcome, BetTicket, CLVSnapshot, PlacedBet

if TYPE_CHECKING:
    from src.execution.placement import PlacementLog
    from src.execution.settlement import SettlementLog
    from src.execution.tickets import BetTicketDraft
    from src.monitoring.clv import CLVResult


def persist_ticket(
    session: Session,
    ticket: BetTicketDraft,
    *,
    candidate_id: int,
) -> BetTicket:
    """Insert a generated paper-trade ticket."""
    row = BetTicket(
        candidate_id=candidate_id,
        sleeve=ticket.sleeve,
        proposed_stake=ticket.recommended_stake,
        proposed_american_odds=ticket.recommended_american_odds,
        kelly_fraction_used=ticket.kelly_fraction_used,
        sizing_method=ticket.sizing_method,
        approved=ticket.approved,
        rejection_reason=ticket.rejection_reason,
        inputs_hash=ticket.inputs_hash,
        created_at=ticket.created_at,
    )
    session.add(row)
    session.flush()
    return row


def persist_placement(
    session: Session,
    placement: PlacementLog,
    *,
    ticket_id: int,
    bet_class: str = "STANDARD",
    boost_terms_json: str | None = None,
) -> PlacedBet:
    """Insert a manually placed bet.

    Rejected/unfilled placement attempts are represented by the ticket's
    rejection fields for now; only actual placed bets enter `placed_bets`.
    """
    if placement.status != "placed" or placement.actual_american_odds is None:
        raise ValueError("Only placed bets can be persisted to placed_bets.")
    resolved_class = normalize_bet_class(bet_class)

    row = PlacedBet(
        ticket_id=ticket_id,
        book=placement.book_id,
        actual_american_odds=placement.actual_american_odds,
        actual_stake=placement.actual_stake,
        placed_at=placement.placed_at,
        notes=placement.notes,
        placement_method=placement.placement_method,
        bet_class=resolved_class,
        boost_terms_json=boost_terms_json,
        inputs_hash=placement.inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def persist_settlement(
    session: Session,
    settlement: SettlementLog,
    *,
    bet_id: int,
) -> BetOutcome:
    """Insert the final settlement for a placed bet."""
    row = BetOutcome(
        bet_id=bet_id,
        result=settlement.result,
        payout=settlement.payout,
        profit_loss=settlement.profit_loss,
        payout_raw=settlement.payout_raw,
        profit_loss_raw=settlement.profit_loss_raw,
        payout_realized=settlement.payout_realized,
        profit_loss_realized=settlement.profit_loss_realized,
        settled_at=settlement.settled_at,
        settlement_notes=settlement.notes,
        inputs_hash=settlement.inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def persist_clv(
    session: Session,
    clv: CLVResult,
    *,
    bet_id: int,
) -> CLVSnapshot:
    """Insert a CLV snapshot for a placed bet."""
    row = CLVSnapshot(
        bet_id=bet_id,
        closing_american_odds=clv.closing_american_odds,
        closing_implied_prob=clv.closing_implied_prob,
        placement_implied_prob=clv.placement_implied_prob,
        clv_raw=clv.clv_raw,
        clv_model=clv.clv_model,
        captured_at=clv.captured_at,
        inputs_hash=clv.inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def place_ticket_row(
    session: Session,
    ticket: BetTicket,
    candidate: BetCandidate,
    *,
    actual_american_odds: int | None = None,
    actual_stake: float | None = None,
    placed_at: datetime | None = None,
    notes: str | None = None,
    placement_method: str = "manual",
    bet_class: str = "STANDARD",
    boost_terms_json: str | None = None,
    code_version: str | None = None,
) -> PlacedBet:
    """Create a placed bet directly from persisted ticket/candidate rows."""
    if not ticket.approved:
        raise ValueError("Cannot place a ticket that failed risk approval.")
    if ticket.proposed_american_odds is None:
        raise ValueError("Ticket is missing proposed American odds.")
    if _placed_bet_exists(session, ticket.ticket_id):
        raise ValueError(f"Ticket {ticket.ticket_id} already has a placed bet.")

    resolved_odds = actual_american_odds or ticket.proposed_american_odds
    resolved_stake = ticket.proposed_stake if actual_stake is None else actual_stake
    resolved_class = normalize_bet_class(bet_class)
    placed = placed_at or datetime.now(UTC)
    inputs_hash = artifact_hash(
        artifact_type="placed_bet",
        inputs={
            "ticket_id": ticket.ticket_id,
            "ticket_hash": ticket.inputs_hash,
            "candidate_hash": candidate.inputs_hash,
            "actual_american_odds": resolved_odds,
            "actual_stake": resolved_stake,
            "bet_class": resolved_class,
            "boost_terms_json": boost_terms_json,
        },
        config={"placement_method": placement_method},
        code_version=code_version,
    )

    row = PlacedBet(
        ticket_id=ticket.ticket_id,
        book=candidate.book,
        actual_american_odds=resolved_odds,
        actual_stake=resolved_stake,
        placed_at=placed,
        notes=notes,
        placement_method=placement_method,
        bet_class=resolved_class,
        boost_terms_json=boost_terms_json,
        inputs_hash=inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def settle_bet_row(
    session: Session,
    placed_bet: PlacedBet,
    *,
    result: str,
    settled_at: datetime | None = None,
    notes: str | None = None,
    code_version: str | None = None,
) -> BetOutcome:
    """Create a settlement row from a persisted placed bet."""
    if _outcome_exists(session, placed_bet.bet_id):
        raise ValueError(f"Bet {placed_bet.bet_id} already has a settlement.")

    amounts = settlement_amounts(
        result=result,
        stake=placed_bet.actual_stake,
        american_odds=placed_bet.actual_american_odds,
        bet_class=placed_bet.bet_class,
        boost_terms_json=placed_bet.boost_terms_json,
    )
    inputs_hash = artifact_hash(
        artifact_type="bet_outcome",
        inputs={
            "bet_id": placed_bet.bet_id,
            "placed_hash": placed_bet.inputs_hash,
            "result": result,
            "payout_raw": amounts["payout_raw"],
            "profit_loss_raw": amounts["profit_loss_raw"],
            "payout_realized": amounts["payout_realized"],
            "profit_loss_realized": amounts["profit_loss_realized"],
        },
        code_version=code_version,
    )

    row = BetOutcome(
        bet_id=placed_bet.bet_id,
        result=result,
        payout=amounts["payout_realized"],
        profit_loss=amounts["profit_loss_realized"],
        payout_raw=amounts["payout_raw"],
        profit_loss_raw=amounts["profit_loss_raw"],
        payout_realized=amounts["payout_realized"],
        profit_loss_realized=amounts["profit_loss_realized"],
        settled_at=settled_at or datetime.now(UTC),
        settlement_notes=notes,
        inputs_hash=inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def record_clv_for_bet_row(
    session: Session,
    placed_bet: PlacedBet,
    ticket: BetTicket,
    candidate: BetCandidate,
    *,
    closing_american_odds: int,
    captured_at: datetime | None = None,
    code_version: str | None = None,
) -> CLVSnapshot:
    """Create a CLV snapshot from persisted bet/ticket/candidate rows."""
    if _clv_exists(session, placed_bet.bet_id):
        raise ValueError(f"Bet {placed_bet.bet_id} already has a CLV snapshot.")

    placement_prob = decimal_to_implied(american_to_decimal(placed_bet.actual_american_odds))
    closing_prob = decimal_to_implied(american_to_decimal(closing_american_odds))
    inputs_hash = artifact_hash(
        artifact_type="clv_snapshot",
        inputs={
            "bet_id": placed_bet.bet_id,
            "placed_hash": placed_bet.inputs_hash,
            "ticket_hash": ticket.inputs_hash,
            "candidate_hash": candidate.inputs_hash,
            "closing_american_odds": closing_american_odds,
        },
        code_version=code_version,
    )

    row = CLVSnapshot(
        bet_id=placed_bet.bet_id,
        closing_american_odds=closing_american_odds,
        closing_implied_prob=closing_prob,
        placement_implied_prob=placement_prob,
        clv_raw=closing_prob - placement_prob,
        clv_model=candidate.fair_prob - closing_prob,
        captured_at=captured_at or datetime.now(UTC),
        inputs_hash=inputs_hash,
    )
    session.add(row)
    session.flush()
    return row


def _placed_bet_exists(session: Session, ticket_id: int) -> bool:
    return session.query(PlacedBet).filter_by(ticket_id=ticket_id).first() is not None


def _outcome_exists(session: Session, bet_id: int) -> bool:
    return session.query(BetOutcome).filter_by(bet_id=bet_id).first() is not None


def _clv_exists(session: Session, bet_id: int) -> bool:
    return session.query(CLVSnapshot).filter_by(bet_id=bet_id).first() is not None
