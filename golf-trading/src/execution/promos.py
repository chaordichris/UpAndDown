"""Promo-aware settlement helpers."""

from __future__ import annotations

import json

from src.normalization.odds import american_to_decimal

BET_CLASSES = frozenset({"STANDARD", "BOOSTED_ODDS", "FREE_BET", "RISK_FREE"})


def normalize_bet_class(bet_class: str) -> str:
    normalized = bet_class.upper()
    if normalized not in BET_CLASSES:
        raise ValueError(f"Unknown bet_class: {bet_class}")
    return normalized


def settlement_amounts(
    *,
    result: str,
    stake: float,
    american_odds: int,
    bet_class: str = "STANDARD",
    boost_terms_json: str | None = None,
) -> dict[str, float]:
    raw_payout = payout(result, stake, american_odds)
    raw_profit_loss = raw_payout - stake
    realized_payout = raw_payout
    realized_profit_loss = raw_profit_loss
    normalized_class = normalize_bet_class(bet_class)
    terms = parse_terms(boost_terms_json)

    if normalized_class == "BOOSTED_ODDS" and result == "win":
        multiplier = float(terms.get("profit_boost_multiplier", 1.0))
        boosted_profit = (raw_payout - stake) * multiplier
        realized_payout = stake + boosted_profit
        realized_profit_loss = boosted_profit
    elif normalized_class == "FREE_BET":
        realized_payout = max(raw_payout - stake, 0.0) if result == "win" else 0.0
        realized_profit_loss = realized_payout
    elif normalized_class == "RISK_FREE" and result == "loss":
        refund = float(terms.get("refund_amount", stake))
        realized_payout = refund
        realized_profit_loss = refund - stake

    return {
        "payout_raw": round(raw_payout, 2),
        "profit_loss_raw": round(raw_profit_loss, 2),
        "payout_realized": round(realized_payout, 2),
        "profit_loss_realized": round(realized_profit_loss, 2),
    }


def payout(result: str, stake: float, american_odds: int) -> float:
    if result == "win":
        return stake * american_to_decimal(american_odds)
    if result == "loss":
        return 0.0
    if result in {"push", "void"}:
        return stake
    if result == "dead_heat":
        return (stake / 2.0) * american_to_decimal(american_odds) + (stake / 2.0)
    raise ValueError(f"Unknown settlement result: {result}")


def parse_terms(boost_terms_json: str | None) -> dict[str, float | str | int]:
    if not boost_terms_json:
        return {}
    parsed = json.loads(boost_terms_json)
    if not isinstance(parsed, dict):
        raise ValueError("boost_terms_json must decode to an object.")
    return parsed
