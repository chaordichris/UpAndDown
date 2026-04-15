# UpAndDown — Agent Project Charter

## What this is

A systematic golf betting framework. DataGolf provides the model.
The system translates forecasts into fair prices, finds edges against
sportsbook lines, sizes bets conservatively, and tracks performance.

## Core philosophy

**Survival first. No-bet is the default.** Small repeatable edges in
matchup markets. Tiny convex sleeve for outrights. Never compromise the bankroll.

## Current phase

**Phase 1 — Ingestion + Normalization complete.** Next: Phase 2 (Pricing + Risk).

## What was built in Phase 1

1. `src/normalization/odds.py` — American ↔ decimal ↔ implied prob (pure math, fully tested)
2. `src/normalization/vig.py` — Multiplicative and power vig removal (20+ tests)
3. `src/normalization/players.py` — Player name/ID resolution (exact, alias, fuzzy with difflib)
4. `src/ingestion/datagolf.py` — DataGolf API client (httpx, 3-retry backoff, snapshot persistence)
5. `src/ingestion/sportsbooks.py` — DK/FD parsers + persist stub; live fetch = NotImplementedError (needs odds API or scraper)

## What to build next (Phase 2)

1. `src/pricing/matchups.py` — P(A beats B) from DataGolf's individual finish distributions
2. `src/pricing/top_n.py` — Make-cut and top-N fair prices directly from DG probabilities
3. `src/pricing/outrights.py` — Outright win fair prices from DG win probabilities
4. `src/risk/edge.py` — Edge detection: fair_prob − book_no_vig_prob; filter by min_edge thresholds
5. `src/risk/sizing.py` — Fractional Kelly sizing (0.25x) + max_bet_fraction cap
6. `src/risk/exposure.py` — Golfer / tournament / book concentration limits
7. `src/risk/drawdown.py` — 4-level drawdown brake logic

See `docs/adr/` and build plan for full specs.

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
