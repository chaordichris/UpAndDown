# UpAndDown — Agent Project Charter

## What this is

A systematic golf betting framework. DataGolf provides the model.
The system translates forecasts into fair prices, finds edges against
sportsbook lines, sizes bets conservatively, and tracks performance.

## Core philosophy

**Survival first. No-bet is the default.** Small repeatable edges in
matchup markets. Tiny convex sleeve for outrights. Never compromise the bankroll.

## Current status

- **Phase 2 baseline is complete.** Pricing, edge detection, and baseline risk controls exist and are tested.
- **Phase 3 is next.** Execution, settlement, CLV tracking, and reporting are still open.
- **v0.2 quant-risk upgrades are not integrated yet.** Use `docs/agent-execution-plan.md` plus the addendum to sequence them behind the Phase 3 backbone.

## What is already built

1. `src/config.py`, `src/storage/`, `scripts/init_db.py` — foundation, config, schema, and DB lifecycle
2. `src/ingestion/datagolf.py`, `src/ingestion/sportsbooks.py` — DataGolf ingestion and odds snapshot parsing
3. `src/normalization/odds.py`, `src/normalization/vig.py`, `src/normalization/players.py` — core normalization math
4. `src/pricing/` — matchup, top-N, outright pricing baseline
5. `src/risk/edge.py`, `src/risk/sizing.py`, `src/risk/exposure.py`, `src/risk/drawdown.py` — baseline edge and risk engine

## What to build next

1. `src/execution/` — ticket generation, placement logging, settlement recording
2. `src/monitoring/` — CLV, reporting, and execution diagnostics
3. `src/storage/hashing.py` and `tests/replay/` — deterministic provenance and smoke contracts
4. `src/risk/posterior_kelly.py`, `src/risk/ror.py`, `src/risk/fdr.py` — v0.2 quant-risk floor
5. `scripts/phase_gate_check.py` plus `dg_model_version` propagation — machine-checkable phase gates and leakage defense
6. Advanced portfolio modules (`covariance.py`, `portfolio.py`, `account_health.py`, `capacity.py`) only behind config flags

See `docs/agent-execution-plan.md`, `docs/adr/`, and the build plan addendum for full sequencing.

## Conventions

- Python 3.11+. Type hints everywhere. Dataclasses for interfaces between modules.
- All configurable values in `config/settings.yaml` or `config/books.yaml`.
- Secrets in `.env`. Never committed.
- Every module has unit tests. Target 80%+ coverage on core modules.
- Every function that does math has property-based or table-driven tests.
- No hardcoded magic numbers anywhere.
- Every bet decision is logged with full provenance (snapshot IDs, fair price, book price, edge, reason).
- Every new downstream artifact should carry an `inputs_hash`.
- Every workstream handoff should include a passing replay or smoke contract.
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
| `BankrollState` | risk | risk / monitoring |
| `ExposureReport` | risk | execution / monitoring |

## What NOT to do

- Do not build a custom golf model. Use DataGolf's forecasts.
- Do not automate bet placement (Phases 1-4 are all manual execution).
- Do not add markets, books, or tours before matchup MVP works.
- Do not tune parameters on backtest results without a holdout set.
- Do not use ROI as a signal over fewer than 100 bets. Use CLV instead.
- Do not override the risk engine. It has veto power over every bet.
- Do not hardcode any number that could reasonably need to change.
- Do not size on a point edge estimate once `edge_sd` exists. Use posterior Kelly.
- Do not relax quantitative phase-exit gates mid-phase. Re-commit before re-entry.

## Key files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Codex-local instructions for this subtree |
| `CLAUDE.md` | Claude-local instructions for this subtree |
| `config/settings.yaml` | All non-secret parameters |
| `config/books.yaml` | Book-specific rules and market config |
| `config/.env.example` | Template for secrets |
| `docs/agent-execution-plan.md` | Current workstream backlog and handoff contract |
| `docs/adr/` | Architecture decision records |
| `../skills/` | Shared agent skill sources |
| `../.codex/skills/` | Codex mirror of shared skills |
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
All phase-gate checks must pass before capital is increased.
