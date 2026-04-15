"""
Matchup fair-price calculation.

Two paths:

  1. datagolf_direct — Read DG's own baseline odds from a betting-tools/matchups
     response entry. The `datagolf_baseline` sub-dict contains DG's no-vig
     head-to-head estimate already. Convert to probability via odds normalization.

  2. harville — Derive P(A beats B) from individual win probabilities using the
     Harville formula: P(A | {A,B}) = P_win(A) / (P_win(A) + P_win(B)).
     Use this when DG's direct baseline is unavailable or as a cross-check.

For 3-balls the Harville formula extends naturally:
  P(A | {A,B,C}) = P_win(A) / (P_win(A) + P_win(B) + P_win(C))

These are approximations — they assume players' outcomes are independent given
their skill ratings (IIA assumption). DataGolf's own model likely handles
correlation better; prefer path 1 when available.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.pricing.fair_price import (
    FairPriceResult,
    METHOD_DATAGOLF_DIRECT,
    METHOD_HARVILLE,
)

# Market type labels
MARKET_2BALL = "matchup_2ball"
MARKET_3BALL = "matchup_3ball"


# ---------------------------------------------------------------------------
# Path 1: DataGolf direct baseline
# ---------------------------------------------------------------------------

def price_matchup_from_datagolf(
    match_entry: dict,
    as_of: datetime | None = None,
) -> list[FairPriceResult]:
    """Extract fair prices from a DataGolf betting-tools matchup entry.

    Reads the `datagolf_baseline` sub-dict, which contains DG's own no-vig
    head-to-head odds. Converts those odds to probabilities.

    Args:
        match_entry: One item from the DataGolf match_list response array.
                     Must contain `datagolf_baseline` with `p1_odds` / `p2_odds`
                     (and optionally `p3_odds` for 3-balls), plus player name/id fields.
        as_of: Timestamp to attach to the result. Defaults to now (UTC).

    Returns:
        List of FairPriceResult, one per player side (2 for 2-ball, 3 for 3-ball).

    Raises:
        KeyError: If `datagolf_baseline` or required player fields are missing.
        ValueError: If odds cannot be converted (e.g., zero odds).
    """
    as_of = as_of or datetime.now(timezone.utc)
    baseline = match_entry["datagolf_baseline"]

    n_players = 3 if "p3_player_name" in match_entry else 2
    market_type = MARKET_3BALL if n_players == 3 else MARKET_2BALL

    # Collect (datagolf_id, raw_odds) for each player
    sides: list[tuple[str, float]] = []
    for i in range(1, n_players + 1):
        pk = f"p{i}"
        dg_id = match_entry.get(f"{pk}_datagolf_id", match_entry.get(f"{pk}_player_name", ""))
        raw_odds = baseline[f"{pk}_odds"]
        sides.append((dg_id, float(raw_odds)))

    return _sides_to_fair_prices(sides, market_type, METHOD_DATAGOLF_DIRECT, as_of)


# ---------------------------------------------------------------------------
# Path 2: Harville derivation from individual win probabilities
# ---------------------------------------------------------------------------

def price_matchup_harville(
    players: list[tuple[str, float]],
    market_type: str = MARKET_2BALL,
    as_of: datetime | None = None,
) -> list[FairPriceResult]:
    """Derive matchup fair prices via the Harville formula.

    Args:
        players: List of (datagolf_id, win_probability) tuples.
                 Length 2 for 2-ball, 3 for 3-ball.
        market_type: "matchup_2ball" or "matchup_3ball".
        as_of: Timestamp to attach. Defaults to now (UTC).

    Returns:
        List of FairPriceResult, one per player.

    Raises:
        ValueError: If any win probability is non-positive, or players is empty.
    """
    if not players:
        raise ValueError("players must not be empty.")
    if len(players) < 2:
        raise ValueError(f"Need at least 2 players for a matchup, got {len(players)}.")
    if any(p <= 0.0 for _, p in players):
        raise ValueError("All win probabilities must be positive.")

    as_of = as_of or datetime.now(timezone.utc)
    total = sum(p for _, p in players)

    results = []
    ids = [dg_id for dg_id, _ in players]
    for i, (dg_id, win_prob) in enumerate(players):
        fair_prob = win_prob / total
        opponent_id = ids[1 - i] if len(ids) == 2 else None
        results.append(FairPriceResult(
            market_type=market_type,
            datagolf_id=dg_id,
            opponent_id=opponent_id,
            fair_prob=fair_prob,
            method=METHOD_HARVILLE,
            as_of=as_of,
        ))
    return results


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _sides_to_fair_prices(
    sides: list[tuple[str, float]],
    market_type: str,
    method: str,
    as_of: datetime,
) -> list[FairPriceResult]:
    """Convert (datagolf_id, american_odds) pairs into FairPriceResult list.

    Converts American odds → implied prob, then normalises so the sides
    sum to 1.0 (DG's baseline should already be no-vig, but this guards
    against any floating-point drift).
    """
    raw_probs = []
    for dg_id, american_odds in sides:
        decimal = american_to_decimal(american_odds)
        raw_probs.append((dg_id, decimal_to_implied(decimal)))

    total = sum(p for _, p in raw_probs)
    ids = [dg_id for dg_id, _ in raw_probs]

    results = []
    for i, (dg_id, raw_prob) in enumerate(raw_probs):
        fair_prob = raw_prob / total  # normalise to sum=1
        opponent_id = ids[1 - i] if len(ids) == 2 else None
        results.append(FairPriceResult(
            market_type=market_type,
            datagolf_id=dg_id,
            opponent_id=opponent_id,
            fair_prob=fair_prob,
            method=method,
            as_of=as_of,
        ))
    return results
