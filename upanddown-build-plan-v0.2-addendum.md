# UpAndDown Build Plan — v0.2 Addendum

**Version:** 0.2 (extends v0.1)
**Date:** 2026-04-29
**Status:** Proposed
**Reviewer lens:** Senior buy-side quant trader / risk
**Relationship to v0.1:** Additive only. Nothing in v0.1 is deleted. Each section below references the v0.1 location it amends.

---

## 0. How to read this addendum

The v0.1 plan is solid. The structural decisions — Spitznagel survival framing, two-sleeve construction, CLV as primary diagnostic, walk-forward backtests, manual execution, DataGolf as anchor, no parlays — are the right calls and would not be touched by a buy-side risk committee.

Product-objective clarification adopted after v0.2: UpAndDown should not compete
with dedicated bet-tracking apps. The quant-risk upgrades below remain useful,
but they should support daily edge review, reproducible backtests, bounded
paper-trading proof, and later imported real-history analysis rather than a
full in-house betting ledger.

What a risk committee *would* push back on is in five categories: (1) Kelly is treated as if the edge estimate were known, when in practice it is the noisiest input; (2) "correlation" is handled by name match instead of as a covariance object; (3) the vendor-model versioning gap is a silent leakage source the plan does not catch; (4) execution and promo accounting are footnotes when they belong in the P&L attribution; (5) the agent decomposition is good prose but not yet *verifiable*.

The ten improvements below address those five categories. Each one is sized to an additional skill (or amendment to an existing skill) and is testable on its own. None requires a redesign of an existing module.

A second principle: every improvement here is justified by **risk reduction or measurement honesty**, not sophistication for its own sake. A 0.25-Kelly system on a clean baseline beats a "factor-aware portfolio-optimized" system that has a leakage bug. We are bolting on the upgrades the v0.1 plan can structurally absorb without losing its discipline.

---

## 1. Summary of changes

| # | Improvement | Amends v0.1 section | Risk category |
|---|-------------|---------------------|---------------|
| 1 | Edge-uncertainty-aware Kelly (posterior-Kelly) and explicit risk-of-ruin (RoR) calculation | §6.9, §9.2, ADR-005 | Sizing / survival |
| 2 | Portfolio-level covariance optimization replaces per-name correlation aggregation | §4.7, §6.10 | Correlation / concentration |
| 3 | Vendor model versioning (DataGolf model_version pinning, leakage detector) | §4.1, §6.1, §11.2 | Leakage |
| 4 | Implementation shortfall as first-class metric, with P&L attribution | §4.8, §6.13, §11.3 | Execution / measurement |
| 5 | Multiple-comparisons correction on edge thresholds (FDR control) | §4.6, §6.8 | False-discovery |
| 6 | Reproducibility hashes and replay contracts for agent verification | §5, §7 (workstreams) | Agent-friendliness / auditability |
| 7 | Capacity / line-impact model, with stake decay above book limits | §6.2, §6.9, §13.1 | Execution realism |
| 8 | Promo / boost / free-bet accounting separated from CLV | §6.12, §6.13 | Measurement honesty |
| 9 | Quantitative phase-exit gates (replaces qualitative exit criteria) | §14, §15 | Operational gating |
| 10 | Account-longevity model (book-limit risk as a stake-decaying constraint) | §6.10, §13.2 | Strategy capacity |

---

## 2. Improvement 1: Edge-uncertainty Kelly + risk-of-ruin

**Gap.** v0.1 §6.9 sizes via fractional Kelly with a fixed 0.25 multiplier. This is the standard heuristic and it's defensible, but it implicitly assumes the edge estimate is a point. Kelly is famously sensitive to edge mis-estimation: a 4% true edge with ±2% standard error around the estimate is a very different bet from a 4% edge known precisely. The 0.25 multiplier hides this rather than measuring it. ADR-005 ties bankroll philosophy to Spitznagel's survival framing but does not connect that framing to a quantified probability of ruin.

**Fix.** Two additions, neither of which removes the existing module.

First, a `posterior_edge` upstream of sizing. For every `BetCandidate`, the pricing module emits not just `edge_pct` but `(edge_mean, edge_sd)`. The standard deviation is sourced from three measurable inputs that are already in the system: (a) DataGolf calibration error in this market type from prior tournaments, (b) data freshness penalty (older book line → wider posterior), and (c) sample-CLV uncertainty for this market type. None of these requires a new model — they are all empirical.

