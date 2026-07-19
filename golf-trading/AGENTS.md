# UpAndDown Golf Trading Instructions

## Current State

- `WS-1` through `WS-5` baseline modules are in place: config, storage, ingestion, normalization, pricing, edge detection, sizing, exposure, and drawdown.
- `WS-6` Phase 3 execution/logging is in progress: tickets, manual placement, settlement, CLV, attribution, promo accounting, report artifacts, and operator CLI commands exist.
- `WS-7` backtesting is in progress: leakage-checked DataGolf forecast replay, settlement, multi-event summaries, fixture-backed replay CLI, and review artifacts exist.
- `WS-8` monitoring/reporting is in progress: stored reports, CLV, attribution, open-action review, and JSON paper-report output exist.
- Phase 2 baseline is complete. Phase 3 daily edge UI/backtest visualization/paper validation, Batch C risk gates, and WS-7 audit artifacts are underway.

## Read Before Changing Architecture

- `agent.md`
- `docs/agent-execution-plan.md`
- `../upanddown-build-plan.md`
- `../upanddown-build-plan-v0.2-addendum.md`

## Shared Skills

- `../skills/` is the tool-agnostic source for shared skills.
- `../.codex/skills/` is the Codex mirror.
- `../.claude/skills/` is the Claude mirror.
- Root `../*.skill` files are packaged import artifacts for agents that load skills as archives.
- See `../skills/README.md` for the full skill catalog and provenance.
- When editing a shared skill, update the tool-agnostic source, both mirrors, and the corresponding root `.skill` package in the same change.

## Required Conventions

- Keep all tunable values in `config/settings.yaml` or `config/books.yaml`.
- Use typed dataclasses for interfaces between modules.
- Give every new math-heavy module unit tests; risk and pricing math should also get property or table-driven tests.
- Add deterministic provenance (`inputs_hash`) to new artifacts and require a replay or smoke contract for workstream handoffs.
- Keep DataGolf as the model anchor; do not add custom predictive overlays in MVP work.
- Do not add automated execution, live betting, or parameter-tuning shortcuts before the paper-trading loop and phase gates exist.

## Current Priority Order

1. Make daily DataGolf-anchored edges easy to inspect in the operator UI.
2. Broaden WS-7 historical coverage and add reproducible backtest visualizations.
3. Keep the Phase 3 paper-validation backbone focused on proof evidence (`execution`, settlement, CLV, attribution, reports), not full betting-history tracking.
4. Add cross-cutting verifiability (`inputs_hash`, replay fixtures, smoke contracts).
5. Ship the quant-risk P0 items from the addendum (`dg_model_version`, posterior Kelly, RoR, quantitative phase gates).
6. Keep advanced portfolio controls behind config flags until they prove themselves in parallel tests.

## Doc Hygiene

- If the repo phase changes, update both `README.md` and `agent.md`.
- If the work backlog or handoff rules change, update `docs/agent-execution-plan.md`.
