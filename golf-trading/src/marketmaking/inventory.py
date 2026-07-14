"""Inventory accounting: positions, cash, and P&L attribution.

P&L is decomposed into the three streams the spec requires:
- spread capture: edge vs. fair at the moment of each fill
- adverse selection: fair-value drift against the position after each fill
- inventory settlement: residual position resolving at contract settlement
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Fill, InventoryState, Side


def apply_fill(inventory: InventoryState, fill: Fill) -> None:
    """Record a fill against our quote. BID fill = we bought YES."""
    if fill.side == Side.BID:
        inventory.position += fill.size
        inventory.cash -= fill.price * fill.size
    else:
        inventory.position -= fill.size
        inventory.cash += fill.price * fill.size
    inventory.fills.append(fill)


@dataclass(frozen=True)
class PnLAttribution:
    spread_capture: float
    adverse_selection: float
    inventory_settlement: float

    @property
    def total(self) -> float:
        return self.spread_capture + self.adverse_selection + self.inventory_settlement


def attribute_pnl(
    inventory: InventoryState,
    fair_at_fill: dict[int, float],
    fair_final: float,
    settlement: float,
) -> PnLAttribution:
    """Decompose realized P&L for one settled market.

    ``fair_at_fill`` maps timestep → our fair mean when the fill happened;
    ``fair_final`` is our last fair mean before settlement; ``settlement``
    is 0.0 or 1.0. The three streams sum exactly to total realized P&L:

    - spread capture:  sign * (fair_at_fill − price)          per fill
    - adverse selection: sign * (fair_final − fair_at_fill)   per fill
    - inventory settlement: sign * (settlement − fair_final)  per fill
    """
    if settlement not in (0.0, 1.0):
        raise ValueError(f"settlement must be 0.0 or 1.0, got {settlement}")

    spread = 0.0
    adverse = 0.0
    settle_noise = 0.0
    for fill in inventory.fills:
        fair = fair_at_fill[fill.timestep]
        sign = 1 if fill.side == Side.BID else -1
        # We bought below fair / sold above fair → positive spread capture.
        spread += sign * (fair - fill.price) * fill.size
        # Fair drifting against our side after the fill = we were picked off.
        adverse += sign * (fair_final - fair) * fill.size
        # Residual gap between final fair and the realized outcome.
        settle_noise += sign * (settlement - fair_final) * fill.size

    return PnLAttribution(
        spread_capture=spread,
        adverse_selection=adverse,
        inventory_settlement=settle_noise,
    )