Second, the Kelly fraction becomes a function of edge uncertainty rather than a fixed 0.25. The cleanest closed form is the certainty-equivalent log-utility stake under a Normal posterior on edge: `f* = (μ_edge − σ_edge²) / (b)`, where b is the decimal odds minus one. When σ_edge is small, this collapses to standard Kelly. When σ_edge is large, the term `−σ²` automatically shrinks the stake. A floor of 0.10 Kelly and a ceiling of 0.40 Kelly bracket the result.

Third, a standalone `risk/ror.py` that runs a Monte Carlo simulation over the assumed edge-and-variance regime (parameters from current calibration) and reports the probability of triggering the −25% paper-trade brake or the −35% halt over the next 100 bets. This is run at every phase exit and pinned to the phase decision artifact.

**Deliverables.**
- `src/risk/posterior_kelly.py` — turns `(edge_mean, edge_sd, odds)` into a Kelly fraction.
- `src/risk/ror.py` — Monte Carlo RoR estimator, callable as `ror.estimate(config, prior_calibration) -> dict`.
- Amendment to `BetCandidate`: add `edge_sd: float` field. Amendment to `BetTicket`: log `kelly_fraction_used` (already there) plus `edge_sd_used` and `posterior_kelly_components`.

**Tests.**
- Property: As `edge_sd → 0`, `posterior_kelly == standard_kelly × user_fraction`.
- Property: As `edge_sd` increases, stake monotonically decreases.
- Unit: A 4% edge with σ=2% should produce a meaningfully smaller stake than σ=0.5%, hand-calculated.
- Backtest invariant: across the 20-tournament backtest, posterior-Kelly should produce smaller average stake than fixed 0.25 Kelly when calibration data is sparse, and should converge to it once calibration data accumulates.

**ADR addition.** ADR-011 — "Kelly under edge uncertainty." Documents the choice of certainty-equivalent over alternatives (e.g., shrinkage estimator, Bayesian Kelly with a beta prior on win probability) and ties it back to the Spitznagel survival framing in ADR-005.

---

## 3. Improvement 2: Portfolio-level covariance

**Gap.** v0.1 §4.7 and §6.10 handle correlation by aggregating exposure by golfer name. This catches "I bet Scheffler in three different markets" but misses (a) two golfers in the same matchup share weather and course, (b) outright + top-10 bets on the same player double-count, (c) multiple golfers exposed to the same factor (links specialists, bombers). The plan acknowledges this as a known limitation in §6.10 but does not propose a structural fix.

**Fix.** Add a covariance-aware portfolio construction step between edge detection and sizing, run **once per tournament** rather than per bet. The math is small and tractable for the bet count involved (typically 10-30 candidates per week).

Construction:
1. For each pair of bet candidates, estimate `Corr(payoff_i, payoff_j)` using DataGolf's simulation outputs. DataGolf publishes per-player finish distributions; correlations between bet outcomes can be estimated by running 10k-sim Monte Carlo over the field once per tournament and computing the joint distribution of bet payoffs.
2. Solve a small QP: maximize Σ (stake_i × edge_i) − λ × stake' Σ stake, subject to all the existing v0.1 hard caps (single bet ≤ 2%, tournament ≤ 5%, golfer ≤ 3%, book ≤ 60%, sleeve budgets, minimum book bet sizes).
3. λ is set so that the unconstrained solution recovers single-bet posterior Kelly when bets are uncorrelated. This makes the new module a strict superset of the old behavior on the no-correlation case.

This is a portfolio-level upgrade: it tells you to bet less on Bet 5 because Bet 2 already captures the same factor, even if neither violates a per-bet cap.

**Deliverables.**
- `src/risk/covariance.py` — produces a tournament-level covariance matrix from DataGolf simulations.
- `src/risk/portfolio.py` — solves the QP. Library: `scipy.optimize.minimize` with SLSQP, or `cvxpy` (cleaner). No new heavy dependencies.
- Amendment to §6.10: per-bet correlation aggregation remains as a fallback when the QP fails to solve or when only one candidate exists.

**Tests.**
- Sanity: Independent bets (zero off-diagonal covariance) should produce identical stakes to per-bet posterior-Kelly.
- Sanity: Two perfectly correlated bets (same outcome from a recombination) should be sized as one bet of equivalent edge.
- Property: All existing v0.1 hard caps still bind.
- Backtest invariant: portfolio Sharpe over 20 tournaments should be ≥ per-bet sizing Sharpe, on the same bet candidates.

