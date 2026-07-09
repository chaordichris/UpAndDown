# Control Plane Strategy Contract v1.0

Every strategy (pod) publishes one JSON status file. The control plane reads
these files and nothing else — no imports from strategy code, no direct DB
access. This keeps strategies independently testable and lets any language
publish (Python today, anything later).

## Location

```
golf-trading/artifacts/control-plane/<strategy_id>.status.json
```

The control plane's `config/control-plane.json` lists the glob(s) it watches.

## Schema

```jsonc
{
  "contract_version": "1.0",
  "strategy_id": "sportsbook-edges",        // stable slug, unique
  "strategy_name": "Sportsbook Weekly Edges",
  "sleeve": "core",                          // core | convex | dfs | mm
  "generated_at": "2026-07-08T12:00:00Z",    // ISO-8601 UTC
  "inputs_hash": "abc123...",                // provenance hash of source data

  "health": {
    "status": "ok",                          // ok | stale | error
    "notes": ["3 books missing make_cut odds"]
  },

  // Trades the operator should consider TODAY. Empty list is a valid,
  // successful output (no-bet default).
  "opportunities": [
    {
      "id": "mc-dk-player123",               // stable within a run
      "market": "make_cut",
      "description": "J. Smith to make cut @ DraftKings -120",
      "fair_prob": 0.61,
      "book_prob": 0.545,
      "edge": 0.065,
      "recommended_action": "bet",           // bet | review | pass
      "stake_suggestion": "0.5u ($12)",      // human-readable; sizing stays in strategy
      "expires_at": "2026-07-09T11:00:00Z",  // stale after this
      "provenance": { "artifact": "daily-analysis-make-cut-2026-07-07.json" }
    }
  ],

  // Open exposure the operator currently holds via this strategy.
  "positions": [
    {
      "id": "bet-42",
      "description": "T. Kim top-20 @ FanDuel +240, 1u",
      "stake": 25.0,
      "placed_at": "2026-07-02T15:04:00Z",
      "status": "open",                      // open | settled | void
      "detail": { "market": "top_20", "book": "fanduel" }
    }
  ],

  // Aggregated risk view. Keys are free-form but by_golfer / by_tournament /
  // total_at_risk are expected by the dashboard's exposure panel.
  "exposures": {
    "total_at_risk": 145.0,
    "by_golfer": { "T. Kim": 40.0 },
    "by_tournament": { "John Deere Classic": 145.0 },
    "limits": { "max_golfer": 60.0, "max_tournament": 250.0 }
  },

  // Strategy-owned quick actions. Commands must ALSO appear in the control
  // plane's action whitelist to be runnable — this field is advisory routing,
  // the whitelist is the security boundary.
  "actions": [
    { "id": "refresh-edges", "label": "Re-run edge pipeline" }
  ]
}
```

## Rules

1. Publishing is atomic: write to a temp file, then rename.
2. `generated_at` drives staleness. The control plane marks a strategy
   `stale` when the file is older than its configured freshness window.
3. Empty `opportunities` is success, not failure. The dashboard renders
   "no action" prominently — the default position is no trade.
4. All money numbers are dollars (floats), all probabilities are 0–1.
5. Additive schema evolution only within v1.x; renames/removals bump major.
6. Every file carries `inputs_hash` so a displayed opportunity can be traced
   back to the exact source artifacts.
