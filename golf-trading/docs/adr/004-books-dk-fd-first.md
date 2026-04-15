# ADR-004: DraftKings and FanDuel as the initial supported books

**Status:** Accepted  
**Date:** 2026-04-15

## Decision

Launch with DraftKings (DK) and FanDuel (FD) only. Add BetMGM, Caesars, and others in Phase 6.

## Context

Indiana has 10+ legal sportsbooks. Building integrations for all of them in Phase 1 would increase maintenance burden and delay the MVP.

## Rationale

DK and FD are the two largest books by golf market liquidity in Indiana. They post the most markets (matchups, 3-balls, props, outrights), often post lines earliest, and have the most reliable odds data availability. Having two books provides line-shopping capability — enough to meaningfully compare prices — without the overhead of managing 8 integrations.

Additional books become more valuable as the system matures: better line shopping, more markets, account diversification as limits tighten. That's a Phase 6 problem.

## Consequences

Early edge detection is limited to DK vs. FD. If both books are priced similarly, apparent edges may not exist. Tracking CLV will use whichever book had the better price at placement as the baseline — this is conservative and appropriate for Phase 1.
