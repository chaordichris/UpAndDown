"""Closing-line-value calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.execution.placement import PlacementLog
from src.execution.tickets import BetTicketDraft
from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.storage.hashing import artifact_hash


@dataclass(frozen=True)
class CLVResult:
    """CLV snapshot for one placed bet."""

    clv_ref: str
    placement_ref: str
    closing_american_odds: int
    placement_implied_prob: float
    closing_implied_prob: float
    clv_raw: float
    clv_model: float
    captured_at: datetime
    inputs_hash: str


def compute_clv(
    ticket: BetTicketDraft,
    placement: PlacementLog,
    *,
    closing_american_odds: int,
    captured_at: datetime | None = None,
    code_version: str | None = None,
) -> CLVResult:
    """Compute raw and model CLV for a placed ticket."""
    if placement.status != "placed" or placement.actual_american_odds is None:
        raise ValueError("CLV requires a placed bet with actual odds.")

    placement_prob = decimal_to_implied(american_to_decimal(placement.actual_american_odds))
    closing_prob = decimal_to_implied(american_to_decimal(closing_american_odds))
    captured = captured_at or datetime.now(UTC)
    inputs_hash = artifact_hash(
        artifact_type="clv_snapshot",
        inputs={
            "ticket_hash": ticket.inputs_hash,
            "placement_hash": placement.inputs_hash,
            "closing_american_odds": closing_american_odds,
        },
        code_version=code_version,
    )

    return CLVResult(
        clv_ref=f"CLV-{inputs_hash[:12]}",
        placement_ref=placement.placement_ref,
        closing_american_odds=closing_american_odds,
        placement_implied_prob=placement_prob,
        closing_implied_prob=closing_prob,
        clv_raw=closing_prob - placement_prob,
        clv_model=ticket.fair_prob - closing_prob,
        captured_at=captured,
        inputs_hash=inputs_hash,
    )
