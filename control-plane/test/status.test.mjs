import { test } from "node:test";
import assert from "node:assert/strict";
import { annotateStaleness, summarize, loadConfig, buildOverview } from "../lib/status.js";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NOW = Date.parse("2026-07-08T12:00:00Z");
const hoursAgo = (h) => new Date(NOW - h * 3_600_000).toISOString();

test("annotateStaleness: fresh file stays ok", () => {
  const s = annotateStaleness(
    { strategy_id: "x", generated_at: hoursAgo(2), health: { status: "ok" } },
    { default: 36 },
    NOW,
  );
  assert.equal(s.stale, false);
  assert.equal(s.effective_status, "ok");
  assert.equal(s.age_hours, 2);
});

test("annotateStaleness: old file becomes stale, per-strategy window wins", () => {
  const s = annotateStaleness(
    { strategy_id: "sportsbook-edges", generated_at: hoursAgo(30), health: { status: "ok" } },
    { default: 36, "sportsbook-edges": 24 },
    NOW,
  );
  assert.equal(s.stale, true);
  assert.equal(s.effective_status, "stale");
});

test("annotateStaleness: missing generated_at is stale, error status preserved", () => {
  const s = annotateStaleness({ strategy_id: "x", health: { status: "error" } }, {}, NOW);
  assert.equal(s.stale, true);
  assert.equal(s.effective_status, "error");
});

test("summarize: counts actionable, open positions, total at risk", () => {
  const strategies = [
    {
      strategy_id: "a", stale: false, effective_status: "ok",
      opportunities: [
        { recommended_action: "bet" },
        { recommended_action: "pass" },
        { recommended_action: "bet", expires_at: hoursAgo(1) }, // expired
      ],
      positions: [{ status: "open" }, { status: "settled" }],
      exposures: { total_at_risk: 100.5 },
    },
    { strategy_id: "b", stale: true, effective_status: "stale", opportunities: [{ recommended_action: "bet" }], positions: [], exposures: { total_at_risk: 10 } },
  ];
  const s = summarize(strategies);
  assert.equal(s.actionable_count, 1); // stale pod + expired opp excluded
  assert.equal(s.open_position_count, 1);
  assert.equal(s.total_at_risk, 110.5);
  assert.equal(s.strategies_ok, 1);
});

test("buildOverview: runs against real config without throwing", () => {
  const config = loadConfig(ROOT);
  const overview = buildOverview(ROOT, config, NOW);
  assert.ok(Array.isArray(overview.strategies));
  assert.ok(Array.isArray(overview.actions));
  assert.ok(overview.summary.strategies_total >= 0);
  // whitelist entries never leak argv/cwd to the client
  for (const a of overview.actions) assert.equal(a.argv, undefined);
});
