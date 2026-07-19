# UpAndDown Golf Trading Instructions

## Current State

- `WS-1` through `WS-5` baseline modules are in place: config, storage, ingestion, normalization, pricing, edge detection, sizing, exposure, and drawdown.
- `WS-6`, `WS-7`, and `WS-8` scaffolding is in place: tickets, placement, settlement, CLV, attribution, backtest replay, reports, phase-gate checks.
- `scripts/run_pipeline.py` provides the end-to-end fetch → price → edge → persist pipeline that feeds the paper-trading loop.
- The system is in Phase 3 — scaffolding complete, awaiting real operator-entered paper trades (0/60 bets, 0/4 tournaments).

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

1. **Run the pipeline on live tournaments** — use `scripts/run_pipeline.py` each week to generate candidates, then paper-trade them through the operator console.
2. Accumulate 60+ settled paper bets across 4+ tournaments to reach the Phase 3 → 4 gate.
3. Seed historical fixture data and broaden WS-7 backtest coverage.
4. Keep v0.2 quant-risk controls behind config flags until the paper-trading loop has enough volume.
5. Advanced portfolio controls stay deferred.

## Doc Hygiene

- If the repo phase changes, update both `README.md` and `agent.md`.
- If the work backlog or handoff rules change, update `docs/agent-execution-plan.md`.
