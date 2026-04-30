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
| WS-6 Execution + Logging | Open | `src/execution/__init__.py` only | Highest-value next work. |
| WS-7 Backtesting | Open | `src/backtest/__init__.py` only | Wait until WS-6 logging contracts are defined. |
| WS-8 Monitoring + Reporting | Open | `src/monitoring/__init__.py` only | CLV and reporting depend on WS-6 data shape. |

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

### Batch D — Measurement honesty

**Goal:** separate model quality from execution noise and promo subsidies.

**Suggested file targets**
- `src/monitoring/attribution.py`
- execution schema additions for realized vs. raw P&L

**Definition of done**
- Execution shortfall is logged against the recommended ticket, not inferred later.
- Boosts and promos are tagged and excluded from raw CLV.
- Reports show model alpha, execution drift, sizing contribution, and residual variance separately.

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
