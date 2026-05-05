"""
Unit tests for src/pricing/matchups.py, top_n.py, and outrights.py.

All tests are pure-math / pure-function — no DB, no I/O.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from src.pricing.fair_price import (
    FairPriceResult,
    METHOD_DATAGOLF_DIRECT,
    METHOD_HARVILLE,
    METHOD_DATAGOLF_FORECAST,
)
from src.pricing.matchups import (
    price_matchup_from_datagolf,
    price_matchup_harville,
    MARKET_2BALL,
    MARKET_3BALL,
)
from src.pricing.top_n import price_top_n, price_all_top_n, SUPPORTED_MARKETS
from src.pricing.outrights import price_outright, price_all_outrights, MARKET_OUTRIGHT_WIN

TOL = 1e-5
NOW = datetime(2024, 3, 11, 14, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Matchup pricing — DataGolf direct
# ---------------------------------------------------------------------------

MATCHUP_ENTRY = {
    "p1_player_name": "Scottie Scheffler",
    "p2_player_name": "Rory McIlroy",
    "p1_datagolf_id": "scottie_scheffler",
    "p2_datagolf_id": "rory_mcilroy",
    "draftkings": {"p1_odds": -145, "p2_odds": 120},
    "datagolf_baseline": {"p1_odds": -155, "p2_odds": 128},
}

def test_matchup_datagolf_direct_returns_two_sides() -> None:
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    assert len(results) == 2


def test_matchup_datagolf_direct_ids() -> None:
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    ids = {r.datagolf_id for r in results}
    assert "scottie_scheffler" in ids
    assert "rory_mcilroy" in ids


def test_matchup_datagolf_direct_probs_sum_to_one() -> None:
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    total = sum(r.fair_prob for r in results)
    assert math.isclose(total, 1.0, abs_tol=1e-6)


def test_matchup_datagolf_direct_method_label() -> None:
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    for r in results:
        assert r.method == METHOD_DATAGOLF_DIRECT


def test_matchup_datagolf_direct_market_type() -> None:
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    for r in results:
        assert r.market_type == MARKET_2BALL


def test_matchup_datagolf_direct_favourite_has_higher_prob() -> None:
    """Scheffler at -155 should have higher fair_prob than McIlroy at +128."""
    results = price_matchup_from_datagolf(MATCHUP_ENTRY, as_of=NOW)
    scheffler = next(r for r in results if r.datagolf_id == "scottie_scheffler")
    mcilroy = next(r for r in results if r.datagolf_id == "rory_mcilroy")
    assert scheffler.fair_prob > mcilroy.fair_prob


def test_matchup_datagolf_direct_missing_baseline_raises() -> None:
    bad = {k: v for k, v in MATCHUP_ENTRY.items() if k != "datagolf_baseline"}
    with pytest.raises(KeyError):
        price_matchup_from_datagolf(bad, as_of=NOW)


def test_matchup_3ball_returns_three_sides() -> None:
    entry_3ball = {
        "p1_player_name": "A", "p2_player_name": "B", "p3_player_name": "C",
        "p1_datagolf_id": "a", "p2_datagolf_id": "b", "p3_datagolf_id": "c",
        "datagolf_baseline": {"p1_odds": 120, "p2_odds": 130, "p3_odds": 150},
    }
    results = price_matchup_from_datagolf(entry_3ball, as_of=NOW)
    assert len(results) == 3
    assert all(r.market_type == MARKET_3BALL for r in results)
    assert math.isclose(sum(r.fair_prob for r in results), 1.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Matchup pricing — Harville
# ---------------------------------------------------------------------------

def test_harville_symmetric_players() -> None:
    """Equal win probs → each side gets 0.50."""
    results = price_matchup_harville(
        [("player_a", 0.30), ("player_b", 0.30)], as_of=NOW
    )
    assert len(results) == 2
    assert math.isclose(results[0].fair_prob, 0.5, abs_tol=TOL)
    assert math.isclose(results[1].fair_prob, 0.5, abs_tol=TOL)


def test_harville_asymmetric_players() -> None:
    """Harville: P(A) = 0.20/(0.20+0.08) ≈ 0.714."""
    results = price_matchup_harville(
        [("scheffler", 0.20), ("long_shot", 0.08)], as_of=NOW
    )
    expected_a = 0.20 / (0.20 + 0.08)
    assert math.isclose(results[0].fair_prob, expected_a, abs_tol=TOL)


def test_harville_probs_sum_to_one() -> None:
    results = price_matchup_harville(
        [("a", 0.15), ("b", 0.10), ("c", 0.05)],
        market_type=MARKET_3BALL, as_of=NOW,
    )
    assert math.isclose(sum(r.fair_prob for r in results), 1.0, abs_tol=TOL)


def test_harville_method_label() -> None:
    results = price_matchup_harville([("a", 0.20), ("b", 0.15)], as_of=NOW)
    for r in results:
        assert r.method == METHOD_HARVILLE


def test_harville_empty_players_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        price_matchup_harville([], as_of=NOW)


def test_harville_single_player_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        price_matchup_harville([("a", 0.20)], as_of=NOW)


def test_harville_zero_prob_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        price_matchup_harville([("a", 0.0), ("b", 0.15)], as_of=NOW)


# ---------------------------------------------------------------------------
# Top-N pricing
# ---------------------------------------------------------------------------

FORECAST_ENTRY = {
    "player_id": "scottie_scheffler",
    "player_name": "Scottie Scheffler",
    "win_probability": 0.142,
    "top_5_probability": 0.372,
    "top_10_probability": 0.521,
    "top_20_probability": 0.682,
    "make_cut_probability": 0.841,
}

@pytest.mark.parametrize("market,expected_prob", [
    ("top_5", 0.372),
    ("top_10", 0.521),
    ("top_20", 0.682),
    ("make_cut", 0.841),
])
def test_price_top_n_correct_probability(market, expected_prob) -> None:
    result = price_top_n(FORECAST_ENTRY, market, as_of=NOW)
    assert math.isclose(result.fair_prob, expected_prob, abs_tol=TOL)


def test_price_top_n_datagolf_id() -> None:
    result = price_top_n(FORECAST_ENTRY, "top_10", as_of=NOW)
    assert result.datagolf_id == "scottie_scheffler"


def test_price_top_n_method() -> None:
    result = price_top_n(FORECAST_ENTRY, "make_cut", as_of=NOW)
    assert result.method == METHOD_DATAGOLF_FORECAST


def test_price_top_n_no_opponent() -> None:
    result = price_top_n(FORECAST_ENTRY, "top_5", as_of=NOW)
    assert result.opponent_id is None


def test_price_top_n_unsupported_market_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported market_type"):
        price_top_n(FORECAST_ENTRY, "top_3", as_of=NOW)


def test_price_all_top_n_returns_all_supported() -> None:
    results = price_all_top_n(FORECAST_ENTRY, as_of=NOW)
    returned_markets = {r.market_type for r in results}
    assert returned_markets == set(SUPPORTED_MARKETS)


def test_price_all_top_n_partial_entry() -> None:
    """Entry with only some markets returns only those markets."""
    partial = {"player_id": "test", "top_10_probability": 0.40}
    results = price_all_top_n(partial, as_of=NOW)
    assert len(results) == 1
    assert results[0].market_type == "top_10"


# ---------------------------------------------------------------------------
# Outright pricing
# ---------------------------------------------------------------------------

def test_price_outright_correct_probability() -> None:
    result = price_outright(FORECAST_ENTRY, as_of=NOW)
    assert math.isclose(result.fair_prob, 0.142, abs_tol=TOL)


def test_price_outright_market_type() -> None:
    result = price_outright(FORECAST_ENTRY, as_of=NOW)
    assert result.market_type == MARKET_OUTRIGHT_WIN


def test_price_outright_method() -> None:
    result = price_outright(FORECAST_ENTRY, as_of=NOW)
    assert result.method == METHOD_DATAGOLF_FORECAST


def test_price_outright_zero_prob_raises() -> None:
    with pytest.raises(ValueError, match="\\(0, 1\\]"):
        price_outright({"player_id": "x", "win_probability": 0.0}, as_of=NOW)


def test_price_all_outrights_count() -> None:
    response = {"players": [FORECAST_ENTRY, {**FORECAST_ENTRY, "player_id": "rory_mcilroy"}]}
    results = price_all_outrights(response, as_of=NOW)
    assert len(results) == 2


def test_price_all_outrights_skips_missing_win_prob() -> None:
    """Player without win_probability is skipped, not errored."""
    response = {
        "players": [
            FORECAST_ENTRY,
            {"player_id": "no_prob_player"},  # no win_probability key
        ]
    }
    results = price_all_outrights(response, as_of=NOW)
    assert len(results) == 1
