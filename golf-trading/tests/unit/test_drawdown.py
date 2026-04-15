"""
Unit tests for src/risk/drawdown.py and src/risk/exposure.py

Drawdown: all 5 levels verified with exact threshold values.
Exposure: golfer, tournament, and book limit enforcement.
"""

from __future__ import annotations

import pytest

from src.risk.drawdown import DrawdownState, compute_drawdown_state
from src.risk.exposure import ExposureDecision, OpenBookSummary, check_exposure

# Default thresholds from settings.yaml
THRESHOLDS = dict(
    alert_threshold=0.10,
    reduce_threshold=0.15,
    severe_threshold=0.20,
    paper_only_threshold=0.25,
    halt_threshold=0.35,
)

PEAK = 10_000.0


def _state(current: float) -> DrawdownState:
    return compute_drawdown_state(current, PEAK, **THRESHOLDS)


# ---------------------------------------------------------------------------
# Drawdown levels
# ---------------------------------------------------------------------------

def test_normal_level() -> None:
    state = _state(9_500)  # 5% drawdown
    assert state.level == "normal"
    assert state.sizing_multiplier == 1.0
    assert not state.paper_only
    assert not state.halted


def test_alert_level() -> None:
    state = _state(9_000)  # exactly 10%
    assert state.level == "alert"
    assert state.sizing_multiplier == 1.0
    assert not state.paper_only
    assert not state.halted


def test_reduce_level() -> None:
    state = _state(8_500)  # exactly 15%
    assert state.level == "reduce"
    assert state.sizing_multiplier == 0.5
    assert not state.paper_only


def test_severe_level() -> None:
    state = _state(8_000)  # exactly 20%
    assert state.level == "severe"
    assert state.sizing_multiplier == 0.25
    assert not state.paper_only


def test_paper_only_level() -> None:
    state = _state(7_500)  # exactly 25%
    assert state.level == "paper_only"
    assert state.sizing_multiplier == 0.0
    assert state.paper_only
    assert not state.halted


def test_halt_level() -> None:
    state = _state(6_500)  # exactly 35%
    assert state.level == "halt"
    assert state.sizing_multiplier == 0.0
    assert state.paper_only
    assert state.halted


def test_just_below_alert() -> None:
    state = _state(9_001)  # 9.99%
    assert state.level == "normal"


def test_just_above_reduce() -> None:
    state = _state(8_499)  # 15.01%
    assert state.level == "reduce"


def test_at_peak_is_normal() -> None:
    state = _state(PEAK)
    assert state.level == "normal"
    assert state.drawdown_pct == 0.0


def test_above_peak_treated_as_normal() -> None:
    """active > peak (e.g. first bet scenario) → normal, 0% drawdown."""
    state = _state(PEAK + 1)
    assert state.level == "normal"
    assert state.drawdown_pct == 0.0


def test_drawdown_pct_accurate() -> None:
    state = _state(8_500)  # 15% exactly
    assert abs(state.drawdown_pct - 15.0) < 0.01


def test_invalid_peak_raises() -> None:
    with pytest.raises(ValueError, match="peak_bankroll"):
        compute_drawdown_state(9_000, 0, **THRESHOLDS)


def test_invalid_current_raises() -> None:
    with pytest.raises(ValueError, match="active_bankroll"):
        compute_drawdown_state(0, PEAK, **THRESHOLDS)


# ---------------------------------------------------------------------------
# Exposure limits
# ---------------------------------------------------------------------------

ACTIVE = 10_000.0
TOTAL = 25_000.0
LIMITS = dict(
    active_bankroll=ACTIVE,
    total_bankroll=TOTAL,
    max_golfer_fraction=0.03,      # $300 golfer limit
    max_tournament_fraction=0.05,  # $1250 tournament limit
    max_book_fraction=0.20,        # $5000 book limit
)
EMPTY_BOOK = OpenBookSummary(golfer_stakes={}, tournament_stakes={}, book_stakes={})


def _check(
    stake: float,
    datagolf_id: str = "scheffler",
    tournament_id: str = "tpc_2024",
    book_id: str = "dk",
    open_book: OpenBookSummary = EMPTY_BOOK,
) -> ExposureDecision:
    return check_exposure(
        datagolf_id=datagolf_id,
        tournament_id=tournament_id,
        book_id=book_id,
        proposed_stake=stake,
        open_book=open_book,
        **LIMITS,
    )


def test_exposure_approved_under_all_limits() -> None:
    result = _check(100.0)
    assert result.approved


def test_exposure_golfer_limit_breached() -> None:
    """$200 already on scheffler + $200 proposed = $400 > $300 limit."""
    book = OpenBookSummary(
        golfer_stakes={"scheffler": 200.0},
        tournament_stakes={},
        book_stakes={},
    )
    result = _check(200.0, open_book=book)
    assert not result.approved
    assert "Golfer limit" in result.reason


def test_exposure_tournament_limit_breached() -> None:
    """$1200 already on tpc_2024 + $100 = $1300 > $1250 limit."""
    book = OpenBookSummary(
        golfer_stakes={},
        tournament_stakes={"tpc_2024": 1_200.0},
        book_stakes={},
    )
    result = _check(100.0, open_book=book)
    assert not result.approved
    assert "Tournament limit" in result.reason


def test_exposure_book_limit_breached() -> None:
    """$4900 already at dk + $200 = $5100 > $5000 book limit."""
    book = OpenBookSummary(
        golfer_stakes={},
        tournament_stakes={},
        book_stakes={"dk": 4_900.0},
    )
    result = _check(200.0, open_book=book)
    assert not result.approved
    assert "Book limit" in result.reason


def test_exposure_exactly_at_golfer_limit_approved() -> None:
    """$200 + $100 = $300 = exactly the limit → approved."""
    book = OpenBookSummary(
        golfer_stakes={"scheffler": 200.0},
        tournament_stakes={},
        book_stakes={},
    )
    result = _check(100.0, open_book=book)
    assert result.approved


def test_exposure_different_golfer_no_limit_breach() -> None:
    """Existing stake on mcilroy doesn't affect scheffler's limit."""
    book = OpenBookSummary(
        golfer_stakes={"mcilroy": 295.0},
        tournament_stakes={},
        book_stakes={},
    )
    result = _check(100.0, datagolf_id="scheffler", open_book=book)
    assert result.approved


def test_exposure_empty_book_always_approved_under_limits() -> None:
    """Fresh start: any stake under all three limits is approved."""
    result = _check(50.0)
    assert result.approved
