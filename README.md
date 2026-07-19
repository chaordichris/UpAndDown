# UpAndDown

A personal pod-shop for golf advantage play.

The multi-manager hedge fund ("pod shop") model — independent strategy pods,
each with its own P&L and playbook, allocated capital by a central risk
function with absolute veto power — maps surprisingly well onto exploiting +EV
opportunities across golf games. This repo is that mapping: the golf markets
are the opportunity set, DataGolf is the shared research desk, each strategy
is a pod, and a hard-limits risk layer plus a control plane sit above all of
them.

## Intellectual lineage

The system's posture comes from three places. From **Nassim Taleb**: respect
fat tails, never expose the bankroll to ruin, and prefer being approximately
right about uncertainty to being precisely wrong about point estimates. From
**Mark Spitznagel**: survival first as an *architectural* property — capital
is split between a core sleeve of small repeatable edges and a tightly capped
convex sleeve for asymmetric payoffs, and drawdown brakes are hard-coded, not
advisory. From **Robert J. Frey** (Renaissance alum): systematic process over
conviction, measure everything, and let unglamorous statistical discipline —
calibration, CLV, provenance — decide what survives. The statistics are
**Bayesian** throughout: DataGolf forecasts are treated as posterior means
with explicit effective sample sizes, sizing is posterior-Kelly-aware, and
uncertainty bands (not point estimates) gate every action.

Three doctrines follow, and every pod inherits them:

1. **No-action is the default.** You need a quantified reason to bet, enter,
   or quote — never a reason not to. An empty trade board is a success state.
2. **The risk layer has veto power.** Bankroll limits, exposure caps, and
   kill switches cannot be overridden by anything upstream of them.
3. **Auditability is the product.** Every decision traces from raw data to
   action via provenance-hashed artifacts. If it can't be replayed, it
   didn't happen.

## The pods

| Pod | Sleeve | Edge | Status |
|---|---|---|---|
| **Sportsbook weekly edges** | core + convex | DataGolf fair prices vs. book lines (matchups, top-N, make-cut core; capped outright convex sleeve) | Phase 3 — paper-trading proof underway |
| **Splash Sports DFS** | dfs | Contest EV via tiered lineup portfolios with Kelly-adjusted entry sizing | Weekly operation |
| **Prediction-market MM** | mm | Make prices on golf contracts (Kalshi) around Bayesian fair-value bands; earn spread, survive adverse selection | MM-0 scaffold — simulator only |

Pods are deliberately *not* microservices: each is a CLI-first Python module
with its own tests, artifacts, and phase gates, publishing a standardized
status file. That keeps every pod independently runnable, testable, and
auditable — the properties that matter at single-operator scale.

## The control plane

`control-plane/` is the daily desk: a local, zero-dependency Node app that
aggregates every pod's status file into one screen — today's recommended
trades, open positions, exposure concentration, pod health — with one-click
(whitelisted, no-shell) buttons to run the underlying pipelines. Open it each
morning; it tells you whether today requires action. See
`control-plane/README.md` and `control-plane/CONTRACT.md`.

```bash
cd golf-trading && python scripts/export_control_plane_status.py   # refresh pod data
cd ../control-plane && npm start                                    # → http://localhost:4600
```

## Repo map

```
control-plane/        Daily desk UI + strategy status contract (Node, no deps)
golf-trading/         All pod code (Python)
  src/                ingestion, pricing, risk, execution, backtest,
                      fantasy (Splash), marketmaking (Kalshi scaffold)
  scripts/            CLI pipelines — the pods' operational surface
  docs/               Runbooks, ADRs, execution plan, strategy specs
  artifacts/          Provenance-hashed outputs incl. control-plane/*.status.json
skills/               Shared agent skills (tool-agnostic source + mirrors)
upanddown-build-plan* Founding architecture documents
```

## Read next

- `golf-trading/agent.md` — project charter and current status
- `golf-trading/docs/agent-execution-plan.md` — implementation backlog
- `golf-trading/docs/prediction-market-mm-spec.md` — market-making strategy spec
- `upanddown-build-plan.md` — the founding architecture and philosophy

## Ground rules

DataGolf is the anchor model — no custom golf-model overlays. Execution is
manual by doctrine until a phase gate proves otherwise. Real money moves only
after pre-committed, artifact-recorded proof gates pass. This is a research
and decision-support system; it never places bets or orders on its own.
