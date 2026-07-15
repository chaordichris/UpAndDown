"""Paper-trade ticket generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.risk.edge import EdgeResult
from src.risk.sizing import SizingResult
from src.storage.hashing import artifact_hash


@dataclass(frozen=True)
class BetTicketDraft:
    """Risk-reviewed paper-trade ticket ready for manual placement."""

    ticket_ref: str
    tournament_id: str
    datagolf_id: str
    opponent_id: str | None
    market_type: str
    book_id: str
    sleeve: str
    side: str
    fair_prob: float
    book_no_vig_prob: float
    vig_removed: bool
    edge: float
    recommended_american_odds: int
    recommended_stake: float
    approved: bool
    rejection_reason: str | None
    sizing_method: str
    kelly_fraction_used: float
    created_at: datetime
    inputs_hash: str


def generate_ticket(
    edge: EdgeResult,
    sizing: SizingResult,
    *,
    tournament_id: str,
    side: str | None = None,
    sizing_method: str | None = None,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> BetTicketDraft:
    """Create a deterministic paper-trade ticket from edge and sizing output."""
    created = created_at or datetime.now(UTC)
    resolved_sizing_method = sizing_method or (
        "fixed_unit" if edge.sleeve == "convex" else "fractional_kelly"
    )
    resolved_side = side or edge.datagolf_id
    inputs_hash = artifact_hash(
        artifact_type="bet_ticket",
        inputs={"edge": edge, "sizing": sizing, "tournament_id": tournament_id, "side": resolved_side},
        config={"sizing_method": resolved_sizing_method},
        code_version=code_version,
    )
    ticket_ref = f"TKT-{inputs_hash[:12]}"

    return BetTicketDraft(
        ticket_ref=ticket_ref,
        tournament_id=tournament_id,
        datagolf_id=edge.datagolf_id,
        opponent_id=edge.opponent_id,
        market_type=edge.market_type,
        book_id=edge.book_id,
        sleeve=edge.sleeve,
        side=resolved_side,
        fair_prob=edge.fair_prob,
        book_no_vig_prob=edge.book_no_vig_prob,
        vig_removed=edge.vig_removed,
        edge=edge.edge,
        recommended_american_odds=edge.book_american_odds,
        recommended_stake=sizing.stake,
        approved=sizing.approved,
        rejection_reason=None if sizing.approved else sizing.reason,
        sizing_method=resolved_sizing_method,
        kelly_fraction_used=sizing.kelly_fraction,
        created_at=created,
        inputs_hash=inputs_hash,
    )


def render_ticket(ticket: BetTicketDraft) -> str:
    """Render a ticket for manual placement review."""
    status = "APPROVED" if ticket.approved else "REJECTED"
    opponent = f" vs {ticket.opponent_id}" if ticket.opponent_id else ""
    return "\n".join(
        [
            f"{ticket.ticket_ref} [{status}]",
            f"Tournament: {ticket.tournament_id}",
            f"Market: {ticket.market_type} - {ticket.datagolf_id}{opponent}",
            f"Book: {ticket.book_id}",
            f"Side: {ticket.side} {ticket.recommended_american_odds:+d}",
            f"Fair probability: {ticket.fair_prob:.3f}",
            (
                f"Book no-vig probability: {ticket.book_no_vig_prob:.3f}"
                if ticket.vig_removed
                else f"Book implied probability (vig NOT removed): {ticket.book_no_vig_prob:.3f}"
            ),
            f"Edge: {ticket.edge:.3f}",
            f"Stake: ${ticket.recommended_stake:.2f}",
            f"Sleeve: {ticket.sleeve}",
        ]
    )
