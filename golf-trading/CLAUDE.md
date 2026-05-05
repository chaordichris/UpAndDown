# UpAndDown Golf Trading Instructions

## Current State

- `WS-1` through `WS-5` baseline modules are in place: config, storage, ingestion, normalization, pricing, edge detection, sizing, exposure, and drawdown.
- `src/execution/`, `src/backtest/`, `src/monitoring/`, and `src/orchestration/` are still skeletons.
- The repo is at the boundary between Phase 2 completion and Phase 3 paper-trading implementation.

## Read Before Changing Architecture

- `agent.md`
- `docs/agent-execution-plan.md`
- `../upanddown-build-plan.md`
- `../upanddown-build-plan-v0.2-addendum.md`

## Skill Sources

- Use `../skills/karpathy-coding/SKILL.md` for coding behavior and change discipline.
- Use `../skills/github-best-practices/SKILL.md` for git, branch, and review hygiene.

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
4. Keep advanced portfolio controls behind config flags until they prove themselves in parallel tests.

## Doc Hygiene

- If the repo phase changes, update both `README.md` and `agent.md`.
- If the work backlog or handoff rules change, update `docs/agent-execution-plan.md`.
