"""
Drawdown brake.

Tracks how far the active-core bankroll has fallen from its peak and
returns a DrawdownState that the rest of the system respects.

Five levels (from settings.yaml):

  normal      drawdown < 10%   → full sizing (multiplier = 1.0)
  alert       drawdown ≥ 10%   → full sizing, operator notified
  reduce      drawdown ≥ 15%   → half sizing (multiplier = 0.5)
  severe      drawdown ≥ 20%   → quarter sizing (multiplier = 0.25)
  paper_only  drawdown ≥ 25%   → no real bets (multiplier = 0.0, paper_only = True)
  halt        drawdown ≥ 35%   → full system halt (multiplier = 0.0, halted = True)

The sizing multiplier is applied on top of Kelly / unit sizing.
The caller (orchestrator) is responsible for passing the correct
active_bankroll and peak_bankroll. This module does no DB access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrawdownState:
    """Current drawdown level and its effect on bet sizing."""

    level: str              # "normal" | "alert" | "reduce" | "severe" | "paper_only" | "halt"
    drawdown_pct: float     # current drawdown as a percentage, e.g. 12.5
    sizing_multiplier: float  # 1.0 | 0.5 | 0.25 | 0.0
    paper_only: bool        # True → log bets but do not place
    halted: bool            # True → do not compute or log anything


def compute_drawdown_state(
    active_bankroll: float,
    peak_bankroll: float,
    alert_threshold: float,
    reduce_threshold: float,
    severe_threshold: float,
    paper_only_threshold: float,
    halt_threshold: float,
) -> DrawdownState:
    """Compute the current drawdown state.

    Args:
        active_bankroll: Current active-core bankroll value.
        peak_bankroll: Highest active-core bankroll value ever recorded.
        alert_threshold: Fraction at which to alert (e.g., 0.10).
        reduce_threshold: Fraction at which to halve sizing (e.g., 0.15).
        severe_threshold: Fraction at which to quarter sizing (e.g., 0.20).
        paper_only_threshold: Fraction at which to go paper-only (e.g., 0.25).
        halt_threshold: Fraction at which to halt entirely (e.g., 0.35).

    Returns:
        DrawdownState describing the current risk level.

    Raises:
        ValueError: If active_bankroll or peak_bankroll is non-positive,
                    or if active > peak (caller data error).
    """
    if peak_bankroll <= 0:
        raise ValueError(f"peak_bankroll must be positive, got {peak_bankroll}.")
    if active_bankroll <= 0:
        raise ValueError(f"active_bankroll must be positive, got {active_bankroll}.")
    if active_bankroll > peak_bankroll:
        # This can happen legitimately on the very first bet (peak = initial).
        # Treat as no drawdown.
        return DrawdownState(
            level="normal",
            drawdown_pct=0.0,
            sizing_multiplier=1.0,
            paper_only=False,
            halted=False,
        )

    drawdown = (peak_bankroll - active_bankroll) / peak_bankroll
    drawdown_pct = drawdown * 100.0

    # Evaluate from most severe to least (order matters)
    if drawdown >= halt_threshold:
        return DrawdownState(
            level="halt",
            drawdown_pct=drawdown_pct,
            sizing_multiplier=0.0,
            paper_only=True,
            halted=True,
        )
    if drawdown >= paper_only_threshold:
        return DrawdownState(
            level="paper_only",
            drawdown_pct=drawdown_pct,
            sizing_multiplier=0.0,
            paper_only=True,
            halted=False,
        )
    if drawdown >= severe_threshold:
        return DrawdownState(
            level="severe",
            drawdown_pct=drawdown_pct,
            sizing_multiplier=0.25,
            paper_only=False,
            halted=False,
        )
    if drawdown >= reduce_threshold:
        return DrawdownState(
            level="reduce",
            drawdown_pct=drawdown_pct,
            sizing_multiplier=0.5,
            paper_only=False,
            halted=False,
        )
    if drawdown >= alert_threshold:
        return DrawdownState(
            level="alert",
            drawdown_pct=drawdown_pct,
            sizing_multiplier=1.0,
            paper_only=False,
            halted=False,
        )

    return DrawdownState(
        level="normal",
        drawdown_pct=drawdown_pct,
        sizing_multiplier=1.0,
        paper_only=False,
        halted=False,
    )
