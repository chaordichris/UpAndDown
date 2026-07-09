// Dashboard logic: fetch overview, render panels, run whitelisted actions.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (typeof n === "number" ? `$${n.toFixed(2)}` : "—");
const pct = (n) => (typeof n === "number" ? `${(n * 100).toFixed(1)}%` : "—");

let watchedRun = null;

async function refresh() {
  const overview = await (await fetch("/api/overview")).json();
  renderSummary(overview.summary);
  renderActions(overview.actions);
  renderOpportunities(overview.strategies);
  renderPositions(overview.strategies);
  renderExposures(overview.strategies);
  renderStrategies(overview.strategies);
  renderRuns(await (await fetch("/api/runs")).json());
}

function renderSummary(s) {
  $("summary").innerHTML = `
    <span class="${s.actionable_count ? "alert" : ""}">trades today <b>${s.actionable_count}</b></span>
    <span>open positions <b>${s.open_position_count}</b></span>
    <span>at risk <b>${money(s.total_at_risk)}</b></span>
    <span>pods healthy <b>${s.strategies_ok}/${s.strategies_total}</b></span>`;
}

function renderActions(actions) {
  $("actions-bar").innerHTML = actions
    .map((a) => `<button data-action="${esc(a.id)}" class="${a.danger ? "danger" : ""}" title="${esc(a.description)}">${a.danger ? "⚠ " : ""}${esc(a.label)}</button>`)
    .join("");
  for (const btn of $("actions-bar").querySelectorAll("button")) {
    btn.onclick = () => runAction(btn);
  }
}

async function runAction(btn) {
  const id = btn.dataset.action;
  if (btn.classList.contains("danger") && !confirm(`Run '${id}'? This writes data.`)) return;
  btn.disabled = true;
  try {
    const res = await (await fetch(`/api/actions/${id}/run`, { method: "POST" })).json();
    if (res.error) alert(res.error);
    else watchRun(res.run_id);
  } finally {
    setTimeout(() => { btn.disabled = false; refresh(); }, 800);
  }
}

function watchRun(runId) {
  watchedRun = runId;
  const out = $("run-output");
  out.hidden = false;
  const poll = async () => {
    if (watchedRun !== runId) return;
    const run = await (await fetch(`/api/runs/${runId}`)).json();
    out.textContent = `[${run.action_id}] ${run.status}\n\n${run.output}`;
    if (run.status === "running") setTimeout(poll, 1200);
    else refresh();
  };
  poll();
}

function opportunityRows(strategies) {
  return strategies.flatMap((s) =>
    (s.opportunities ?? []).map((o) => ({
      ...o,
      strategy_id: s.strategy_id,
      stale: s.stale || (o.expires_at && Date.parse(o.expires_at) < Date.now()),
    })),
  );
}

function renderOpportunities(strategies) {
  const rows = opportunityRows(strategies).sort((a, b) => (b.edge ?? 0) - (a.edge ?? 0));
  if (!rows.length) {
    $("opportunities").innerHTML = `<div class="empty good">No qualified opportunities. No action required — that is a valid result.</div>`;
    return;
  }
  $("opportunities").innerHTML = `<table>
    <tr><th>pod</th><th>market</th><th>trade</th><th>fair</th><th>book</th><th>edge</th><th>stake</th><th>action</th></tr>
    ${rows.map((o) => `
      <tr class="${o.stale ? "stale" : ""}">
        <td>${esc(o.strategy_id)}</td>
        <td>${esc(o.market)}</td>
        <td>${esc(o.description)}</td>
        <td class="num">${pct(o.fair_prob)}</td>
        <td class="num">${pct(o.book_prob)}</td>
        <td class="num">${pct(o.edge)}</td>
        <td>${esc(o.stake_suggestion ?? "—")}</td>
        <td><span class="pill ${o.stale ? "stale" : esc(o.recommended_action)}">${o.stale ? "stale" : esc(o.recommended_action)}</span></td>
      </tr>`).join("")}
  </table>`;
}

function renderPositions(strategies) {
  const rows = strategies.flatMap((s) =>
    (s.positions ?? []).filter((p) => p.status === "open").map((p) => ({ ...p, strategy_id: s.strategy_id })),
  );
  $("positions").innerHTML = rows.length
    ? `<table><tr><th>pod</th><th>position</th><th>stake</th><th>placed</th></tr>
       ${rows.map((p) => `<tr><td>${esc(p.strategy_id)}</td><td>${esc(p.description)}</td>
        <td class="num">${money(p.stake)}</td><td>${esc((p.placed_at ?? "").slice(0, 10))}</td></tr>`).join("")}</table>`
    : `<div class="empty">No open positions.</div>`;
}

function renderExposures(strategies) {
  const byGolfer = {};
  let maxGolfer = 0;
  for (const s of strategies) {
    for (const [name, amt] of Object.entries(s.exposures?.by_golfer ?? {})) {
      byGolfer[name] = (byGolfer[name] ?? 0) + amt;
    }
    maxGolfer = Math.max(maxGolfer, Number(s.exposures?.limits?.max_golfer) || 0);
  }
  const rows = Object.entries(byGolfer).sort((a, b) => b[1] - a[1]).slice(0, 15);
  if (!rows.length) {
    $("exposures").innerHTML = `<div class="empty">No exposure recorded.</div>`;
    return;
  }
  const top = rows[0][1];
  $("exposures").innerHTML = `<div class="bars">${rows.map(([name, amt]) => `
    <div class="bar-row">
      <span>${esc(name)}</span>
      <div class="bar-track"><div class="bar-fill ${maxGolfer && amt > 0.8 * maxGolfer ? "warn" : ""}" style="width:${(amt / top) * 100}%"></div></div>
      <span class="num">${money(amt)}</span>
    </div>`).join("")}</div>`;
}

function renderStrategies(strategies) {
  $("strategies").innerHTML = strategies.map((s) => `
    <div class="card">
      <h3>${esc(s.strategy_name ?? s.strategy_id)} <span class="pill ${esc(s.effective_status)}">${esc(s.effective_status)}</span></h3>
      <div class="meta">sleeve: ${esc(s.sleeve ?? "?")} · updated ${s.age_hours != null ? `${s.age_hours}h ago` : "never"} · hash ${esc((s.inputs_hash ?? "").slice(0, 10))}</div>
      <div class="meta">${(s.opportunities ?? []).length} opportunities · ${(s.positions ?? []).filter((p) => p.status === "open").length} open · at risk ${money(s.exposures?.total_at_risk)}</div>
      ${(s.health?.notes ?? []).length ? `<ul>${s.health.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    </div>`).join("") || `<div class="empty">No status files found. Run the exporter: <code>python scripts/export_control_plane_status.py</code></div>`;
}

function renderRuns(runs) {
  $("runs").innerHTML = runs.length
    ? `<table><tr><th>action</th><th>status</th><th>started</th><th></th></tr>
       ${runs.slice(0, 8).map((r) => `<tr><td>${esc(r.label)}</td>
         <td><span class="pill ${esc(r.status)}">${esc(r.status)}</span></td>
         <td>${esc(r.started_at.replace("T", " ").slice(0, 19))}</td>
         <td><button data-run="${esc(r.id)}">log</button></td></tr>`).join("")}</table>`
    : `<div class="empty">No runs yet this session.</div>`;
  for (const btn of $("runs").querySelectorAll("button[data-run]")) {
    btn.onclick = () => watchRun(btn.dataset.run);
  }
}

refresh();
setInterval(refresh, 30_000);
