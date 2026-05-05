# UpAndDown Agent Execution Plan

**Purpose:** turn the current Phase 2 baseline into a paper-trading system with quant-grade auditability, without blowing up the MVP with premature complexity.

## 1. Current repo reality

| Workstream | Status | Evidence | Notes |
|---|---|---|---|
| WS-1 Foundation | Complete | `src/config.py`, `src/storage/`, `tests/unit/test_config.py`, `tests/unit/test_storage.py` | Good baseline. Do not reopen unless fixing a real defect. |
| WS-2 Ingestion | Complete | `src/ingestion/datagolf.py`, `src/ingestion/sportsbooks.py` | Sportsbook input is currently DG betting-tools shaped, not direct book APIs. |
| WS-3 Normalization | Complete | `src/normalization/odds.py`, `src/normalization/vig.py`, `src/normalization/players.py` | Core math exists and is tested. |
| WS-4 Pricing + Edge | Complete | `src/pricing/`, `src/risk/edge.py`, `tests/unit/test_pricing.py`, `tests/unit/test_edge.py` | Matchup, top-N, and outright baseline pricing exists. |
| WS-5 Risk baseline | Complete | `src/risk/sizing.py`, `src/risk/exposure.py`, `src/risk/drawdown.py` | Good MVP baseline, but not yet v0.2 quant-grade. |
| WS-6 Execution + Logging | In progress | `src/execution/tickets.py`, `src/execution/persistence.py`, `scripts/paper_trade.py`, `tests/integration/test_execution_persistence.py` | Ticket generation, manual placement logging, settlement helpers, and operator CLI commands exist. Continue with replay contracts and execution diagnostics. |
| WS-7 Backtesting | In progress | `src/backtest/leakage_guard.py`, `src/backtest/replay.py`, `src/backtest/summary.py`, `tests/replay/test_backtest_forecast_candidate_replay.py` | Initial leakage-checked replay spine exists for DataGolf forecast rows → candidate/ticket generation → settlement/CLV/reporting → multi-tournament summary. Broader historical data coverage remains open. |
| WS-8 Monitoring + Reporting | In progress | `src/monitoring/clv.py`, `src/monitoring/attribution.py`, `src/monitoring/reports.py`, `tests/integration/test_stored_report.py`, `tests/replay/test_phase3_paper_trade_replay.py` | CLV capture, stored paper-trade reporting, ticket detail, export, open-action views, first pinned replay contract, initial P&L attribution, and promo P&L separation exist. Phase-gate reporting remains deferred. |

## 2. Non-negotiable operating rules

1. Every new artifact must carry deterministic provenance via `inputs_hash`.
2. Every workstream handoff must include a smoke contract: fixture, command, and expected output shape.
3. Any change that alters bet selection or stake sizing must ship behind a config flag unless it is a bug fix.
4. Phase-exit gates are pre-committed. Do not loosen them mid-phase because results feel noisy.
5. Realized ROI is never a sufficient reason to retune the system on its own. Use CLV, calibration, and the explicit phase-gate metrics.

## 3. Priority execution order

### Batch A — Phase 3 paper-trading backbone

**Goal:** close the loop from `BetCandidate` to settled paper-trade record.

**Suggested file targets**
- `src/execution/tickets.py`
- `src/execution/placement.py`
- `src/execution/settlement.py`
- `src/monitoring/clv.py`
- `src/monitoring/reports.py`
- `scripts/paper_trade.py`

**Definition of done**
- System emits a paper-trade ticket from existing pricing and risk outputs.
- Manual placement logging records recommended line, obtained line, stake, timestamp, and rejection reason if unfilled.
- Settlement records outcomes in a schema that can support CLV and attribution later.
- One fixture-driven integration test covers candidate → ticket → placement log → settlement log.

