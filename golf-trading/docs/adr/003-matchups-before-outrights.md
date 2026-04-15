# ADR-003: Matchups as core strategy; outrights as small convex sleeve

**Status:** Accepted  
**Date:** 2026-04-15

## Decision

Matchup (2-ball and 3-ball) markets are the primary edge engine. Outrights are a capped convex sleeve (≤10% of total capital) with fixed small units per bet.

## Context

The strategy has two candidate architectures: (A) outrights as the primary market, (B) matchups as the primary market with outrights as a controlled sleeve.

## Analysis

**Outrights:**
- High vig (often 15-25% hold across the field)
- High variance — even correct model predictions rarely pay off in any given 144-player field
- Hard to evaluate CLV (closing lines are less reliable due to thin liquidity)
- Sample sizes accumulate slowly (one winner per tournament)

**Matchups:**
- Lower vig (typically 4-8% hold)
- Binary outcome with clear settlement
- DataGolf's individual probabilities translate cleanly into matchup fair prices
- Sample sizes accumulate faster (many matchups per tournament, easily 10-20 per week)
- CLV is easy to track and reliable as a process metric

## Decision rationale

Matchups offer the best combination of: low vig, measurable CLV, fast sample accumulation, and clean DataGolf integration. Outrights have an important role — they are genuinely convex (long odds, asymmetric payoff) — but they should be small, fixed units because their variance is too high for Kelly-style sizing to be stable.

## Consequences

The core edge engine will succeed or fail based on matchup pricing quality. If matchup CLV is systematically negative after 50+ bets, the model needs recalibration — not a switch to outrights.
