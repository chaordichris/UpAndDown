# Splash Sports Pod — Bulletproofing Plan

**Status:** SP-1 implemented; SP-2 runner skeleton implemented (generator/card/
sensitivity consolidation done; full config block still open); SP-3 through
SP-5 sequenced below.
**Owner surface:** `src/fantasy/splash/`, `scripts/*splash*.py`
**Doctrine:** same as every pod — no-action default, hard vetoes, provenance,
pre-committed gates. This plan makes those properties *operational*, not
aspirational, for the weekly Splash workflow.

## 0. Where we actually are

The good news the artifacts already prove: the portfolio generator **fails
closed**. The 2026-07 rungood run emitted `status: blocked_hard_review` with
zero lineups rather than building lineups on missing anchors. The core safety
property exists.

What is *not* bulletproof:

1. **Diagnosis is hostile.** A blocked run yields terse strings
   (`tier_4_has_0_anchored_players_for_1_required`) with no explanation of
   which upstream fixture is deficient or which script repairs it. The
   remediation chain (capture enrichment → build anchors → rank fixture →
   overrides → regenerate) is ~6 manual CLI invocations with long argument
   lists. Data gaps happen *because* the pipeline is hard to drive, and a
   blocked Friday run during a tournament week is an unrecoverable miss.
2. **The feedback loop has never closed.** The operator console supports
   entry logging and result settlement (`splash-results-ledger.json`), but
   the ledger has never been written. Zero settled contests means: no
   realized-vs-projected ROI, no calibration evidence for the score model, no
   duplication-rate check against the opponent model, and nothing for the
   control plane to show as positions.
3. **Config lives in argparse defaults.** Bankroll, EV thresholds, exposure
   caps, ownership assumptions are `add_argument(default=...)` magic numbers —
   violating the workspace rule that all configurable values live in
   `settings.yaml`. Two near-duplicate generator scripts (generic + rungood)
   multiply the drift risk.
4. **No pre-committed proof gate.** The betting pod needs ≥60 settled bets
   across ≥4 tournaments before real capital scales. Splash has no equivalent
   pre-committed standard, which is exactly the condition under which
   result-chasing retunes happen.
5. **Unofficial API dependency.** Splash's JSON endpoints are undocumented
   and versioned by a mobile-web header. Schema drift will eventually break
   ingestion; today it would break it *quietly* mid-pipeline.

## SP-1 — Preflight integrity gate (implemented)

**Goal:** one command that answers "can this week's data support a lineup
card?" with a structured, remediable report — before any simulation spend.

**Built:**
- `src/fantasy/splash/integrity.py` — pure functions over the same four
  fixtures the generator consumes (contest detail, player pools, DataGolf
  ranks, score anchors). Checks: per-tier anchor coverage vs. roster
  requirements, unmapped players, rank mismatches, missing anchors by name,
  anchor sanity (probabilities, SDs), and fixture freshness. Every failure
  carries a `remediation` field naming the script that repairs it.
- `scripts/splash_preflight.py` — CLI wrapper; writes
  `artifacts/splash-preflight-report.json` (with `inputs_hash`), prints a
  human summary, exits non-zero on any blocking failure.
- Control-plane action `splash-preflight` so the gate is one click from the
  daily desk.
- Table-driven tests in `tests/unit/test_splash_integrity.py`.

**Definition of done (met):** running preflight against the July rungood
fixtures reproduces every current `hard_review_item` as a *diagnosed* failure
with a named remediation, and a clean synthetic fixture set passes.

## SP-2 — One-command weekly run

**Goal:** `python scripts/run_splash_week.py --contest <uuid>` executes
discover → capture → enrich → anchors → **preflight** → portfolios →
lineup card → control-plane status, as a resumable, manifest-driven pipeline.

**Built (runner skeleton):**
- `scripts/run_splash_week.py` — resumable, manifest-driven engine over an
  ordered stage graph (`capture → enrich → anchors → preflight → portfolios →
  sensitivity → card → status`). Each stage writes its artifact(s) into the
  week directory and records an `inputs_hash` chaining upstream output hashes +
  resolved config into `week-manifest.json`. A re-run skips any stage whose
  outputs exist and whose `inputs_hash` still matches; `--force-from <stage>`
  reruns from a stage; `--start-stage <stage>` seeds earlier stages from
  artifacts already on disk (the current path — capture/enrich/anchors are
  still driven by the SP-1 manual scripts, then this runner drives the rest).
- Preflight is a hard gate: a blocked SP-1 report stops the pipeline; it never
  pushes through a data gap.
- Stage parameters come from the new `splash:` block in `config/settings.yaml`
  (`src.config.SplashConfig`); CLI flags act as overrides and are logged as
  overrides in the manifest. Stages reuse the existing scripts as importable
  functions / their CLIs — no stage logic is forked.
- `tests/unit/test_run_splash_week.py` — engine tests (completion, deterministic
  replay, config-cache invalidation, `--force-from`, `--start-stage` seeding,
  preflight-block halt, arg validation) plus a real-preflight integration test
  that fails closed against the checked-in rungood fixtures.

**Done this slice:** the generator, lineup-card, and sensitivity script pairs
are consolidated behind one canonical module each —
`src/fantasy/splash/series.py` (`ContestSeriesConfig` + the `RUNGOOD_SERIES`
preset), `scripts/generate_splash_portfolios.py`,
`scripts/build_splash_lineup_card.py`, `scripts/run_splash_sensitivity.py`.
The rungood-named scripts are now thin back-compat shims re-exporting the
symbols their pinned tests need. `run_splash_week.py`'s portfolios stage calls
`generate_portfolios(...)` in-process instead of the argv-patch/`importlib`
reuse pattern, and its sensitivity/card stages import the canonical modules
directly. The generator's own provenance path resolution no longer crashes on
out-of-repo-root fixtures (falls back to an absolute path instead of raising).
Golden-diff verified byte-identical (including `artifact_hash`) against the
pre-refactor generator output.

