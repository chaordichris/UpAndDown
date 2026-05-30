# Phase 3 Paper-Trading Proof Runbook

This runbook is for real operator-entered paper trading. Do not use fixture or
smoke data as Phase 3 gate evidence. DataGolf remains the model anchor, and all
execution is manual.

## Preconditions

- Run from `golf-trading/`.
- Use `PYTHONPATH=.` and `.venv/bin/python`.
- Use the real paper-trading database chosen for Phase 3 review.
- Only operator-entered placements, settlements, and closing lines count toward
  the Phase 3 to Phase 4 gate.

```bash
PAPER_DB=sqlite:////private/tmp/upanddown-paper-review.db
```

## 0a. Run The Pipeline

Before anything else, fetch live data and generate candidates for this week's
tournament. This is the upstream step that feeds everything below.

```bash
# Dry-run first to see what edges exist (no DB writes):
PYTHONPATH=. .venv/bin/python scripts/run_pipeline.py \
  --tour pga \
  --books draftkings fanduel \
  --dry-run

# If edges look reasonable, persist to the paper DB:
PYTHONPATH=. .venv/bin/python scripts/run_pipeline.py \
  --database-url "$PAPER_DB" \
  --tour pga \
  --books draftkings fanduel
```

The script fetches live matchup odds from DataGolf's betting-tools endpoint,
prices every 2-ball matchup via DG's own baseline, computes edges per requested
book, and persists Tournament, Player, and BetCandidate rows. Only matchups
above the configured edge threshold (default 3% core) become candidates.

Run this once or twice during tournament week (e.g., Tuesday evening and
Wednesday morning) to capture line snapshots at different times.

## 0b. Open The Operator Console

For tournament-week operation, use the local console to review candidates,
create tickets, place bets, settle bets, record CLV, and record attribution
against the same paper database used by the CLI commands below.

```bash
PYTHONPATH=. .venv/bin/python scripts/operator_console.py \
  --database-url "$PAPER_DB" \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765`. The console is local-only and does not automate
book placement; it writes the same manual paper-trading rows as
`scripts/paper_trade.py`.

## 1. Ticket Operator Candidates

After the pipeline has run for the tournament under review:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py list-candidates \
  --database-url "$PAPER_DB" \
  --open-only

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py ticket-candidates \
  --database-url "$PAPER_DB" \
  --total-bankroll 25000
```

Review the bet slips before manual entry:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py list-tickets \
  --database-url "$PAPER_DB" \
  --unplaced

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py export-tickets \
  --database-url "$PAPER_DB" \
  --unplaced \
  --approved-only
```

## 2. Record Manual Placement

For every approved ticket, record the actual operator outcome. If the bet was
not placed because the line moved or the book rejected it, record that as a
rejection instead of deleting the ticket.

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py place-ticket TICKET_ID \
  --database-url "$PAPER_DB" \
  --actual-odds -105 \
  --actual-stake 25.00 \
  --notes "operator-entered pre-tournament paper placement"
```

## 3. Record Settlement, CLV, And Attribution

After the event settles:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py settle-bet BET_ID win \
  --database-url "$PAPER_DB"

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py record-clv BET_ID \
  --database-url "$PAPER_DB" \
  --closing-odds -125

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py record-attribution BET_ID \
  --database-url "$PAPER_DB"
```

Repeat until the paper DB contains at least 4 tournaments and 60 settled paper
bets. Until then, the Phase 3 gate is expected to fail.

## 4. Check Review Readiness

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py readiness \
  --database-url "$PAPER_DB" \
  --required-tournaments 4 \
  --required-settled-bets 60
```

The readiness check is an operator diagnostic, not the phase gate itself. It
flags undersized samples, open approved tickets, pending settlements, missing
CLV, and missing attribution before the review packet is assembled.

For an auditable readiness artifact:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py readiness \
  --database-url "$PAPER_DB" \
  --required-tournaments 4 \
  --required-settled-bets 60 \
  --format json \
  --output artifacts/phase3-readiness.json
```

## 5. Check Evidence Provenance

Before assembling gate artifacts, run the evidence guardrail. It reuses the
readiness checks and also flags smoke, fixture, or backtest rows that must not
be counted as real operator-entered Phase 3 evidence.

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py evidence-check \
  --database-url "$PAPER_DB" \
  --required-tournaments 4 \
  --required-settled-bets 60
```

For an auditable evidence artifact:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py evidence-check \
  --database-url "$PAPER_DB" \
  --required-tournaments 4 \
  --required-settled-bets 60 \
  --format json \
  --output artifacts/phase3-evidence.json
```

The evidence check is a guardrail, not a replacement for the phase gate. If it
reports `Evidence clean: NO`, stop and remove the contaminated review database
from Phase 3 evidence before continuing.

## 6. Export Paper Report

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py report \
  --database-url "$PAPER_DB" \
  --format json \
  --output artifacts/paper-report.json
```

The report artifact is review evidence. It includes ticket, placement,
settlement, CLV, attribution, strategy P&L, promo P&L, realized P&L, and ROI
counts/totals.

## 7. Attach Phase-Gate Review

```bash
PYTHONPATH=. .venv/bin/python scripts/phase_gate_check.py \
  --database-url "$PAPER_DB" \
  --paper-tournaments 4 \
  --pipeline-crashes 0 \
  --data-completeness 0.95 \
  --starting-bankroll 10000 \
  --peak-bankroll 10000 \
  --stake-fraction 0.01 \
  --expected-return 0.02 \
  --return-sd 1.0 \
  --backtest-summary-json artifacts/backtest-review.json \
  --phase3-evidence-json artifacts/phase3-evidence.json \
  --format json \
  --output artifacts/phase-gate.json
```

The gate criteria remain paper-trading based. Attached WS-7 backtest summaries
are supporting evidence, not pass/fail criteria. The attached Phase 3 evidence
artifact must pass before the phase-gate artifact can be assembled.

## 8. Bundle Review Artifacts

After replay, backtest-review, paper-report, evidence-check, and phase-gate
artifacts exist, build the review bundle:

```bash
PYTHONPATH=. .venv/bin/python scripts/artifact_bundle.py \
  --replay artifacts/replay.json \
  --backtest-review artifacts/backtest-review.json \
  --paper-report artifacts/paper-report.json \
  --phase3-evidence artifacts/phase3-evidence.json \
  --phase-gate artifacts/phase-gate.json \
  --format json \
  --output artifacts/review-bundle.json
```

The bundle records file-level SHA-256 values and embedded artifact hashes so
the manual review packet can be rechecked without trusting filenames alone.
