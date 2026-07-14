# Forecast-Backed Market Expansion Spec

## Goal

Add DataGolf forecast-backed markets to the daily edge pipeline without changing
the golf model. The first proof markets are `top_20`, `top_10`, `top_5`,
`make_cut`, and `outright_win`; once they work end to end, the same path can
expand to `miss_cut`.

## Scope

Proof build:

- Fetch live `top_20`, `top_10`, `top_5`, `make_cut`, and `win` odds from
  DataGolf's betting-tools outrights endpoint.
- Evaluate all requested books that appear in the response.
- Use DataGolf's own baseline line as the fair probability source.
- Persist threshold-passing `BetCandidate` rows.
- Optionally write a daily analysis artifact that records play and no-play days.
- Keep existing matchup behavior unchanged.
- Let the existing operator console and `paper_trade.py` ticketing flow review
  and ticket the resulting candidates.

Out of scope for the proof build:

- Miss-cut live processing.
- Any custom golf-model overlay.
- Automated bet placement.
- Parameter tuning from early results.

## Market Mapping

| DataGolf market | Internal market | Sleeve |
|---|---|---|
| `top_20` | `top_20` | core |
| `top_10` | `top_10` | core |
| `top_5` | `top_5` | core |
| `make_cut` | `make_cut` | core |
| `win` | `outright_win` | convex |

Future mappings:

| DataGolf market | Internal market | Sleeve | Notes |
|---|---|---|---|
| `miss_cut` | `miss_cut` | core | Requires explicit inverse probability handling. |

## Edge Calculation

For forecast-backed outrights markets, the DataGolf betting-tools response
provides a DataGolf baseline line and book lines in the same player row. The
pipeline converts the DataGolf baseline American odds to a fair probability,
converts each book's American odds to an implied probability, and computes:

```text
edge = datagolf_fair_probability - book_implied_probability
```

This is intentionally conservative. Top-N and outright prices are one-sided
"yes" lines in this live endpoint; without a paired "no" price or a full-field
de-vig contract, the system cannot remove vig cleanly. The raw book implied
probability will usually be higher than the no-vig probability, so the edge
estimate is biased downward rather than inflated.

## Acceptance Criteria

- `scripts/run_pipeline.py --market top_20`, `--market top_10`,
  `--market top_5`, `--market make_cut`, and `--market outright_win` fetch live
  DataGolf odds, print candidate edges, and persist candidates when
  `--database-url` is set.
- `--market outright_win` fetches DataGolf `market=win` and persists internal
  `market_type="outright_win"` candidates so convex thresholds and sizing apply.
- `--dry-run` works without writing to the paper database.
- Requested books missing from the DataGolf response are warned about.
- `--analysis-output` writes a JSON artifact with event metadata, books checked,
  edge counts, qualified edges, near-misses, thresholds, and an artifact hash.
- Existing `tournament_matchups` behavior remains unchanged.
- Unit coverage proves forecast-backed edge generation, player mapping, and
  candidate persistence behavior without network calls.

## Expansion Path

After this proof path passes live smoke testing, add the remaining inverse
market family:

1. `miss_cut`

Each market should add a fixture-backed test before being enabled in the weekly
operator command.
