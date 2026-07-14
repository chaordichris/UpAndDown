"""Quote generation: posterior-driven spread with inventory skew.

Rules, in order:
1. No-quote default: if the posterior band is wider than
   ``max_quotable_half_width``, stand down entirely.
2. Half-spread is max(min_half_spread, mult * posterior half-width) plus
   venue fee — quoting tighter than your own uncertainty is selling
   insurance below cost.
3. Inventory skews the quoted mid against the position (long → shade both
   quotes down to attract sellers of our inventory, i.e. buyers from us).
4. Side size shrinks linearly as inventory utilization rises; a side that
   would breach the position limit is withheld.
"""

from __future__ import annotations

from .config import MMConfig
from .types import FairValueBand, InventoryState, MarketDef, Quote, QuoteProposal, Side


def _round_to_tick(price: float, market: MarketDef) -> float:
    ticks = round(price / market.tick)
    return min(max(ticks * market.tick, market.min_price), market.max_price)


def generate_quotes(
    market: MarketDef,
    fair: FairValueBand,
    inventory: InventoryState,
    config: MMConfig,
) -> QuoteProposal:
    reasons: list[str] = []

    if fair.half_width > config.max_quotable_half_width:
        return QuoteProposal(
            market_id=market.market_id,
            quotes=(),
            fair=fair,
            reasons=(
                f"posterior half-width {fair.half_width:.4f} exceeds "
                f"max quotable {config.max_quotable_half_width:.4f} — no-quote default",
            ),
        )

    utilization = inventory.position / config.max_position_per_market
    skewed_mid = fair.mean - (
        config.inventory_skew_intensity * utilization * fair.half_width
    )
    half_spread = (
        max(config.min_half_spread, config.uncertainty_spread_mult * fair.half_width)
        + config.fee_per_contract
    )

    quotes: list[Quote] = []
    for side in (Side.BID, Side.ASK):
        sign = 1 if side == Side.BID else -1  # bid fills make us longer
        side_utilization = max(0.0, sign * utilization)
        size = int(round(config.base_quote_size * (1.0 - side_utilization)))
        headroom = config.max_position_per_market - sign * inventory.position
        size = min(size, max(0, headroom))
        if size <= 0:
            reasons.append(f"{side.value} withheld: position limit utilization")
            continue
        raw_price = (
            skewed_mid - half_spread if side == Side.BID else skewed_mid + half_spread
        )
        price = _round_to_tick(raw_price, market)
        quotes.append(Quote(market_id=market.market_id, side=side, price=price, size=size))

    bid = next((q for q in quotes if q.side == Side.BID), None)
    ask = next((q for q in quotes if q.side == Side.ASK), None)
    if bid and ask and bid.price >= ask.price:
        # Tick rounding collapsed the spread (deep in a tail). Stand down.
        return QuoteProposal(
            market_id=market.market_id,
            quotes=(),
            fair=fair,
            reasons=("spread collapsed at price boundary — no-quote",),
        )

    return QuoteProposal(
        market_id=market.market_id,
        quotes=tuple(quotes),
        fair=fair,
        reasons=tuple(reasons),
    )
