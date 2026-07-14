# Prediction-Market Market-Making — Strategy Spec (WS-9)

**Status:** Scaffold. Simulator-only. No live venue connectivity, no real capital.
**Sleeve:** `mm` — a third pod alongside sportsbook edges (core/convex) and Splash DFS.

## 1. Thesis

Sportsbook betting is *taking* prices: we only act when a book misprices
against the DataGolf anchor. Prediction markets (Kalshi first) let us *make*
prices: post two-sided quotes on golf tournament contracts and earn the
spread, using the same DataGolf-anchored fair value as the center of gravity.

The edge decomposes into three P&L streams that must be tracked separately:

1. **Spread capture** — uninformed flow crossing our quotes. This is the
   business we want.
2. **Adverse selection** — informed flow picking us off when our fair is
   stale (DataGolf updates lag live scoring, injuries, weather). This is the
   business we must survive.
3. **Inventory settlement** — residual directional exposure resolving at
   settlement. This should be noise, not a bet.

A market maker that cannot measure these three separately cannot tell whether
it has an edge. The simulator reports all three from day one.

## 2. Philosophical constraints (Taleb / Spitznagel / Frey)

- **No-quote is the default.** We quote a market only when our posterior
  uncertainty about fair value is tight enough that the quoted spread covers
  it. Wide uncertainty → stand down. Same posture as no-bet.
- **Survival first, hard vetoes.** The risk engine can veto any quote and can
  flatten the book. Its limits (max inventory per market, max notional per
  tournament, daily loss kill switch) cannot be overridden by the quoting
  engine — identical to the bankroll engine's veto power over bets.
- **Bayesian fair value, not point estimates.** DataGolf probability is
  treated as the mean of a Beta posterior with an explicit effective sample
  size. The credible interval — not a constant — sets the minimum half-spread.
  Quoting tighter than your own uncertainty is selling insurance below cost.
- **Convexity awareness.** Inventory skew is asymmetric near the 0/1
  boundaries where contract gamma is highest; position limits shrink as
  |p − 0.5| grows because tail outcomes gap, they don't drift.
- **Kelly-fractional capital.** Per-market risk budget is a fraction of the
  mm sleeve, sized so that total ruin of one market's inventory is an
  acceptable, pre-committed loss.

## 3. Venue plan

| Phase | Venue | Mode |
|---|---|---|
| MM-0 (now) | Simulator (`venues/sim.py`) | Deterministic paper harness, seeded |
| MM-1 | Kalshi read-only (`venues/kalshi.py`) | Real order books, shadow quotes, measure would-have P&L |
| MM-2 | Kalshi live, tiny size | Manual order placement from quote tickets (consistent with manual-execution doctrine) |
| MM-3+ | API execution, more venues | Only after MM-2 proves positive spread capture net of adverse selection |

Kalshi specifics that shape the design: binary contracts priced 1–99¢, 1¢
tick, fee schedule taken from config (never hardcoded), REST + WebSocket API,
CFTC-regulated. The `VenueAdapter` interface hides all of this so the quoting
engine is venue-agnostic.

## 4. Architecture

```
DataGolf forecast ──► fair_value.py ──► FairValueBand (posterior mean + CI)
                                            │
order book snapshot ──► quoting.py ◄── inventory.py (position, avg cost)
                            │
                     QuoteProposal(s)
                            │
                       risk.py  ── veto / clamp (hard limits, kill switch)
                            │
                     ApprovedQuotes ──► venue adapter (sim | kalshi)
                                            │
                                        fills ──► inventory, P&L attribution
```

Modules (`src/marketmaking/`):

- `types.py` — frozen dataclasses for every interface boundary.
- `config.py` — `MMConfig` loaded from `settings.yaml` `marketmaking:` block;
  safe defaults; `enabled: false` until MM-2 gate passes.
- `fair_value.py` — Beta posterior around the DataGolf prob; credible
  interval via Wilson-style normal approximation on the Beta.
- `quoting.py` — half-spread = max(min edge, k × posterior half-width) +
  inventory skew (Avellaneda–Stoikov-flavored linear skew); side size shrinks
  as inventory approaches its limit; never quotes a side that would breach it.
- `inventory.py` — per-market position, average cost, realized/unrealized P&L.
- `risk.py` — hard limits and kill switch. Pure veto layer; returns reasons.
- `venues/` — `base.py` (abstract adapter), `sim.py` (stochastic flow +
  drifting true probability), `kalshi.py` (stub: documented endpoints, raises
  `NotImplementedError` on live calls).
- `simulator.py` — seeded episode runner; emits an artifact with
  `inputs_hash`, P&L attribution, inventory paths.
- `scripts/mm_simulate.py` — CLI; `--publish-status` writes the control-plane
  contract file for the `pm-market-making` pod.

## 5. Phase gates (pre-committed)

- **MM-0 → MM-1:** simulator shows positive spread capture with adverse
  selection ≤ 50% of gross spread P&L across ≥ 1,000 seeded episodes, and all
  risk-limit property tests pass.
- **MM-1 → MM-2:** ≥ 4 tournament weeks of shadow quoting against real Kalshi
  books with positive would-have P&L net of fees, and measured book depth
  supports our minimum viable size.
- **MM-2 → MM-3:** ≥ 200 real fills with positive realized spread capture net
  of adverse selection and fees; max drawdown within pre-set bound.

Gates are recorded as artifacts, same as Phase 3 paper-trading proof.

## 6. Explicitly out of scope for the scaffold

Live order placement, WebSocket ingestion, cross-venue arbitrage, in-play
quoting, and any overlay that second-guesses DataGolf. The anchor-model rule
holds here too.
