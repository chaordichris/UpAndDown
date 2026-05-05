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

## 1. Ticket Operator Candidates

After ingestion, pricing, edge detection, and candidate persistence have run for
the tournament under review:

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
  --format json \
  --output artifacts/phase-gate.json
```

The gate criteria remain paper-trading based. Attached WS-7 backtest summaries
are supporting evidence, not pass/fail criteria.
