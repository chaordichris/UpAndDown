"""
Bet sizing.

Core bets: fractional Kelly criterion.
  Kelly fraction = edge / (decimal_odds - 1)
  Stake = kelly_fraction × kelly_multiplier × active_bankroll

Convex bets: fixed unit (a flat percentage of the convex sleeve).
  Stake = convex_unit_fraction × convex_bankroll

Hard limits applied after Kelly/unit calculation:
  - Floor: min_bet_dollars (no bet below minimum book stake)
  - Ceiling: max_bet_fraction × total_bankroll (absolute cap per bet)

If the computed stake falls below the floor, the bet is rejected.
If it exceeds the ceiling, it is capped (not rejected).

All sizing is intentionally conservative. The default 0.25x Kelly fraction
means the system bets at one-quarter of what full Kelly would suggest.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.normalization.odds import american_to_decimal
from src.risk.edge import EdgeResult
from src.risk.posterior_kelly import compute_posterior_kelly_fraction


@dataclass(frozen=True)
class SizingResult:
    """Output of the sizing calculation for one bet candidate."""

    stake: float          # recommended stake in dollars (0 if rejected)
    approved: bool        # False if stake < min_bet floor
    reason: str           # human-readable explanation for the decision
    kelly_fraction: float # the raw Kelly fraction before multiplier (audit)


def size_core_bet(
    edge: EdgeResult,
    active_bankroll: float,
    total_bankroll: float,
    kelly_multiplier: float,
    min_bet_dollars: float,
    max_bet_fraction: float,
    posterior_kelly_enabled: bool = False,
) -> SizingResult:
    """Compute stake for a core (matchup) bet using fractional Kelly.

    Args:
        edge: EdgeResult for this candidate.
        active_bankroll: Current active-core bankroll (40% of total by default).
        total_bankroll: Total bankroll (for ceiling calculation).
        kelly_multiplier: Fraction of full Kelly to use (e.g., 0.25).
        min_bet_dollars: Absolute minimum stake in dollars.
        max_bet_fraction: Maximum stake as fraction of total_bankroll.

    Returns:
        SizingResult with stake and approval decision.
    """
    if not edge.passes_threshold:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason="Edge below minimum threshold.",
            kelly_fraction=0.0,
        )
    if not edge.passes_fdr:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason="Candidate failed FDR control.",
            kelly_fraction=0.0,
        )
    if posterior_kelly_enabled and edge.edge_sd is None:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason="Posterior Kelly requires edge_sd.",
            kelly_fraction=0.0,
        )

    decimal_odds = american_to_decimal(edge.book_american_odds)
    if posterior_kelly_enabled:
        posterior = compute_posterior_kelly_fraction(
            edge_mean=edge.edge,
            edge_sd=edge.edge_sd or 0.0,
            decimal_odds=decimal_odds,
            user_fraction=kelly_multiplier,
        )
        kelly_f = posterior.posterior_kelly_fraction
        if not posterior.approved:
            return SizingResult(
                stake=0.0,
                approved=False,
                reason=posterior.reason,
                kelly_fraction=kelly_f,
            )
        stake_multiplier = 1.0
    else:
        # Kelly fraction = edge / (odds - 1)
        kelly_f = edge.edge / (decimal_odds - 1.0)
        stake_multiplier = kelly_multiplier

    if kelly_f <= 0:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason=f"Kelly fraction non-positive ({kelly_f:.4f}).",
            kelly_fraction=kelly_f,
        )

    raw_stake = stake_multiplier * kelly_f * active_bankroll
    ceiling = max_bet_fraction * total_bankroll
    stake = min(raw_stake, ceiling)

    if stake < min_bet_dollars:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason=f"Computed stake ${stake:.2f} is below minimum ${min_bet_dollars:.2f}.",
            kelly_fraction=kelly_f,
        )

    return SizingResult(
        stake=round(stake, 2),
        approved=True,
        reason=_sizing_reason(
            kelly_fraction=kelly_f,
            stake_multiplier=stake_multiplier,
            active_bankroll=active_bankroll,
            raw_stake=raw_stake,
            ceiling=ceiling,
            posterior_kelly_enabled=posterior_kelly_enabled,
        ),
        kelly_fraction=kelly_f,
    )


def size_convex_bet(
    edge: EdgeResult,
    convex_bankroll: float,
    total_bankroll: float,
    unit_fraction: float,
    min_bet_dollars: float,
    max_bet_fraction: float,
) -> SizingResult:
    """Compute stake for a convex (outright) bet using a fixed unit.

    Args:
        edge: EdgeResult for this candidate.
        convex_bankroll: Current convex-sleeve bankroll (10% of total by default).
        total_bankroll: Total bankroll (for ceiling calculation).
        unit_fraction: Fixed fraction of convex bankroll per bet (e.g., 0.005).
        min_bet_dollars: Absolute minimum stake.
        max_bet_fraction: Maximum stake as fraction of total_bankroll.

    Returns:
        SizingResult with stake and approval decision.
    """
    if not edge.passes_threshold:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason="Edge below minimum threshold.",
            kelly_fraction=0.0,
        )
    if not edge.passes_fdr:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason="Candidate failed FDR control.",
            kelly_fraction=0.0,
        )

    raw_stake = unit_fraction * convex_bankroll
    ceiling = max_bet_fraction * total_bankroll
    stake = min(raw_stake, ceiling)

    if stake < min_bet_dollars:
        return SizingResult(
            stake=0.0,
            approved=False,
            reason=f"Computed stake ${stake:.2f} is below minimum ${min_bet_dollars:.2f}.",
            kelly_fraction=0.0,
        )

    return SizingResult(
        stake=round(stake, 2),
        approved=True,
        reason=(
            f"Fixed unit {unit_fraction*100:.2f}% × ${convex_bankroll:.0f} = ${raw_stake:.2f}"
            + (f" (capped at ${ceiling:.2f})" if raw_stake > ceiling else "")
        ),
        kelly_fraction=0.0,  # not applicable for fixed-unit sizing
    )


def _sizing_reason(
    *,
    kelly_fraction: float,
    stake_multiplier: float,
    active_bankroll: float,
    raw_stake: float,
    ceiling: float,
    posterior_kelly_enabled: bool,
) -> str:
    if posterior_kelly_enabled:
        prefix = f"Posterior Kelly={kelly_fraction:.4f} × ${active_bankroll:.0f}"
    else:
        prefix = f"Kelly={kelly_fraction:.4f} × {stake_multiplier}x × ${active_bankroll:.0f}"
    return (
        f"{prefix} = ${raw_stake:.2f}"
        + (f" (capped at ${ceiling:.2f})" if raw_stake > ceiling else "")
    )