**Still open (deferred slices):** graduate the contest-series config and the
remaining anchor-shape/API params into the fuller SP-4 `settings.yaml` block;
wire the live discover/capture/enrich/anchors handlers end to end (today they
delegate to existing scripts but are exercised only from `--start-stage`
onward against fixtures).

**Design constraints:**
- Each stage writes its artifact and records `inputs_hash` chaining into a
  week manifest; re-running skips completed stages unless `--force-from
  <stage>`.
- Preflight failure stops the pipeline with the SP-1 report — the pipeline
  never "pushes through" a data gap.
- All stage parameters come from a new `splash:` block in `settings.yaml`
  (SP-4 lands the block; SP-2 consumes it). No new argparse defaults.
- Reuse existing scripts as importable functions (the pattern
  `run_splash_workflow.py` already uses); do not fork logic.
- Done: the generic/rungood generator, card, and sensitivity script pairs are
  consolidated behind one canonical code path each
  (`src/fantasy/splash/series.py` + `scripts/generate_splash_portfolios.py`,
  `scripts/build_splash_lineup_card.py`, `scripts/run_splash_sensitivity.py`);
  the rungood-named scripts are now thin re-export shims.

**Definition of done:** a tournament week is drivable with one command plus
manual entry placement; a smoke contract runs the full chain against checked-
in fixtures in CI (`make test`); the manifest replays deterministically.

## SP-3 — Results & calibration loop

**Goal:** every entered lineup gets settled, and settlement feeds three
pre-committed diagnostics.

**Work items:**
1. **Ledger becomes mandatory workflow, not optional UI.** Entry logging at
   card-generation time (operator confirms which lineups were actually
   entered); settlement capture from final contest standings (read-only API
   fetch where available, manual entry otherwise).
2. **Realized vs. projected:** per-contest report comparing realized payout
   to the optimizer's `expected_payout_cents` distribution — was the outcome
   inside the simulated band?
3. **Score-model calibration:** PIT/coverage checks of actual player scores
   against the simulated distributions (the Splash analog of CLV — process
   truth over outcome noise).
4. **Duplication audit:** actual duplicate-entry counts vs. the opponent
   model's assumption, per contest size.
5. Ledger totals flow into the control-plane status file as positions and
   realized P&L.

**Definition of done:** after any settled contest, one command produces a
calibration artifact; the control plane shows open entries and realized P&L;
≥1 replay test pins the settlement math.

## SP-4 — Risk & config hardening

**Goal:** every tunable in one governed place; caps enforced by a veto layer.

**Work items:**
1. `splash:` block in `settings.yaml`: bankroll fraction caps (weekly,
   per-contest, per-entry), optimizer parameters (min marginal EV, exposure
   caps, Kelly fraction), ownership assumptions, simulation counts, API base
   URLs. Scripts read config; CLI flags become overrides that are *logged as
   overrides* in artifacts.
2. A `SplashRiskGuard` mirroring the betting pod's drawdown brake: refuses
   entry plans exceeding weekly/per-contest caps, refuses when the ledger
   shows the weekly cap already consumed, kill-switch on realized weekly loss.
   Vetoes are recorded with reasons in the lineup card artifact.
3. Cross-pod golfer exposure: splash status file publishes per-golfer entry
   exposure (contract already supports it) so the control plane *renders*
   combined sportsbook + DFS concentration. (Render-only; enforcement stays
   per-pod.)

**Definition of done:** deleting every splash argparse default changes no
behavior (all values sourced from config); a property test proves no plan
exceeding caps can serialize to a lineup card.

## SP-5 — Pre-committed proof gate for the pod

**Goal:** decide *now* what evidence justifies scaling real entry fees, so
noisy results can't renegotiate it later.

**Proposed gate (tune before committing, then freeze):**
- ≥ 12 settled contests across ≥ 6 tournament weeks at current stakes.
- Score-model calibration: 80% credible-interval coverage of actual player
  scores in [70%, 90%].
- Duplication assumption error < 2x in either direction.
- Realized ROI inside the simulated 10th–90th percentile band in ≥ 8 of 12
  contests (process check, not a profitability requirement).
- Zero risk-guard violations (no cap breaches, no unlogged overrides).

Gate evidence is an artifact (`splash_phase_gate_check`), same pattern as
`scripts/phase_gate_check.py`.

## Sequencing and effort

| Order | Workstream | Size | Depends on |
|---|---|---|---|
| 1 | SP-1 preflight gate | done | — |
| 2 | SP-2 one-command run | skeleton done; generator/card/sensitivity consolidation done | SP-1 |
| 3 | SP-4 config/risk hardening | M | none (parallel with SP-2; SP-2 consumes it) |
| 4 | SP-3 results loop | M | a settled contest to exercise it |
| 5 | SP-5 proof gate | S | SP-3 artifacts |

Rationale: SP-2 and SP-4 remove the operational causes of data gaps and
config drift *before* the next tournament week; SP-3 starts accumulating
evidence the first week the pipeline runs clean; SP-5 is cheap once SP-3
exists and must be frozen before results start arriving in volume.

## Non-goals

No custom golf-model overlays (DataGolf stays the anchor). No automated entry
submission — placement stays manual by doctrine. No opponent-model
sophistication increases until SP-3 shows where the current one is wrong.
