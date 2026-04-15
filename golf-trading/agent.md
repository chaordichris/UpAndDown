# UpAndDown — Agent Project Charter

## What this is

A systematic golf betting framework. DataGolf provides the model.
The system translates forecasts into fair prices, finds edges against
sportsbook lines, sizes bets conservatively, and tracks performance.

## Core philosophy

**Survival first. No-bet is the default.** Small repeatable edges in
matchup markets. Tiny convex sleeve for outrights. Never compromise the bankroll.

## Current phase

**Phase 0 — Foundation complete.** Next: Phase 1 (Data Ingestion).

## What to build next (Phase 1)

1. `src/ingestion/datagolf.py` — DataGolf API client
2. `src/ingestion/sportsbooks.py` — DraftKings + FanDuel odds ingestion
3. `src/normalization/odds.py` — American ↔ decimal ↔ implied prob
4. `src/normalization/vig.py` — Multiplicative and power vig removal
5. `src/normalization/players.py` — Player name/ID resolution

See `docs/skills/` for full skill specs per module.

## Conventions

- Python 3.11+. Type hints everywhere. Dataclasses for interfaces between modules.
- All configurable values in `config/settings.yaml` or `config/books.yaml`.
- Secrets in `.env`. Never committed.
- Every module has unit tests. Target 80%+ coverage on core modules.
- Every function that does math has property-based or table-driven tests.
- No hardcoded magic numbers anywhere.
- Every bet decision is logged with full provenance (snapshot IDs, fair price, book price, edge, reason).
- `make test` must pass before any commit.

## Module interfaces

All modules communicate via typed dataclasses. The key interface types are:

| Type | Produced by | Consumed by |
|------|-------------|-------------|
| `RawSnapshot` | ingestion | storage |
| `NormalizedOdds` | normalization | pricing |
| `FairPrice` | pricing | edge |
| `BetCandidate` | edge | risk |
| `BetTicket` | risk | execution |
| `PlacedBet` | execution | monitoring |
| `BetOutcome` | settlement | monitoring |

## What NOT to do

- Do not build a custom golf model. Use DataGolf's forecasts.
- Do not automate bet placement (Phases 1-4 are all manual execution).
- Do not add markets, books, or tours before matchup MVP works.
- Do not tune parameters on backtest results without a holdout set.
- Do not use ROI as a signal over fewer than 100 bets. Use CLV instead.
- Do not override the risk engine. It has veto power over every bet.
- Do not hardcode any number that could reasonably need to change.

## Key files

| File | Purpose |
|------|---------|
| `config/settings.yaml` | All non-secret parameters |
| `config/books.yaml` | Book-specific rules and market config |
| `config/.env.example` | Template for secrets |
| `docs/adr/` | Architecture decision records |
| `docs/skills/` | Skill specs per module |
| `src/config.py` | Typed config loader |
| `src/storage/models.py` | All 13 DB table definitions |
| `src/storage/db.py` | Connection and session management |

## Build sequence

```
Phase 0: Foundation (complete)
  └─ Repo, config, storage, tests, ADRs

Phase 1: Ingestion + Normalization
  ├─ DataGolf API client
  ├─ DraftKings + FanDuel odds ingestion
  ├─ Odds normalization (American/decimal/prob)
  ├─ Vig removal (multiplicative + power)
  └─ Player name resolution

Phase 2: Pricing + Risk
  ├─ Matchup fair-odds pricing (primary)
  ├─ Make-cut / top-N pricing
  ├─ Edge detection + ranking
  ├─ Kelly sizing
  ├─ Exposure + concentration control
  └─ Drawdown brakes

Phase 3: Paper Trading
  ├─ Bet ticket output
  ├─ Placement logger (manual)
  ├─ Settlement recorder
  ├─ CLV tracker
  └─ Weekly report

Phase 4: Shadow Live (real bets at minimum stakes)
Phase 5: Full Capital Deployment
Phase 6: Iteration + Expansion
```

## Success metric

Positive aggregate CLV over 50+ bets across 8+ tournaments.
ROI is tracked but not used as a signal below 100 bets.
