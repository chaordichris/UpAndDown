# UpAndDown Control Plane

A local, zero-build daily trading desk. Open it each morning and see, in one
screen: what trades each strategy recommends today, what positions are open,
where exposure is concentrated, and one-click buttons to run the underlying
pipelines.

## Architecture: artifact-contract hub

```
┌──────────────────────────────── control-plane (Node, no deps) ───────────┐
│  server.js ── GET /api/overview   → aggregate of all status files        │
│            ── POST /api/actions/:id/run → spawn whitelisted command      │
│            ── GET /api/runs/:id   → captured stdout/stderr + exit code   │
│  public/   ── single-page dashboard (vanilla JS)                         │
└───────────────▲──────────────────────────────────────▲───────────────────┘
                │ reads JSON (contract v1.0)            │ spawns (whitelist)
   golf-trading/artifacts/control-plane/*.status.json   │
                ▲                                       │
┌───────────────┴───────────────────────────────────────┴──────────────────┐
│  Strategy pods (Python, CLI-first, independently testable)               │
│  • sportsbook-edges  → scripts/run_pipeline.py + export_control_plane…  │
│  • splash-dfs        → scripts/run_splash_workflow.py + exporter         │
│  • pm-market-making  → scripts/mm_simulate.py + exporter (scaffold)      │
└───────────────────────────────────────────────────────────────────────────┘
```

Why this and not microservices: at single-operator scale, N local daemons add
failure modes and ops work without adding capability. Strategies stay what
they already are — auditable CLI pipelines that emit provenance-hashed
artifacts. The contract file (see `CONTRACT.md`) is the only coupling point.
A strategy can be promoted to a real service later without changing the
dashboard, as long as something keeps publishing its status file.

## Run it

```bash
cd control-plane
npm start          # → http://localhost:4600  (no npm install needed)
```

Refresh data for the dashboard (also available as a button in the UI):

```bash
cd ../golf-trading
python scripts/export_control_plane_status.py
```

## Configuration

`config/control-plane.json`:

- `statusGlobs` — where to find strategy status files
- `freshnessHours` — per-strategy staleness windows
- `actions` — the **whitelist** of runnable commands. Only entries here can
  ever be executed, each with a fixed argv (no shell, no user-supplied
  arguments). This is the security boundary; treat additions as code review.

## Design rules

1. The control plane never computes edges, sizes, or risk — it renders what
   strategies published and refuses to render stale data quietly.
2. No trade is auto-executed. Actions run pipelines and exporters; placing
   bets stays manual and logged in the strategy pods.
3. Zero npm dependencies. `node:http`, `node:fs`, `node:child_process` only.
4. Stale > wrong: a status file older than its freshness window renders with
   an explicit STALE banner and its opportunities are de-emphasized.

## Testing

```bash
npm test
```