**Current implementation notes**
- `scripts/paper_trade.py` supports smoke data creation, candidate ticketing, ticket detail display, ticket CSV export, placement, settlement, CLV capture, stored reporting, JSON report artifact output, readiness diagnostics, and open-action review.
- `docs/paper-trading-phase3-proof-runbook.md` defines the real operator-entered paper-trading proof workflow. Fixture and smoke rows are not Phase 3 gate evidence; the gate remains blocked until the real paper DB has at least 4 tournaments and 60 settled paper bets. Use `paper_trade.py readiness` to flag undersized samples and unresolved operator work before assembling gate artifacts.
- Operator smoke shape:
  - `PYTHONPATH=. .venv/bin/python scripts/paper_trade.py create-smoke-candidate --database-url sqlite:////private/tmp/upanddown-phase3-cli-smoke.db`
  - `PYTHONPATH=. .venv/bin/python scripts/paper_trade.py ticket-candidates --total-bankroll 25000 --database-url sqlite:////private/tmp/upanddown-phase3-cli-smoke.db`
  - `PYTHONPATH=. .venv/bin/python scripts/paper_trade.py show-ticket 1 --database-url sqlite:////private/tmp/upanddown-phase3-cli-smoke.db`
  - `PYTHONPATH=. .venv/bin/python scripts/paper_trade.py export-tickets --database-url sqlite:////private/tmp/upanddown-phase3-cli-smoke.db --unplaced --approved-only`
  - `PYTHONPATH=. .venv/bin/python scripts/paper_trade.py open-actions --database-url sqlite:////private/tmp/upanddown-phase3-cli-smoke.db`

### Batch B — Verifiability spine

**Goal:** make agent handoffs replayable instead of trust-based.

**Suggested file targets**
- `src/storage/hashing.py`
- `tests/replay/`
- `tests/fixtures/replay/`

**Definition of done**
- Canonical hashing exists for config slices, snapshot IDs, and interface payloads.
- `BetCandidate`, `BetTicket`, `PlacedBet`, and `BetOutcome` carry `inputs_hash`.
- Each completed workstream has at least one replay or smoke contract.
- Re-running the same fixture produces byte-stable output on repeated runs.

**Current implementation notes**
- `src/storage/hashing.py` provides deterministic canonical payload hashing.
- Execution and monitoring tables now include `inputs_hash` fields needed by the Phase 3 artifact chain.
- `tests/fixtures/replay/phase3_paper_trade.json` plus `tests/replay/test_phase3_paper_trade_replay.py` pins the Phase 3 candidate → ticket → placement → settlement → CLV manifest.
- `tests/fixtures/replay/datagolf_forecast_ingestion.json` plus `tests/replay/test_datagolf_forecast_ingestion_replay.py` pins DataGolf raw snapshot → persisted forecast rows → leakage-guard metadata with deterministic hashes.
- `tests/fixtures/replay/datagolf_pricing.json` plus `tests/replay/test_datagolf_pricing_replay.py` pins DataGolf forecast payload → fair-price batch for outrights, top-N, and make-cut without adding any custom model overlay.
- `tests/fixtures/replay/datagolf_matchup_normalization.json` plus `tests/replay/test_datagolf_matchup_normalization_replay.py` pins DataGolf betting-tools matchup payload → parsed book snapshot → normalized American/decimal/implied/no-vig odds using the multiplicative vig baseline.
- `tests/fixtures/replay/risk_edge_sizing.json` plus `tests/replay/test_risk_edge_sizing_replay.py` pins the first WS-5 risk contract from fair price → edge detection → baseline sizing, without changing current bet-selection or staking defaults.
- `tests/fixtures/replay/risk_candidate_generation_default.json` plus `tests/replay/test_risk_candidate_generation_default_replay.py` pins the default disabled-risk handoff from fair prices/book odds → edge detection → persisted candidates → ticketing. It proves candidate generation preserves threshold-only behavior when Batch C flags remain off.
- `tests/fixtures/replay/fdr_posterior_ticketing.json` plus `tests/replay/test_fdr_posterior_ticketing_replay.py` pins FDR annotation, persisted candidate risk metadata, and posterior-Kelly ticket sizing behind enabled risk flags.
- Additional replay fixtures for broader risk handoffs remain open.

### Batch C — Quant-risk floor from the v0.2 addendum

**Goal:** fix the three issues most likely to fail a buy-side risk review.

**Suggested file targets**
- `src/risk/posterior_kelly.py`
- `src/risk/ror.py`
- `src/risk/fdr.py`
- `scripts/phase_gate_check.py`
- ingestion and storage changes to propagate `dg_model_version`

**Definition of done**
- Edge objects carry both `edge_pct` and `edge_sd`.
- Fixed Kelly remains available, but posterior Kelly is the default test path behind config.
- RoR is reported at each phase review.
- Backtests can detect vendor-model leakage via `dg_model_version`.
- Phase 3, 4, and 5 exits are machine-checkable.

