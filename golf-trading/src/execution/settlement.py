"""Settlement recording for placed paper trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.execution.placement import PlacementLog
from src.execution.promos import settlement_amounts
from src.storage.hashing import artifact_hash


@dataclass(frozen=True)
class SettlementLog:
    """Final settlement result for a placed bet."""

    settlement_ref: str
    placement_ref: str
    result: str
    stake: float
    payout: float
    profit_loss: float
    payout_raw: float
    profit_loss_raw: float
    payout_realized: float
    profit_loss_realized: float
    settled_at: datetime
    notes: str | None
    inputs_hash: str


def settle_placement(
    placement: PlacementLog,
    *,
    result: str,
    settled_at: datetime | None = None,
    notes: str | None = None,
    bet_class: str = "STANDARD",
    boost_terms_json: str | None = None,
    code_version: str | None = None,
) -> SettlementLog:
    """Settle a placed bet and compute payout/P&L."""
    if placement.status != "placed":
        raise ValueError("Only placed bets can be settled.")
    if placement.actual_american_odds is None:
        raise ValueError("Placed bets must have actual odds before settlement.")

    stake = placement.actual_stake
    amounts = settlement_amounts(
        result=result,
        stake=stake,
        american_odds=placement.actual_american_odds,
        bet_class=bet_class,
        boost_terms_json=boost_terms_json,
    )
    settled = settled_at or datetime.now(UTC)
    inputs_hash = artifact_hash(
        artifact_type="settlement_log",
        inputs={
            "placement_hash": placement.inputs_hash,
            "result": result,
            "bet_class": bet_class,
            "boost_terms_json": boost_terms_json,
            "payout_raw": amounts["payout_raw"],
            "profit_loss_raw": amounts["profit_loss_raw"],
            "payout_realized": amounts["payout_realized"],
            "profit_loss_realized": amounts["profit_loss_realized"],
        },
        code_version=code_version,
    )

    return SettlementLog(
        settlement_ref=f"STL-{inputs_hash[:12]}",
        placement_ref=placement.placement_ref,
        result=result,
        stake=stake,
        payout=amounts["payout_realized"],
        profit_loss=amounts["profit_loss_realized"],
        payout_raw=amounts["payout_raw"],
        profit_loss_raw=amounts["profit_loss_raw"],
        payout_realized=amounts["payout_realized"],
        profit_loss_realized=amounts["profit_loss_realized"],
        settled_at=settled,
        notes=notes,
        inputs_hash=inputs_hash,
    )
