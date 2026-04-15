"""
Shared types for the pricing layer.

FairPriceResult is the output contract for all pricing modules.
Downstream consumers (edge detection, reporting) import this type.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Pricing method identifiers — stored alongside every FairPriceResult for audit.
METHOD_DATAGOLF_DIRECT = "datagolf_direct"       # DG baseline read verbatim
METHOD_HARVILLE = "harville"                      # Derived via Harville formula
METHOD_DATAGOLF_FORECAST = "datagolf_forecast"   # DG pre-tournament probability


@dataclass(frozen=True)
class FairPriceResult:
    """No-vig fair probability for one side of one market.

    For matchups: one FairPriceResult per side (p1 and p2, or p1/p2/p3).
    For outrights/top-N/make-cut: one FairPriceResult per player.

    Invariants:
      - 0 < fair_prob < 1
      - For a two-way matchup, the two FairPriceResults should sum to ~1.0
        (ties not modelled in Phase 2; allocated proportionally).
    """

    market_type: str          # "matchup_2ball" | "matchup_3ball" | "outright_win" | ...
    datagolf_id: str          # primary player this price describes
    opponent_id: str | None   # for matchups: the other side (p1's opponent)
    fair_prob: float          # no-vig probability in (0, 1)
    method: str               # METHOD_* constant above
    as_of: datetime           # timestamp of the source data
