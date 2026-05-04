# UpAndDown Golf Trading Instructions

## Current State

- `WS-1` through `WS-5` baseline modules are in place: config, storage, ingestion, normalization, pricing, edge detection, sizing, exposure, and drawdown.
- `WS-6` Phase 3 execution/logging is in progress: tickets, manual placement, settlement, CLV, attribution, promo accounting, report artifacts, and operator CLI commands exist.
- `WS-7` backtesting is in progress: leakage-checked DataGolf forecast replay, settlement, multi-event summaries, fixture-backed replay CLI, and review artifacts exist.
- `WS-8` monitoring/reporting is in progress: stored reports, CLV, attribution, open-action review, and JSON paper-report output exist.
- Phase 2 baseline is complete. Phase 3 paper trading, Batch C risk gates, and WS-7 audit artifacts are underway.

## Read Before Changing Architecture

- `agent.md`
- `docs/agent-execution-plan.md`
- `../upanddown-build-plan.md`
- `../upanddown-build-plan-v0.2-addendum.md`

## Skill Mirrors

- Use `../.codex/skills/karpathy-coding/SKILL.md` for coding behavior and change discipline.
- Use `../.codex/skills/github-best-practices/SKILL.md` for git, branch, and review hygiene.

## Required Conventions

- Keep all tunable values in `config/settings.yaml` or `config/books.yaml`.
- Use typed dataclasses for interfaces between modules.
- Give every new math-heavy module unit tests; risk and pricing math should also get property or table-driven tests.
- Add deterministic provenance (`inputs_hash`) to new artifacts and require a replay or smoke contract for workstream handoffs.
- Keep DataGolf as the model anchor; do not add custom predictive overlays in MVP work.
- Do not add automated execution, live betting, or parameter-tuning shortcuts before the paper-trading loop and phase gates exist.

## Current Priority Order

1. Build the Phase 3 paper-trading backbone (`execution`, settlement, CLV, reports).
2. Add cross-cutting verifiability (`inputs_hash`, replay fixtures, smoke contracts).
3. Ship the quant-risk P0 items from the addendum (`dg_model_version`, posterior Kelly, RoR, quantitative phase gates).
4. Broaden WS-7 historical coverage and keep phase-review artifacts manual, deterministic, and auditable.
5. Keep advanced portfolio controls behind config flags until they prove themselves in parallel tests.

## Doc Hygiene

- If the repo phase changes, update both `README.md` and `agent.md`.
- If the work backlog or handoff rules change, update `docs/agent-execution-plan.md`.
