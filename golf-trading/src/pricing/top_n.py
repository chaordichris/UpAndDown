"""
Top-N and make-cut fair-price extraction from DataGolf pre-tournament forecasts.

DataGolf's /preds/pre-tournament response provides per-player probabilities for
win, top-5, top-10, top-20, and make-cut. These are already no-vig model
probabilities — they don't sum to 1.0 across players because multiple players
can all make the cut or finish top-10 at the same time.

Each probability is used directly as the fair price for that player in that
market. No derivation needed.

Supported markets:
  "top_5"    → top_5_probability
  "top_10"   → top_10_probability
  "top_20"   → top_20_probability
  "make_cut" → make_cut_probability
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.pricing.fair_price import FairPriceResult, METHOD_DATAGOLF_FORECAST

# Mapping from market_type string to the key in a DG forecast player dict
_MARKET_KEY: dict[str, str] = {
    "top_5": "top_5_probability",
    "top_10": "top_10_probability",
    "top_20": "top_20_probability",
    "make_cut": "make_cut_probability",
}

SUPPORTED_MARKETS: tuple[str, ...] = tuple(_MARKET_KEY)


def price_top_n(
    player_entry: dict,
    market_type: str,
    as_of: datetime | None = None,
) -> FairPriceResult:
    """Extract a top-N or make-cut fair price from a DataGolf forecast entry.

    Args:
        player_entry: One player dict from the DG /preds/pre-tournament
                      `players` array. Must contain the probability key for
                      the requested market and `player_id`.
        market_type: One of "top_5", "top_10", "top_20", "make_cut".
        as_of: Timestamp. Defaults to now (UTC).

    Returns:
        FairPriceResult for this player in this market.

    Raises:
        ValueError: If market_type is not supported.
        KeyError: If the player entry is missing required fields.
    """
    if market_type not in _MARKET_KEY:
        raise ValueError(
            f"Unsupported market_type {market_type!r}. "
            f"Supported: {SUPPORTED_MARKETS}"
        )

    prob_key = _MARKET_KEY[market_type]
    fair_prob = float(player_entry[prob_key])
    _validate_prob(fair_prob, market_type, player_entry.get("player_id", "unknown"))

    as_of = as_of or datetime.now(timezone.utc)
    return FairPriceResult(
        market_type=market_type,
        datagolf_id=player_entry["player_id"],
        opponent_id=None,
        fair_prob=fair_prob,
        method=METHOD_DATAGOLF_FORECAST,
        as_of=as_of,
    )


def price_all_top_n(
    player_entry: dict,
    as_of: datetime | None = None,
) -> list[FairPriceResult]:
    """Extract fair prices for all supported top-N markets from one forecast entry.

    Returns one FairPriceResult per supported market type that is present in
    the player entry. Silently skips markets whose key is absent.
    """
    as_of = as_of or datetime.now(timezone.utc)
    results = []
    for market_type, prob_key in _MARKET_KEY.items():
        if prob_key in player_entry:
            results.append(price_top_n(player_entry, market_type, as_of=as_of))
    return results


def _validate_prob(prob: float, market_type: str, player_id: str) -> None:
    if not (0.0 < prob <= 1.0):
        raise ValueError(
            f"Invalid probability {prob} for player={player_id!r} market={market_type!r}. "
            "Expected value in (0, 1]."
        )
