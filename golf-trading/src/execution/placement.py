"""Manual placement logging for paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.execution.tickets import BetTicketDraft
from src.storage.hashing import artifact_hash


@dataclass(frozen=True)
class PlacementLog:
    """The human-entered placement result for a recommended ticket."""

    placement_ref: str
    ticket_ref: str
    status: str
    book_id: str
    recommended_american_odds: int
    actual_american_odds: int | None
    recommended_stake: float
    actual_stake: float
    placed_at: datetime
    rejection_reason: str | None
    notes: str | None
    placement_method: str
    inputs_hash: str


def log_placement(
    ticket: BetTicketDraft,
    *,
    actual_american_odds: int | None = None,
    actual_stake: float | None = None,
    placed_at: datetime | None = None,
    rejected: bool = False,
    rejection_reason: str | None = None,
    notes: str | None = None,
    placement_method: str = "manual",
    code_version: str | None = None,
) -> PlacementLog:
    """Record whether and how a manual paper-trade ticket was placed."""
    if rejected:
        status = "rejected"
        resolved_actual_odds = None
        resolved_stake = 0.0
        resolved_reason = rejection_reason or "Manual placement rejected."
    else:
        if not ticket.approved:
            raise ValueError("Cannot place a ticket that failed risk approval.")
        status = "placed"
        resolved_actual_odds = actual_american_odds or ticket.recommended_american_odds
        resolved_stake = ticket.recommended_stake if actual_stake is None else actual_stake
        resolved_reason = None

    placed = placed_at or datetime.now(UTC)
    inputs_hash = artifact_hash(
        artifact_type="placement_log",
        inputs={
            "ticket_hash": ticket.inputs_hash,
            "actual_american_odds": resolved_actual_odds,
            "actual_stake": resolved_stake,
            "status": status,
        },
        config={"placement_method": placement_method},
        code_version=code_version,
    )

    return PlacementLog(
        placement_ref=f"PLC-{inputs_hash[:12]}",
        ticket_ref=ticket.ticket_ref,
        status=status,
        book_id=ticket.book_id,
        recommended_american_odds=ticket.recommended_american_odds,
        actual_american_odds=resolved_actual_odds,
        recommended_stake=ticket.recommended_stake,
        actual_stake=resolved_stake,
        placed_at=placed,
        rejection_reason=resolved_reason,
        notes=notes,
        placement_method=placement_method,
        inputs_hash=inputs_hash,
    )
