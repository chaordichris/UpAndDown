# ADR-005: Bankroll philosophy — Spitznagel-inspired capital structure

**Status:** Accepted  
**Date:** 2026-04-15

## Decision

Adopt a two-sleeve capital structure with permanent reserves. Use fractional Kelly (0.25x) for core bets and fixed small units for convex bets. Enforce hard drawdown brakes at four levels.

## Context

Sports betting bankroll management has a spectrum: full Kelly (maximize geometric growth, high volatility), flat betting (simple, predictable, but doesn't compound edge), and fractional Kelly (middle ground). The choice shapes the entire risk profile.

## Rationale

The Spitznagel approach applied here: the goal is survival and long-run compounding, not short-term ROI maximization. Full Kelly with uncertain edge estimates is dangerous — a 5% edge estimate has wide confidence intervals, and overbetting a bad estimate produces rapid ruin. Quarter Kelly provides roughly 85% of the geometric growth rate of full Kelly with dramatically lower volatility and drawdown risk.

The permanent reserve (50% of capital) is not deployed capital that's "waiting for an edge" — it is the insurance buffer that ensures the system can always restart. This is directly inspired by Spitznagel's tail-risk philosophy: the reserve is the hedge.

The two-sleeve structure separates the core (repeatable edges, small bets, measurable CLV) from the convex sleeve (outrights, small fixed units, asymmetric payoff) so they can be tracked, sized, and evaluated independently.

## Consequences

This is deliberately more conservative than most sports betting systems. ROI in any given 4-week window will look unimpressive. The goal is to still be operating 12+ months from now with a provably edge-positive process. That requires surviving drawdowns, not maximizing wins.
