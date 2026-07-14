"""Kalshi venue adapter — MM-1 stub. No live calls in the scaffold.

Documented surface for when MM-1 starts (read-only shadow quoting):

- Base URL: ``https://api.elections.kalshi.com/trade-api/v2`` (verify current
  host and golf series tickers at build time — do not trust this comment).
- ``GET /markets?series_ticker=...`` — discover golf tournament markets.
- ``GET /markets/{ticker}/orderbook`` — depth for shadow-quote comparison.
- WebSocket channel for real-time book updates (MM-1 can poll REST instead).
- Auth: API key ID + RSA private key signature headers. Keys live in ``.env``
  (``KALSHI_API_KEY_ID``, ``KALSHI_PRIVATE_KEY_PATH``); never committed.
- Contracts priced 1–99 cents, 1c tick. Fees per the published schedule —
  load into ``MMConfig.fee_per_contract``, never hardcode.

The scaffold intentionally raises on use so nothing can accidentally trade.
"""

from __future__ import annotations

from ..types import Fill, Quote
from .base import VenueAdapter


class KalshiVenue(VenueAdapter):
    """Placeholder. MM-1 implements read-only discovery + shadow quoting."""

    def post_quotes(self, quotes: tuple[Quote, ...], timestep: int) -> list[Fill]:
        raise NotImplementedError(
            "Kalshi connectivity is gated behind MM-1. Use SimVenue for now."
        )

    def settle(self, market_id: str) -> float:
        raise NotImplementedError(
            "Kalshi connectivity is gated behind MM-1. Use SimVenue for now."
        )