**Current implementation notes**
- `src/risk/posterior_kelly.py` provides the standalone posterior-Kelly math contract and `tests/unit/test_posterior_kelly.py` pins zero-uncertainty parity with current fractional Kelly, monotonic uncertainty shrinkage, and no-bet behavior when uncertainty overwhelms the fractional edge.
- `config/settings.yaml` exposes `sizing.posterior_kelly_enabled: false`; persisted candidate ticketing can now use posterior Kelly when enabled and `edge_sd` is present. Defaults preserve current fractional-Kelly ticket sizing.
- `src/risk/fdr.py` provides standalone one-sided edge p-values plus Benjamini-Hochberg FDR decisions and `tests/unit/test_fdr.py` pins p-value uncertainty behavior, monotonic pass sets as q increases, and single-candidate behavior.
- `config/settings.yaml` exposes `edge.fdr_enabled: false` with `edge.fdr_q_core` and `edge.fdr_q_convex`; `apply_fdr_control` can populate edge-level p-values and pass/fail decisions, and persisted candidate ticketing respects `passes_fdr` only when the flag is enabled. Defaults preserve current threshold-only bet selection.
- `src/risk/ror.py` provides a standalone bankroll-level Monte Carlo risk-of-ruin estimator and `tests/unit/test_ror.py` pins deterministic no-risk/no-ruin behavior, guaranteed-loss brake hits, seeded reproducibility, and higher-variance risk increases.
- `config/settings.yaml` exposes the default `ror` review shape: 100 future bets, 10,000 simulations, and a fixed seed for reproducible phase-gate artifacts.
- `scripts/phase_gate_check.py` evaluates the first quantitative Phase 3 -> 4 gate from persisted paper-trading metrics, explicit operator inputs for tournaments/crashes/data completeness, CLV bootstrap lower bound, and the RoR estimator. It supports stable JSON output with a deterministic `artifact_hash` for audit trails, can attach an optional WS-7 `--backtest-summary-json` artifact, and can persist the rendered review with `--output artifacts/phase-gate.json`. `tests/unit/test_phase_gate_check.py` pins pass/fail criteria, deterministic bootstrap behavior, phase-gate artifact hashing, backtest-summary attachment, and direct output writing.
- `src/backtest/leakage_guard.py` provides the first DataGolf model-version leakage check for backtests. It raises hard errors when forecasts are missing `dg_model_version`, captured after the simulated decision time, use unknown versions, or use versions before publication. `tests/unit/test_leakage_guard.py` pins those refusal paths.
- `src/ingestion/datagolf.py` now captures DataGolf model-version metadata on raw snapshots when present, and `src/ingestion/forecasts.py` persists pre-tournament forecast rows with `dg_model_version` and deterministic `inputs_hash`. `tests/unit/test_forecast_ingestion.py` verifies those rows feed the leakage guard directly.
- `EdgeResult` and `BetCandidate` now carry optional `edge_sd`, `p_value`, and `passes_fdr` metadata. Defaults preserve current threshold-only behavior; `tests/unit/test_edge.py` and `tests/unit/test_storage.py` pin the compatibility and storage contracts.
- `src/risk/candidate_generation.py` now converts real edge batches into persisted `BetCandidate` rows, applies FDR before persistence only when `edge.fdr_enabled` is true, and carries the annotated risk metadata plus deterministic candidate hashes into ticketing. `tests/unit/test_candidate_generation.py` pins disabled-default behavior, enabled FDR gating, and player-map refusal paths.

### WS-7 — Backtesting spine

**Goal:** replay historical decisions without vendor-model leakage or custom golf-model overlays.

