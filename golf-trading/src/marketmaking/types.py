"""Interface dataclasses for the market-making pod.

Every boundary between modules is a frozen dataclass so behavior is
table-testable and provenance is serializable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BID = "bid"
    ASK = "ask"


@dataclass(frozen=True)
class MarketDef:
    """A binary contract on a golf outcome (e.g. 'Kim to win the John Deere')."""

    market_id: str
    description: str
    tournament: str
    datagolf_id: str
    market_type: str  # outright_win | top_5 | top_10 | top_20 | make_cut
    tick: float = 0.01
    min_price: float = 0.01
    max_price: float = 0.99


@dataclass(frozen=True)
class FairValueBand:
    """Bayesian fair value: posterior mean with a credible interval."""

    mean: float
    lo: float
    hi: float
    ess: float  # effective sample size behind the posterior

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2.0


@dataclass(frozen=True)
class Quote:
    market_id: str
    side: Side
    price: float
    size: int  # contracts


@dataclass(frozen=True)
class QuoteProposal:
    """Two-sided (or one-sided, or empty) quote set for one market."""

    market_id: str
    quotes: tuple[Quote, ...]
    fair: FairValueBand
    reasons: tuple[str, ...] = ()  # why sides were withheld, if any


@dataclass(frozen=True)
class Fill:
    market_id: str
    side: Side  # the side of OUR quote that was hit
    price: float
    size: int
    timestep: int


def worst_case_settlement_loss(is_long: bool, quantity: int, price: float) -> float:
    """Worst-case loss if ``quantity`` YES contracts near ``price`` settle against the holder.

    Shared by position-limit checks (a hypothetical quote, at its quoted
    price) and mark-to-market position risk (the existing position, at
    current fair value) — same settlement-loss shape, different price input.
    """
    return quantity * price if is_long else quantity * (1.0 - price)


def position_headroom(position: int, side: Side, max_position_per_market: int) -> int:
    """Max additional contracts this side could fill without breaching the limit."""
    sign = 1 if side == Side.BID else -1
    return max_position_per_market - sign * position


def would_breach_position_limit(
    position: int, side: Side, size: int, max_position_per_market: int
) -> bool:
    sign = 1 if side == Side.BID else -1
    projected = position + sign * size
    return abs(projected) > max_position_per_market


@dataclass
class InventoryState:
    """Mutable per-market book state. Positive position = long YES contracts."""

    market_id: str
    position: int = 0
    cash: float = 0.0  # cumulative premium paid/received
    fills: list[Fill] = field(default_factory=list)

    def notional_at_risk(self, fair: float) -> float:
        """Worst-case loss of current position at settlement."""
        return worst_case_settlement_loss(self.position > 0, abs(self.position), fair)


@dataclass(frozen=True)
class RiskDecision:
    approved: tuple[Quote, ...]
    vetoed: tuple[tuple[Quote, str], ...]  # (quote, reason)
    kill_switch: bool = False
