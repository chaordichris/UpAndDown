# UpAndDown Workspace Instructions

## Scope

This file applies to the full workspace. Strategy (pod) code lives in
`golf-trading/`; the cross-strategy daily dashboard lives in `control-plane/`.

## Read First

- `README.md` (pod-shop framing and repo map)
- `upanddown-build-plan.md`
- `upanddown-build-plan-v0.2-addendum.md`
- `golf-trading/agent.md`
- `golf-trading/docs/agent-execution-plan.md`
- `golf-trading/CLAUDE.md` when editing inside `golf-trading/`

## Shared Skill Sources

- `skills/` is the tool-agnostic source for shared skills.
- `.codex/skills/` is the Codex mirror.
- `.claude/skills/` is the Claude mirror.
- Root `*.skill` files are packaged import artifacts for agents that load skills
  as archives.
- See `skills/README.md` for the full skill catalog and provenance.

## Workspace Rules

- Treat `golf-trading/agent.md` as the project charter.
- Treat `golf-trading/docs/agent-execution-plan.md` as the current implementation backlog and handoff contract.
- Keep DataGolf as the anchor model. Do not add custom golf-model overlays in MVP work.
- Prefer manual execution, provenance, and auditability over convenience automation.
- When editing a shared skill, update the tool-agnostic source, both mirrors,
  and the corresponding root `.skill` package in the same change.
- When phase status or workstream boundaries change, update the relevant docs in the same change.
- The control plane (`control-plane/`) only renders what strategies publish via
  `control-plane/CONTRACT.md` status files and runs whitelisted commands. It must
  never compute edges, sizes, or risk, and stays zero-npm-dependency.
- The market-making pod (`golf-trading/src/marketmaking/`) is simulator-only
  (MM-0). No live venue connectivity before its phase gates pass; see
  `golf-trading/docs/prediction-market-mm-spec.md`.
