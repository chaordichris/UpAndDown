"""
Outright win fair-price extraction from DataGolf pre-tournament forecasts.

DataGolf's /preds/pre-tournament response provides a `win_probability` for
each player. This is already a no-vig model probability — use it directly
as the fair price for the outright win market.

A field of 150 players will have win probabilities that sum to ~1.0 (modulo
any missing players or rounding). We do not re-normalise across the field
here — each player's probability is treated independently, matching how the
books price outrights (per-player, not relative-to-field).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.pricing.fair_price import FairPriceResult, METHOD_DATAGOLF_FORECAST

MARKET_OUTRIGHT_WIN = "outright_win"


def price_outright(
    player_entry: dict,
    as_of: datetime | None = None,
) -> FairPriceResult:
    """Extract outright win fair price from a DataGolf forecast entry.

    Args:
        player_entry: One player dict from DG /preds/pre-tournament `players`
                      array. Must contain `win_probability` and `player_id`.
        as_of: Timestamp. Defaults to now (UTC).

    Returns:
        FairPriceResult for this player's outright win market.

    Raises:
        KeyError: If required fields are absent.
        ValueError: If win_probability is out of (0, 1].
    """
    fair_prob = float(player_entry["win_probability"])

    if not (0.0 < fair_prob <= 1.0):
        raise ValueError(
            f"win_probability must be in (0, 1], got {fair_prob} "
            f"for player {player_entry.get('player_id', 'unknown')!r}."
        )

    as_of = as_of or datetime.now(timezone.utc)
    return FairPriceResult(
        market_type=MARKET_OUTRIGHT_WIN,
        datagolf_id=player_entry["player_id"],
        opponent_id=None,
        fair_prob=fair_prob,
        method=METHOD_DATAGOLF_FORECAST,
        as_of=as_of,
    )


def price_all_outrights(
    forecast_response: dict,
    as_of: datetime | None = None,
) -> list[FairPriceResult]:
    """Extract outright win fair prices for every player in a DG forecast response.

    Args:
        forecast_response: Full /preds/pre-tournament response dict.
                           Must contain a `players` list.
        as_of: Timestamp. Defaults to now (UTC).

    Returns:
        List of FairPriceResult, one per player with a valid win_probability.
    """
    as_of = as_of or datetime.now(timezone.utc)
    results = []
    for player in forecast_response.get("players", []):
        if "win_probability" in player:
            results.append(price_outright(player, as_of=as_of))
    return results
