# UpAndDown — Agent Project Charter

## What this is

A systematic golf edge and strategy-validation framework. DataGolf provides
the model. The system translates forecasts into fair prices, finds daily edges
against sportsbook lines, makes those edges easy to review in an operator UI,
backtests the strategy, and tracks a bounded paper-bet sample to justify
whether the strategy deserves real capital.

## Core philosophy

**Survival first. No-bet is the default.** Small repeatable edges in
matchup markets. Tiny convex sleeve for outrights. Never compromise the bankroll.

This is not meant to become a full personal betting-history tracker. Long-term
real bet records can live in dedicated tracking apps and be imported later for
analysis. UpAndDown should excel at edge discovery, backtest visualization, and
paper-trading proof.

## Current status

- **Phase 2 baseline is complete.** Pricing, edge detection, and baseline risk controls exist and are tested.
- **Phase 3 is underway.** Ticket generation, minimal manual paper-placement logging, settlement helpers, CLV capture, paper-proof reports, readiness diagnostics, initial P&L attribution, promo P&L separation, and phase-gate artifact checks now exist. Daily edge UI and backtest visualization are now first-priority Phase 3 product work. The gate remains data-blocked until real operator-entered paper trading reaches the required sample.
- **v0.2 quant-risk upgrades are partially wired behind disabled flags.** Candidate generation now carries FDR/posterior-Kelly metadata into ticketing, DataGolf model versions propagate into leakage-checked replays, and RoR is available for phase-gate artifacts. Risk flags remain off while the paper-trading backbone proves the path.

## What is already built

1. `src/config.py`, `src/storage/`, `scripts/init_db.py` — foundation, config, schema, and DB lifecycle
2. `src/ingestion/datagolf.py`, `src/ingestion/sportsbooks.py` — DataGolf ingestion and odds snapshot parsing
3. `src/normalization/odds.py`, `src/normalization/vig.py`, `src/normalization/players.py` — core normalization math
4. `src/pricing/` — matchup, top-N, outright pricing baseline
5. `src/risk/edge.py`, `src/risk/sizing.py`, `src/risk/exposure.py`, `src/risk/drawdown.py` — baseline edge and risk engine
6. `src/execution/`, `src/monitoring/`, `scripts/paper_trade.py` — initial Phase 3 paper-trading backbone
7. `src/backtest/leakage_guard.py`, `src/backtest/replay.py`, `src/backtest/summary.py` — initial WS-7 leakage-checked replay, settlement, and multi-tournament summary spine
8. `scripts/phase_gate_check.py`, `scripts/backtest_replay.py`, `scripts/backtest_review.py`, `scripts/artifact_bundle.py` — deterministic review artifacts for Phase 3 and WS-7 audit handoffs
9. `scripts/run_pipeline.py` — end-to-end fetch → price → edge → persist pipeline that feeds the paper-trading loop for matchup markets, core yes-market proofs (`top_20`, `top_10`, `top_5`, `make_cut`), and the `outright_win` convex proof market
10. `src/marketmaking/`, `scripts/mm_simulate.py` — WS-9 prediction-market market-making scaffold (Bayesian fair-value bands, posterior-driven quoting with inventory skew, hard-veto risk engine, seeded simulator with P&L attribution). Simulator-only until the gates in `docs/prediction-market-mm-spec.md` pass.
11. `scripts/export_control_plane_status.py` — publishes per-pod status files (contract v1.0) consumed by the workspace-level `control-plane/` daily dashboard
12. `src/fantasy/splash/integrity.py`, `scripts/splash_preflight.py` — WS-11/SP-1 Splash preflight integrity gate: fail-closed fixture validation (tier anchor coverage, mappings, anchor sanity, freshness) with remediation hints, run before any portfolio generation. Sequencing for SP-2..SP-5 in `docs/splash-bulletproof-plan.md`.

## What to build next

1. **Make daily edges easy to review.** Run `scripts/run_pipeline.py` every tournament week, persist candidates, and keep improving the operator UI so fair price, book price, edge, staleness, and recommended action are visible without digging through CLI output.
2. **Broaden and visualize WS-7 backtests.** Historical strategy replay should produce reviewable charts/tables for ROI, CLV, drawdown, market breakdown, edge buckets, and sample size diagnostics.
3. **Accumulate bounded paper-trading evidence.** Use `scripts/paper_trade.py` or `scripts/operator_console.py` to track enough paper bets for the Phase 3 proof gate (>=60 settled bets, >=4 tournaments), including CLV and attribution.
4. Keep exporting paper-report, phase-gate, and review-bundle artifacts for manual audit.
5. Treat real-money bet history as an import/analysis surface, not a core tracking product. Advanced portfolio modules (`covariance.py`, `portfolio.py`, `account_health.py`, `capacity.py`) stay behind config flags.

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
- Do not build a full betting-history product in MVP. Capture only the paper-trade and shadow-live records needed for validation, CLV, attribution, and auditability.
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
  ├─ Daily edge review UI
  ├─ Bet ticket output for paper validation
  ├─ Minimal manual paper placement/settlement records
  ├─ CLV tracker
  └─ Backtest and paper-proof reports

Phase 4: Shadow Live (real bets at minimum stakes)
Phase 5: Full Capital Deployment
Phase 6: Iteration + Expansion
```

## Success metric

Primary product success is an operator can open the tool during a tournament
week, see the day's best DataGolf-anchored edges, inspect backtest evidence for
the strategy, and compare that evidence against a clean paper-bet proof sample.

Quant success remains positive aggregate CLV over 50+ paper bets across 8+
tournaments. ROI is tracked but not used as a signal below 100 bets. All
phase-gate checks must pass before capital is increased.