**Current implementation notes**
- `src/backtest/replay.py` replays persisted DataGolf forecast rows against explicit historical book lines, runs `leakage_guard` before pricing, converts DataGolf probabilities directly into fair prices, and then uses the normal edge → candidate → ticket path.
- `settle_backtest_replay` places approved replay tickets with `placement_method="backtest"`, records historical outcomes, optional CLV, and returns the existing stored paper-trade report shape.
- `tests/fixtures/replay/backtest_forecast_candidate_replay.json` plus `tests/replay/test_backtest_forecast_candidate_replay.py` pins the first WS-7 replay contract from forecast rows/book lines → leakage guard → candidates → tickets → settlement → CLV/report.
- `tests/unit/test_backtest_replay.py` verifies replay success, leakage refusal, missing forecast refusal, replay-local ticketing, settlement/report creation, and missing settlement refusal.
- `scripts/backtest_replay.py` runs one fixture-backed, leakage-checked replay into a fresh event database and emits the stable replay manifest. It refuses non-empty event DBs to preserve deterministic IDs and artifact hashes. Use `--output artifacts/replay.json` to persist the manifest while still printing it for operator review.
- `tests/fixtures/replay/backtest_multi_market_core_replay.json` broadens WS-7 replay coverage to FanDuel top-10/top-20 core markets with mixed approved/rejected tickets, settlement, CLV, and stable manifest hashes.
- `src/backtest/summary.py` aggregates event-level stored reports into weighted multi-tournament totals, ROI, edge, CLV, and tournament-count diagnostics.
- `tests/fixtures/replay/backtest_multi_tournament_summary.json` plus `tests/replay/test_backtest_multi_tournament_summary_replay.py` pins the multi-tournament summary contract.
- `scripts/backtest_review.py` builds text or stable JSON review artifacts from repeated `--event label=database_url` inputs, with deterministic `summary_hash` and `manifest_hash`. It refuses empty event DBs so typo paths cannot become zeroed review evidence. Use `--output artifacts/backtest-review.json`; the JSON file is the intended input for `scripts/phase_gate_check.py --backtest-summary-json`.
- `scripts/artifact_bundle.py` builds the small review-bundle index over replay, backtest-review, paper-report, and phase-gate JSON artifacts. It records rendered-file SHA-256 values plus embedded artifact hashes and emits a deterministic `bundle_hash`.
- `tests/fixtures/replay/backtest_top5_outright_replay.json` adds DraftKings top-5 and outright-win coverage, including a convex-sleeve approved ticket, mixed approvals, settlement, and CLV.
- `tests/integration/test_backtest_artifact_workflow.py` proves the full manual artifact chain can produce replay, three-event backtest-review, paper-report, phase-gate, and review-bundle JSON files from fresh temp databases.
- `docs/backtest-artifact-runbook.md` gives the operator command sequence for replay manifest → multi-event review → phase-gate attachment → review bundle, including the expected failure shape for undersized smoke paper DBs.
- Broader historical data coverage remains open. Phase-gate review artifacts can now attach a leakage-checked multi-tournament backtest summary, but no backtest metrics are gate criteria yet.

### Batch D — Measurement honesty

**Goal:** separate model quality from execution noise and promo subsidies.

**Suggested file targets**
- `src/monitoring/attribution.py`
- execution schema additions for realized vs. raw P&L

**Definition of done**
- Execution shortfall is logged against the recommended ticket, not inferred later.
- Boosts and promos are tagged and excluded from raw CLV.
- Reports show model alpha, execution drift, sizing contribution, and residual variance separately.

**Current implementation notes**
- `src/monitoring/attribution.py` decomposes settled paper-trade P&L into model alpha, execution drift, sizing alpha, and variance.
- `bet_attribution` stores one append-only attribution row per settled bet with deterministic `inputs_hash`.
- `scripts/paper_trade.py record-attribution <bet_id>` records attribution manually after settlement; `persist-smoke` records it as part of the sample chain.
- Stored reports aggregate attribution totals when attribution rows exist.
- `placed_bets.bet_class` and `boost_terms_json` identify standard, boosted-odds, free-bet, and risk-free bets.
- `bet_outcomes` stores raw strategy P&L separately from realized promo-adjusted P&L.
- Stored reports show strategy P&L, promo P&L, realized P&L, strategy ROI, and realized ROI. CLV and attribution remain tied to raw strategy performance.

### Batch E — Advanced portfolio controls

**Goal:** add portfolio realism without destabilizing the baseline.

**Suggested file targets**
- `src/risk/covariance.py`
- `src/risk/portfolio.py`
- `src/risk/account_health.py`
- `src/execution/capacity.py`

**Definition of done**
- All modules are disabled by default behind config flags.
- A fallback path preserves existing per-bet risk behavior when advanced controls fail.
- Parallel backtests show no regression before any flag flips to default-on.

## 4. Handoff contract for future agents

Every meaningful handoff should include:

1. The exact files touched and any config keys added.
2. The fixture or command that proves the work (`pytest ...`, replay test, or smoke script).
3. The output artifact or table shape the next workstream can rely on.
4. The open risks that remain intentionally deferred.

## 5. Things to defer on purpose

- Do not build a custom golf model.
- Do not add live execution or book APIs yet.
- Do not make covariance-QP the default before the baseline paper-trading loop is stable.
- Do not optimize thresholds on realized ROI from a small sample.