**ADR addition.** ADR-012 — "Portfolio construction over per-bet sizing." Explicitly notes when to fall back to per-bet sizing (single candidate, QP non-convergence, covariance estimation failure).

**Risk callout.** This is the single largest math change. To de-risk: ship the QP module behind a config flag (`risk.portfolio.enabled: false` by default) so it can be A/B'd against the per-bet logic during paper trading.

---

## 4. Improvement 3: Vendor model versioning and leakage detection

**Gap.** This is the leakage source v0.1 does not catch. DataGolf updates its model continuously: weights are retrained, new features are added, the same player's "win probability" today reflects a different model than the one available three months ago. v0.1 §11.2 lists "using future DataGolf forecasts" as a leakage risk, but a backtest can also leak by using *today's model output on yesterday's data* — which is what happens by default if you replay the backtest after DG ships an update.

**Fix.** Three structural changes, all small.

First, every `raw_datagolf_snapshot` carries a `dg_model_version` field, populated from a DataGolf endpoint header or — if DG doesn't expose it — by hashing the snapshot's calibration column and pinning that as the version proxy.

Second, the backtester refuses to use a forecast whose `dg_model_version` was not yet published at the simulated decision time. This is a hard error, not a warning.

Third, calibration tracking is segmented by `dg_model_version`. If DG ships a new model mid-season, calibration metrics from before the change are flagged as not directly comparable.

**Deliverables.**
- Schema amendment: add `dg_model_version` to `forecasts` and `raw_snapshots` (already in §12.2 — just add the column).
- `src/backtest/leakage_guard.py` — version-aware filtering of forecasts.
- Calibration reports key by `(market_type, dg_model_version)` instead of `market_type`.

**Tests.**
- Leakage: Inject a forecast with a future `dg_model_version` into a backtest run; the backtester must refuse to use it (hard error, not a warning).
- Calibration regression: After DG ships a new version, the system should correctly segment historical calibration metrics by version.

**ADR addition.** ADR-013 — "Vendor model versioning." Notes that this is the most subtle leakage source we can identify a priori.

---

## 5. Improvement 4: Implementation shortfall as a first-class metric

**Gap.** v0.1 §4.8 records "actual odds, actual stake, and any notes (line moved, bet rejected, etc.)" — useful data, but not surfaced in the P&L attribution. v0.1 §11.3 lists ROI, CLV, calibration, drawdown, Sharpe — the standard sports-betting set. None of these isolate execution drift from model error from sizing error from variance.

**Fix.** Decompose every settled bet into four P&L components. Buy-side equities calls this implementation shortfall analysis; in a betting context the math is direct.

For each placed bet:
- **Model α**: P&L attributable to fair price beating the market's no-vig price at decision time. Computed as `(fair_prob − book_no_vig_prob_at_decision) × stake / (decimal_odds − 1)`.
- **Execution drift**: P&L attributable to the difference between the line the system recommended and the line actually obtained. Computed as `(stake × actual_odds − stake × recommended_odds) × outcome_indicator`.
- **Sizing α**: P&L attributable to bet-sizing decisions versus a flat-stake counterfactual at the sleeve average. Useful for evaluating Kelly tuning.
- **Variance**: residual. By construction, it sums to zero in expectation over a large enough sample.

This is now reported alongside ROI and CLV. The first two months of paper trading will be dominated by Variance, which is fine — the point is to *measure* the others as data accumulates.

**Deliverables.**
- `src/monitoring/attribution.py` — four-way P&L decomposition.
- Weekly report adds an "Attribution" section underneath the existing CLV section.
- New table: `bet_attribution` with one row per settled bet.

**Tests.**
- Conservation: model + execution + sizing + variance = realized P&L exactly, for every bet.
- Unit: a bet placed at exactly the recommended line has zero execution drift.
- Unit: a bet at flat-stake parity has zero sizing α.

---

## 6. Improvement 5: Multiple-comparisons / FDR control on edges

**Gap.** v0.1 §4.6 and §6.8 detect edges with a configurable threshold (default 3% core, 8% convex). For a tournament with 100 markets across multiple books, even a perfectly calibrated model will produce some positive-edge candidates by sampling noise alone. The system has no mechanism to distinguish "real" edges from "many-tests-many-flags."

