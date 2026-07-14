"""Read-only Splash contest opportunity evaluation and capital planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.storage.hashing import stable_hash

EVALUATOR_VERSION = "splash-contest-evaluator-v1"


@dataclass(frozen=True)
class SplashLobbyEvaluationConfig:
    bankroll_dollars: float
    weekly_cap_fraction: float = 0.05
    per_contest_cap_fraction: float = 0.02
    max_entries_per_contest: int = 8
    min_action_score: float = 55.0
    priority_action_score: float = 75.0


def build_splash_lobby_evaluation(
    discovery_manifest: dict[str, Any],
    *,
    config: SplashLobbyEvaluationConfig,
) -> dict[str, Any]:
    """Evaluate lobby contests and build a conservative capital plan."""
    _validate_config(config)
    contests = [_evaluate_contest(row, config) for row in discovery_manifest.get("contests", [])]
    contests = sorted(
        contests,
        key=lambda row: (
            row["recommendation"]["rank"],
            row["opportunity_score"],
            row["capital"]["recommended_spend_dollars"],
        ),
        reverse=True,
    )
    capital_plan = _capital_plan(contests, config)
    artifact = {
        "artifact_type": "splash_lobby_evaluation",
        "version": EVALUATOR_VERSION,
        "source": {
            "discovery_artifact_hash": discovery_manifest.get("artifact_hash"),
            "league_id": (discovery_manifest.get("source") or {}).get("league_id"),
            "lobby_url": (discovery_manifest.get("source") or {}).get("lobby_url"),
        },
        "config": {
            "bankroll_dollars": config.bankroll_dollars,
            "weekly_cap_fraction": config.weekly_cap_fraction,
            "per_contest_cap_fraction": config.per_contest_cap_fraction,
            "max_entries_per_contest": config.max_entries_per_contest,
            "min_action_score": config.min_action_score,
            "priority_action_score": config.priority_action_score,
        },
        "capital_plan": capital_plan,
        "contests": contests,
        "contest_count": len(contests),
    }
    return {**artifact, "artifact_hash": stable_hash(artifact)}


def _evaluate_contest(row: dict[str, Any], config: SplashLobbyEvaluationConfig) -> dict[str, Any]:
    entries = row.get("entries") or {}
    league = row.get("league") or {}
    entry_fee = _money(row.get("entry_fee_dollars"), row.get("entry_fee_cents"))
    prize_pool = _money(row.get("prize_pool_dollars"), row.get("prize_pool_cents"))
    filled = _optional_float(entries.get("filled"))
    max_entries = _optional_float(entries.get("max"))
    max_per_user = int(entries.get("max_per_user") or 0)
    fill_rate = filled / max_entries if filled is not None and max_entries else None
    capacity = min(
        max_per_user,
        config.max_entries_per_contest,
        int((config.bankroll_dollars * config.per_contest_cap_fraction) // entry_fee)
        if entry_fee > 0
        else 0,
    )
    capacity = max(0, capacity)
    recommended_entries = 0
    component_scores = {
        "strategy_fit": _strategy_fit_score(row),
        "capacity": _capacity_score(capacity, max_per_user),
        "fill_state": _fill_state_score(fill_rate),
        "prize_efficiency": _prize_efficiency_score(entry_fee, prize_pool, max_entries),
        "operational_simplicity": _operational_simplicity_score(row),
    }
    penalties = _penalties(row, fill_rate, capacity)
    opportunity_score = max(0.0, min(100.0, sum(component_scores.values()) - sum(penalties.values())))
    action, rank = _recommendation(opportunity_score, capacity, row, config)
    if action in {"priority-play", "play-small"}:
        recommended_entries = min(capacity, 3 if action == "priority-play" else 1)
    elif action == "analyze":
        recommended_entries = min(capacity, 1)

    return {
        "contest": {
            "id": row.get("id"),
            "name": row.get("name"),
            "contest_type": row.get("contest_type"),
            "contest_type_alt_text": row.get("contest_type_alt_text"),
            "entry_fee_dollars": entry_fee,
            "prize_pool_dollars": prize_pool,
            "start_date": row.get("start_date"),
            "status": row.get("status"),
            "scoring_type": row.get("scoring_type"),
            "expected_picks_count": row.get("expected_picks_count"),
            "drop_worst_count": row.get("drop_worst_count"),
            "league_id": league.get("id"),
            "league_name": league.get("name"),
            "league_sport": league.get("sport"),
        },
        "field": {
            "filled_entries": int(filled) if filled is not None else None,
            "max_entries": int(max_entries) if max_entries is not None else None,
            "max_per_user": max_per_user,
            "fill_rate": round(fill_rate, 4) if fill_rate is not None else None,
            "remaining_entries": int(max_entries - filled)
            if filled is not None and max_entries is not None
            else None,
        },
        "scores": component_scores,
        "penalties": penalties,
        "opportunity_score": round(opportunity_score, 2),
        "capital": {
            "max_feasible_entries": capacity,
            "recommended_entries": recommended_entries,
            "recommended_spend_dollars": round(recommended_entries * entry_fee, 2),
            "max_feasible_spend_dollars": round(capacity * entry_fee, 2),
        },
        "recommendation": {
            "action": action,
            "rank": rank,
            "reasons": _reasons(row, fill_rate, capacity, component_scores, penalties),
        },
        "inputs_hash": stable_hash(row),
    }


def _capital_plan(contests: list[dict[str, Any]], config: SplashLobbyEvaluationConfig) -> dict[str, Any]:
    weekly_cap = config.bankroll_dollars * config.weekly_cap_fraction
    planned: list[dict[str, Any]] = []
    total_spend = 0.0
    for contest in contests:
        spend = float(contest["capital"]["recommended_spend_dollars"])
        if spend <= 0:
            continue
        if total_spend + spend > weekly_cap:
            entry_fee = float(contest["contest"]["entry_fee_dollars"])
            remaining_entries = int((weekly_cap - total_spend) // entry_fee) if entry_fee > 0 else 0
            spend = remaining_entries * entry_fee
            if remaining_entries <= 0:
                continue
            contest = {
                **contest,
                "capital": {
                    **contest["capital"],
                    "recommended_entries": remaining_entries,
                    "recommended_spend_dollars": round(spend, 2),
                },
            }
        planned.append(
            {
                "contest_id": contest["contest"]["id"],
                "name": contest["contest"]["name"],
                "action": contest["recommendation"]["action"],
                "recommended_entries": contest["capital"]["recommended_entries"],
                "recommended_spend_dollars": contest["capital"]["recommended_spend_dollars"],
                "opportunity_score": contest["opportunity_score"],
            }
        )
        total_spend += spend
    return {
        "weekly_cap_dollars": round(weekly_cap, 2),
        "planned_spend_dollars": round(total_spend, 2),
        "remaining_cap_dollars": round(max(0.0, weekly_cap - total_spend), 2),
        "planned_contest_count": len(planned),
        "planned_entries": sum(int(row["recommended_entries"]) for row in planned),
        "planned_contests": planned,
    }


def _strategy_fit_score(row: dict[str, Any]) -> float:
    score = 0.0
    if row.get("contest_type") == "player_tier":
        score += 18.0
    if row.get("scoring_type") == "golf_score":
        score += 22.0
    if row.get("expected_picks_count") == 6:
        score += 8.0
    if row.get("drop_worst_count") in {0, 1}:
        score += 7.0
    return score


def _capacity_score(capacity: int, max_per_user: int) -> float:
    if capacity <= 0:
        return 0.0
    if max_per_user >= 20:
        return 12.0
    if max_per_user >= 5:
        return 9.0
    return 6.0


def _fill_state_score(fill_rate: float | None) -> float:
    if fill_rate is None:
        return 6.0
    if 0.20 <= fill_rate <= 0.85:
        return 12.0
    if 0.05 <= fill_rate < 0.20:
        return 8.0
    if 0.85 < fill_rate < 0.98:
        return 7.0
    return 2.0


def _prize_efficiency_score(entry_fee: float, prize_pool: float, max_entries: float | None) -> float:
    if entry_fee <= 0 or not max_entries:
        return 0.0
    rake_proxy = 1.0 - (prize_pool / (entry_fee * max_entries))
    if rake_proxy <= 0.05:
        return 10.0
    if rake_proxy <= 0.12:
        return 7.0
    if rake_proxy <= 0.18:
        return 4.0
    return 1.0


def _operational_simplicity_score(row: dict[str, Any]) -> float:
    score = 0.0
    if row.get("status") == "SCHEDULED":
        score += 4.0
    if (row.get("league") or {}).get("sport") == "golf":
        score += 3.0
    return score


def _penalties(row: dict[str, Any], fill_rate: float | None, capacity: int) -> dict[str, float]:
    penalties: dict[str, float] = {}
    if row.get("scoring_type") != "golf_score":
        penalties["unsupported_scoring_type"] = 30.0
    if row.get("contest_type") != "player_tier":
        penalties["unsupported_contest_type"] = 20.0
    if row.get("status") != "SCHEDULED":
        penalties["not_scheduled"] = 25.0
    if fill_rate is not None and fill_rate >= 0.98:
        penalties["nearly_full"] = 12.0
    if capacity <= 0:
        penalties["no_capital_capacity"] = 20.0
    return penalties


def _recommendation(
    score: float,
    capacity: int,
    row: dict[str, Any],
    config: SplashLobbyEvaluationConfig,
) -> tuple[str, int]:
    if capacity <= 0 or row.get("status") != "SCHEDULED":
        return "ignore", 0
    if row.get("scoring_type") != "golf_score" or row.get("contest_type") != "player_tier":
        return "monitor", 1
    if score >= config.priority_action_score:
        return "priority-play", 5
    if score >= config.min_action_score + 10:
        return "play-small", 4
    if score >= config.min_action_score:
        return "analyze", 3
    return "monitor", 1


def _reasons(
    row: dict[str, Any],
    fill_rate: float | None,
    capacity: int,
    component_scores: dict[str, float],
    penalties: dict[str, float],
) -> list[str]:
    reasons = []
    if row.get("scoring_type") == "golf_score":
        reasons.append("DataGolf total-strokes workflow supported")
    if row.get("contest_type") == "player_tier":
        reasons.append("tiered roster format supported")
    if capacity > 0:
        reasons.append(f"capital capacity supports up to {capacity} entries under caps")
    if fill_rate is not None:
        reasons.append(f"lobby fill rate {fill_rate:.1%}")
    if component_scores["prize_efficiency"] >= 7:
        reasons.append("prize pool is efficient versus listed max entries")
    reasons.extend(f"penalty: {name}" for name in sorted(penalties))
    return reasons


def _money(dollars: Any, cents: Any) -> float:
    if dollars is not None:
        return float(dollars)
    if cents is not None:
        return int(cents) / 100
    return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _validate_config(config: SplashLobbyEvaluationConfig) -> None:
    if config.bankroll_dollars <= 0:
        raise ValueError("bankroll_dollars must be positive")
    if not 0 < config.weekly_cap_fraction <= 1:
        raise ValueError("weekly_cap_fraction must be in (0, 1]")
    if not 0 < config.per_contest_cap_fraction <= 1:
        raise ValueError("per_contest_cap_fraction must be in (0, 1]")
    if config.max_entries_per_contest <= 0:
        raise ValueError("max_entries_per_contest must be positive")
    if not 0 <= config.min_action_score <= config.priority_action_score <= 100:
        raise ValueError("action score thresholds must satisfy 0 <= min <= priority <= 100")
