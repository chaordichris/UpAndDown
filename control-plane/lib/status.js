// Status aggregation: read strategy contract files, mark staleness, summarize.
import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";

export function loadConfig(root) {
  const raw = JSON.parse(readFileSync(path.join(root, "config", "control-plane.json"), "utf-8"));
  if (!Array.isArray(raw.actions)) throw new Error("config: actions must be an array");
  return raw;
}

function readStatusFiles(root, config) {
  const files = [];
  for (const dir of config.statusGlobs) {
    const abs = path.resolve(root, dir);
    if (!existsSync(abs)) continue;
    for (const name of readdirSync(abs)) {
      if (!name.endsWith(".status.json")) continue;
      try {
        files.push(JSON.parse(readFileSync(path.join(abs, name), "utf-8")));
      } catch (err) {
        files.push({
          strategy_id: name.replace(/\.status\.json$/, ""),
          strategy_name: name,
          health: { status: "error", notes: [`unparseable status file: ${err.message}`] },
          opportunities: [], positions: [], exposures: {},
        });
      }
    }
  }
  return files;
}

export function annotateStaleness(strategy, freshnessHours, now = Date.now()) {
  const windowH = freshnessHours[strategy.strategy_id] ?? freshnessHours.default ?? 36;
  const ageH = strategy.generated_at
    ? (now - Date.parse(strategy.generated_at)) / 3_600_000
    : Infinity;
  const stale = !(ageH <= windowH);
  return {
    ...strategy,
    age_hours: Number.isFinite(ageH) ? Math.round(ageH * 10) / 10 : null,
    stale,
    effective_status: stale && strategy.health?.status === "ok" ? "stale" : (strategy.health?.status ?? "error"),
  };
}

export function summarize(strategies) {
  const opps = strategies.flatMap((s) =>
    (s.opportunities ?? []).map((o) => ({
      ...o,
      strategy_id: s.strategy_id,
      stale: s.stale || (o.expires_at != null && Date.parse(o.expires_at) < Date.now()),
    })),
  );
  const actionable = opps.filter((o) => o.recommended_action === "bet" && !o.stale);
  const positions = strategies.flatMap((s) =>
    (s.positions ?? []).filter((p) => p.status === "open").map((p) => ({ ...p, strategy_id: s.strategy_id })),
  );
  const totalAtRisk = strategies.reduce(
    (sum, s) => sum + (Number(s.exposures?.total_at_risk) || 0), 0,
  );
  return {
    actionable_count: actionable.length,
    open_position_count: positions.length,
    total_at_risk: Math.round(totalAtRisk * 100) / 100,
    strategies_ok: strategies.filter((s) => s.effective_status === "ok").length,
    strategies_total: strategies.length,
  };
}

export function buildOverview(root, config, now = Date.now()) {
  const strategies = readStatusFiles(root, config)
    .map((s) => annotateStaleness(s, config.freshnessHours ?? {}, now))
    .sort((a, b) => (a.strategy_id ?? "").localeCompare(b.strategy_id ?? ""));
  return {
    generated_at: new Date(now).toISOString(),
    summary: summarize(strategies),
    strategies,
    actions: config.actions.map(({ id, label, description, danger }) => ({ id, label, description, danger })),
  };
}