**Fix.** Apply Benjamini-Hochberg false-discovery-rate control to candidate ranking. For each tournament, treat the candidate list as a set of hypothesis tests (H0: edge = 0). Compute a p-value per candidate using the candidate's edge size, edge SD (from Improvement 1), and the prior calibration of this market type. Apply BH at FDR = q (configurable; default 0.20 for core, 0.10 for convex).

Candidates that pass the absolute edge threshold AND the FDR threshold are eligible for sizing. Candidates that pass only one or the other are logged as "marginal" and not bet, so we can audit them retrospectively.

This explicitly tightens the bet count and is consistent with v0.1 §11.3's "Bet volume: 5-15 (suspiciously high = model is too loose)" — that comment is the right intuition, formalized here.

**Deliverables.**
- `src/risk/fdr.py` — BH procedure.
- Amendment to `BetCandidate`: add `p_value: float` and `passes_fdr: bool`.
- Configuration: `risk.fdr.q_core` and `risk.fdr.q_convex` in `settings.yaml`.

**Tests.**
- Property: As FDR q increases, the set of `passes_fdr=True` candidates is monotonically larger.
- Property: As candidate edge SD shrinks (more confident), p-values shrink.
- Edge case: Single candidate — BH reduces to a single-test correction (i.e., no penalty), which is the right behavior.

---

## 7. Improvement 6: Reproducibility hashes and replay contracts

**Gap.** v0.1 §7 decomposes work into eight workstreams that agents can build independently. The interfaces (RawSnapshot, NormalizedOdds, etc.) are typed but not *verifiable*. There is no contract that lets a verification agent confirm "the FairPrice produced today on inputs X is bit-identical to the FairPrice produced six months ago on the same inputs." This matters because (a) it's the cheapest form of regression test, (b) it lets agents verify their own work without re-reasoning end-to-end, (c) it's the foundation for blameable bugs ("the input hash matches but the output differs — therefore the change is in module M").

**Fix.** Every artifact in the system carries an `inputs_hash` field. The hash is the SHA-256 of a deterministic serialization of all upstream snapshot IDs, the relevant config slice, and the code version (git SHA of `src/`). Replay tests are then trivial: re-run the pipeline on the same inputs; assert byte-equal outputs.

This is bolt-on. The dataclasses in v0.1 §5 don't change in shape, only gain a hash field.

In addition: every workstream in §7 gets a "smoke contract" — a tiny fixture-driven script that runs the workstream end-to-end and writes its `inputs_hash → output_hash` mapping. An agent finishing a workstream must produce a green smoke contract before handoff. The next agent can verify it without re-reasoning the implementation.

**Deliverables.**
- `src/storage/hashing.py` — canonical serialization and hash function.
- Amendment to every interface dataclass: add `inputs_hash: str`.
- `tests/replay/` — fixture-driven replay tests, one per workstream.
- Workstream handoff document template requiring a passing smoke contract.

**Tests.**
- Determinism: Same inputs → same hash, across processes and across days.
- Bit-equality: Replay on captured inputs produces byte-identical outputs.
- Cross-version flag: When git SHA changes, the hash changes (so we know not to compare across code versions).

---

## 8. Improvement 7: Capacity / line-impact model

**Gap.** v0.1 §13.1 acknowledges that book odds change. It does not model the fact that placing a non-trivial bet at a retail book *moves the line you placed at* (especially at smaller books and on smaller markets), or that books impose limits that scale by market and account. Paper trading will look better than live until this gap closes.

**Fix.** A capacity model that takes `(book, market_type, side)` and returns `(max_stake, expected_line_decay)`. For MVP, the values are conservative defaults from public knowledge — DK and FD posted limits on PGA matchups are typically in the low four figures pre-tournament; outrights are smaller. Once Phase 4 (Shadow Live) accumulates data on actual fills and observed line movement after fill, the values are updated empirically.

The risk engine then caps stake at `min(posterior_kelly_stake, hard_caps, capacity_limit)`. If the posterior-Kelly stake exceeds capacity, the system either splits across books (if same line available elsewhere) or scales the candidate.

**Deliverables.**
- `src/execution/capacity.py` — returns capacity per `(book, market_type, edge_band)`.
- `config/books.yaml` gets a `capacity_defaults` section per book.
- Capacity is logged on every `BetTicket` so we can backtest the policy later.

