# ADR-002: DataGolf as the pricing anchor

**Status:** Accepted  
**Date:** 2026-04-15

## Decision

Use DataGolf's pre-tournament forecasts as the sole source of fair prices in Stage 1. Do not build a competing golf model.

## Context

The system needs fair prices for matchups, make-cut, top-N, and outrights. Building a golf model from scratch requires years of historical shot data, course-fit modeling, and significant validation time before it could be trusted with real capital.

## Alternatives considered

- **Build a custom model:** More control, more potential edge. Requires months of work with no guarantee of outperforming DataGolf, and introduces model risk that's hard to validate quickly.
- **Use multiple models and average:** Adds complexity without clear benefit in Stage 1.

## Rationale

DataGolf is the best publicly available golf forecasting model. It has strong calibration history. The system's alpha in Stage 1 comes from translating DataGolf's probabilities cleanly into fair prices, and identifying markets where books are mispriced relative to that baseline — not from building a better model. The pricing interface is abstract so alternative models can be added later.

## Consequences

Single-source dependency on DataGolf. If DataGolf goes down, no fair prices. Mitigation: cache the last good DG snapshot; use it for up to 24 hours before alerting. If DataGolf's model quality degrades over time, Stage 2 overlays and Stage 3 meta-model add additional signal.