**Tests.**
- Unit: At a 5% edge on a $5k bankroll, posterior-Kelly recommends $400 but capacity is $200 → ticket records both `recommended_stake` and `capacity_capped_stake`.
- Integration: Phase 4 shadow-live data feeds back into capacity estimates.

---

## 9. Improvement 8: Promo / boost / free-bet accounting

**Gap.** Books offer profit boosts, odds boosts, and free bets. These materially change real-world ROI but distort CLV-based diagnostics if not separated. v0.1 has no accounting for them, which means a subsidized winning quarter could mask a deteriorating model — and a subsidy-driven losing quarter could trigger drawdown brakes that aren't really warranted.

**Fix.** Every placed bet has a `bet_class` enum: `STANDARD`, `BOOSTED_ODDS`, `FREE_BET`, `RISK_FREE`. P&L is tracked in two columns: `pnl_raw` (what the bet would have paid at standard odds and standard stake) and `pnl_realized` (what actually settled). CLV is computed only on `pnl_raw`. ROI is reported both ways, with the boost-attributable component called out.

Boosts are *not* a sizing input. The pricing engine and edge detector use the standard line. Boosts are book promos and don't reflect model edge.

**Deliverables.**
- Schema: add `bet_class`, `boost_terms_json`, `pnl_raw`, `pnl_realized` to `placed_bets` / `bet_outcomes`.
- Weekly report has a "Promo P&L" line, separated from "Strategy P&L".

**Tests.**
- Unit: A standard bet has `pnl_raw == pnl_realized`.
- Unit: A profit-boosted bet at +50% has `pnl_realized = 1.5 × pnl_raw` on win, equal on loss.
- Unit: A free bet returns `pnl_raw - stake` on win (since stake isn't returned), `0` on loss.

---

## 10. Improvement 9: Quantitative phase-exit gates

**Gap.** v0.1 §14 and §15 list phase exit criteria. Most are concrete (`make test passes`, `raw and normalized data exists`), but the high-stakes ones — the gates between paper, shadow live, and full deployment — are qualitative ("CLV is documented", "no operational failures"). An agent or operator under pressure can argue around qualitative gates.

**Fix.** Replace the qualitative phase-exit gates with numerical thresholds, each tied to the metrics already produced by Improvements 4 and 5.

| Phase exit | v0.1 criterion | v0.2 quantitative gate |
|------------|---------------|------------------------|
| Phase 3 → 4 | "CLV distribution is documented. No system crashes." | All of: (a) ≥ 4 tournaments paper-traded; (b) ≥ 60 paper bets settled; (c) point estimate aggregate CLV ≥ 0; (d) lower bound of 90% bootstrap CI on CLV ≥ −0.5%; (e) zero pipeline crashes; (f) data completeness ≥ 95% per tournament; (g) RoR estimate ≤ 5% of hitting −25% over the next 100 bets. |
| Phase 4 → 5 | "20+ real bets. Actual execution matches paper closely." | All of: (a) ≥ 25 real bets at minimum stakes; (b) point estimate live CLV ≥ 0; (c) execution drift attribution ≥ −0.5% (i.e., we're getting the lines we recommend within 50 bps on average); (d) live CLV − paper CLV within 1 SE; (e) book-rejection rate ≤ 10%. |
| Phase 5 review | "50+ bets. CLV data supports continue/adjust/stop." | All of: (a) ≥ 60 settled live bets; (b) CLV t-stat ≥ 1.0; (c) execution drift ≥ −1.0%; (d) max drawdown within RoR forecast 95% bound; (e) attribution decomposition shows model α ≥ execution drift in absolute value. Below any threshold → predefined action (see ADR-014 below). |

These gates are explicit, falsifiable, and computable from existing reports. A verification agent can check them.

**Deliverables.**
- ADR-014 — "Phase-exit decision rules." Notes that the gates are pre-committed before the phase begins and may not be relaxed mid-phase.
- A `scripts/phase_gate_check.py` that runs the relevant computations and outputs PASS / FAIL per criterion.

---

## 11. Improvement 10: Account-longevity model

**Gap.** v0.1 §13.2 acknowledges book limiting as an operational risk. v0.1 §6.10 caps per-book exposure at 60% of active capital — a static cap. In reality, sustained CLV-positive activity at a retail book leads to limits, and once limited, the strategy's effective capacity collapses. Treating book longevity as binary ("limited / not limited") is too coarse.

**Fix.** Every book has an `account_health` state: `HEALTHY`, `MILD_DECAY`, `RESTRICTED`, `LIMITED`. State is inferred from the book-rejection rate, observed stake limits, and time since account opened. Stake sizing is multiplied by a longevity factor in `[0.3, 1.0]` keyed on state — a `MILD_DECAY` account gets 0.7× stakes to extend its useful life, a `RESTRICTED` account gets 0.3× and is flagged for retirement.

Crucially: this is *also* a portfolio constraint. If the system would otherwise bet $200 at DraftKings but DK is in `MILD_DECAY`, it should bet $140 at DK and try $60 at FanDuel rather than the full $200 at DK. This is naturally expressed in the QP from Improvement 2.

**Deliverables.**
- `src/risk/account_health.py` — state machine with transitions logged and reviewable.
- Amendment to v0.1 §6.10: per-book cap is now `min(60%, longevity_factor × 60%)`.
- Weekly report has a "Book health" section.

**Tests.**
- Unit: state transitions trigger correctly on configured signals.
- Integration: `MILD_DECAY` books receive smaller stakes than `HEALTHY` books for the same edge.

---

## 12. Patches to v0.1 sections

This section gives the precise edits an agent should make to v0.1 if and when this addendum is adopted. Expressed as section-level deltas; not literal git patches because v0.1 may be edited concurrently.

**§4.1 Data Ingestion.** Add: "Each DataGolf snapshot also captures `dg_model_version` (from API metadata or, as fallback, a hash of the snapshot's player calibration column). The version is propagated through every downstream artifact." (Improvement 3.)

**§4.6 Edge Detection.** Add: "Edge candidates carry both an `edge_pct` and an `edge_sd` (Improvement 1). Candidates pass to sizing only if they clear both the absolute edge threshold and a Benjamini-Hochberg FDR threshold (Improvement 5). Candidates that pass one but not both are logged as `marginal` and not bet." (Improvements 1, 5.)

**§4.7 Bankroll and Exposure Engine.** Add: "Sizing is performed once per tournament at portfolio level (QP solver maximizing Σ stake_i × edge_i − λ × stake'Σstake under all hard caps), with per-bet posterior Kelly as fallback when the QP fails. Capacity and account-health constraints are entered as additional bounds." (Improvements 1, 2, 7, 10.)

**§4.8 Execution Layer.** Add: "Every settled bet records the four-way attribution decomposition: model α, execution drift, sizing α, residual variance. Reports surface attribution alongside ROI/CLV." (Improvement 4.) Add: "Promo / boost / free-bet bets are tagged with `bet_class` and tracked in two P&L columns (`pnl_raw` and `pnl_realized`). CLV is computed on `pnl_raw` only." (Improvement 8.)

**§5 Repository structure.** Add files under `src/risk/`: `posterior_kelly.py`, `ror.py`, `covariance.py`, `portfolio.py`, `fdr.py`, `account_health.py`. Add `src/execution/capacity.py`. Add `src/monitoring/attribution.py`. Add `src/storage/hashing.py`. Add `tests/replay/`.

**§6.9 Bankroll Sizing.** Replace "Kelly fraction (default 0.25x)" with "Kelly fraction defaults to certainty-equivalent posterior Kelly bracketed in [0.10, 0.40]; legacy fixed-0.25 mode remains available via `risk.kelly.mode: fixed`." (Improvement 1.)

**§6.10 Exposure and Concentration Control.** Replace "start simple (per-golfer aggregation) and add sophistication later" with "v0.2 ships portfolio-QP. Per-name aggregation remains as fallback when QP infeasible or when a single-candidate week renders the QP trivial." (Improvement 2.)

**§7 Workstream handoffs.** Add: "Every workstream handoff requires a passing smoke contract (replay test) that records `inputs_hash → output_hash`. The next workstream verifies upstream outputs without re-reasoning their implementation." (Improvement 6.)

**§9.2 Sizing Methodology.** Add a third paragraph: "When edge uncertainty σ_edge is meaningful, the certainty-equivalent stake is `f* = (μ_edge − σ_edge²) / b`, scaled by the user fraction. This collapses to standard fractional Kelly as σ → 0 and shrinks automatically when σ is large. RoR Monte Carlo (`src/risk/ror.py`) is run at every phase exit." (Improvement 1.)

**§11.2 Avoiding Leakage.** Add a fourth bullet: "Using a more recent DataGolf model version on past data (vendor-model leakage). Mitigation: every forecast is pinned to its `dg_model_version`; the backtester refuses forecasts whose version postdates the simulated decision time." (Improvement 3.)

**§11.3 Key Metrics.** Add: "Attribution decomposition (model α / execution / sizing / residual)" and "RoR forecast (probability of −25% drawdown over next 100 bets)." (Improvements 1, 4.)

**§14 Build Order, §15 Deliverables Checklist.** Replace qualitative phase-exit text with the quantitative gate tables in Improvement 9.

**ADR list (§16).** Add ADR-011 (Kelly under edge uncertainty), ADR-012 (Portfolio construction), ADR-013 (Vendor model versioning), ADR-014 (Phase-exit decision rules).

**agent.md charter.** Under "Conventions": add "Every artifact carries an `inputs_hash`. Every workstream handoff requires a passing smoke contract." Under "What NOT to do": add "Do not size on a point edge estimate. Use posterior Kelly with edge_sd from current calibration." and "Do not relax phase-exit gates mid-phase. Re-commit before re-entering."

---

## 13. What was deliberately not added

Equally important: the things a quant trader might reach for that don't earn their complexity in this system.

**Factor models for golf bets.** Tempting analogy to equity factor models. Skipped because (a) the bet horizon is one tournament, not a multi-period rebalance, (b) we'd be building factors from sparse and overlapping data, (c) DataGolf's model already absorbs most of the obvious factors. Revisit if Stage 2 overlay analysis (v0.1 §10) finds a clear factor signature.

**Regime detection.** Tempting because majors and opposite-field events are different markets. Skipped because (a) sample sizes are too small to estimate regime parameters separately, (b) the same effect can be achieved by tracking calibration and CLV per market-type-and-tournament-class, which we already do. Revisit when we have ≥ 100 tournaments.

**Custom golf model overlays in MVP.** Already correctly excluded by ADR-002. Re-affirmed.

**Real-time / in-play extensions.** Already correctly deferred to Phase 6 in v0.1 §10 Stage 4. Re-affirmed.

**Paper-trading sufficient as live proxy.** v0.1 already mandates a Shadow Live phase for this reason. Improvement 7 (capacity) and Improvement 4 (execution attribution) sharpen the proxy quality.

**Continuous reoptimization of Kelly fraction.** Skipped — it's the road to overfitting. The Kelly mode (fixed vs. posterior) is set per phase and held until a phase-gate review.

---

## 14. Risk to the plan from this addendum

Each improvement has an explicit "off switch" (a config flag) so a Phase 3 paper-trade can run with v0.1 logic and a v0.2 logic side-by-side. Any improvement that fails to outperform v0.1 by its own success metric over 4 tournaments is reverted by default.

The single largest source of v0.2 implementation risk is Improvement 2 (portfolio QP). It is also the largest expected-value gain on aggregate bet count weeks. Recommended path: build it but ship Phase 3 with `risk.portfolio.enabled: false` and only flip the switch when both the QP smoke contract and a 4-tournament parallel backtest agree.

Total estimated implementation effort, assuming the v0.1 plan is otherwise on track: 2-3 weeks of additional work, distributed across the existing workstreams as follows: WS-5 (Risk Engine) absorbs Improvements 1, 2, 5, 7, 10. WS-7 (Backtesting) absorbs Improvement 3. WS-8 (Monitoring) absorbs Improvements 4, 8. The hashing/contracts work in Improvement 6 is cross-cutting and should be set up early in WS-1 if not yet built.

---

## 15. Reviewer's bottom line

The v0.1 plan would not embarrass the strategy. It would, however, be hard to defend in a buy-side risk review on three points: edge-uncertainty Kelly, vendor-model versioning, and the quantitative-gate gap at phase exits. Improvements 1, 3, and 9 are the floor — without them this is a well-organized retail betting tool. With them, the system has the same auditability properties a small quant book would expect. Improvements 2, 4, 6 are the next tier — they upgrade the system from "well-organized" to "verifiable." The remaining four (5, 7, 8, 10) are operational hygiene and capacity realism; high marginal value, low marginal risk.

If only three improvements are taken: 1, 3, 9.
If six are taken: 1, 2, 3, 4, 6, 9.
All ten if the project commits to a quant-grade audit posture.
