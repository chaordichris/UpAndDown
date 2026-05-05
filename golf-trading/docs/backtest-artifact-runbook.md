# WS-7 Backtest Artifact Runbook

This runbook describes the manual, auditable artifact chain for leakage-checked
backtest review. It does not automate live betting and does not introduce any
custom golf-model overlay. DataGolf forecast probabilities remain the pricing
anchor.

## Preconditions

- Run from `golf-trading/`.
- Use `PYTHONPATH=.` and `.venv/bin/python`.
- Use a fresh event database for each replay. `scripts/backtest_replay.py`
  refuses non-empty event DBs so row IDs and artifact hashes stay deterministic.
- Keep one event DB per tournament or fixture replay.

## 1. Replay One Event

```bash
EVENT_DB=sqlite:////private/tmp/upanddown-ws7-event.db

PYTHONPATH=. .venv/bin/python scripts/backtest_replay.py \
  --fixture tests/fixtures/replay/backtest_multi_market_core_replay.json \
  --database-url "$EVENT_DB" \
  --format json \
  --output artifacts/replay.json
```

Outputs:

- Event DB with forecast, candidate, ticket, placement, settlement, and CLV rows.
- Stable replay manifest at `artifacts/replay.json`.
- Manifest hashes for forecast, candidate, ticket, settlement, report, and full
  replay.

## 2. Build Multi-Event Review

```bash
PYTHONPATH=. .venv/bin/python scripts/backtest_review.py \
  --event core_markets="$EVENT_DB" \
  --format json \
  --output artifacts/backtest-review.json
```

Repeat `--event label=database_url` once per event DB when reviewing multiple
tournaments.

Outputs:

- Stable review artifact at `artifacts/backtest-review.json`.
- Multi-event summary with tournament count, ticket count, settled count,
  staked amount, strategy and realized P&L, ROI, average edge, average CLV, and
  positive CLV rate.
- `summary_hash` and `manifest_hash` for audit trails.

`scripts/backtest_review.py` refuses empty event DBs so typo paths cannot become
zeroed review evidence.

The verification smoke test exercises this as a three-event review with the
make-cut, core-market, and top-5/outright replay fixtures.

## 3. Export Paper-Trade Report

```bash
PAPER_DB=sqlite:////private/tmp/upanddown-paper-review.db

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py report \
  --database-url "$PAPER_DB" \
  --format json \
  --output artifacts/paper-report.json
```

Outputs:

- Stable JSON view of the current paper-trading DB report.
- `artifact_hash` for the paper-report payload.
- Ticket, placement, settlement, CLV, attribution, strategy P&L, promo P&L,
  realized P&L, and ROI counts/totals.

## 4. Attach To Phase-Gate Review

```bash
PYTHONPATH=. .venv/bin/python scripts/phase_gate_check.py \
  --database-url "$PAPER_DB" \
  --paper-tournaments 1 \
  --pipeline-crashes 0 \
  --data-completeness 1.0 \
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

The Phase 3 to Phase 4 gate remains paper-trading based. Attached backtest
summary metrics are review evidence, not gate criteria. If
`--phase3-evidence-json` is provided, it must be a passing evidence-check
artifact.

A smoke database with fewer than 4 paper tournaments or 60 settled paper bets is
expected to fail the gate while still producing a valid JSON artifact.

## 5. Bundle Review Artifacts

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

Outputs:

- Stable file-level review bundle at `artifacts/review-bundle.json`.
- SHA-256 hash for each rendered artifact file.
- Embedded artifact hashes surfaced from replay, backtest-review, paper-report,
  phase3-evidence, and phase-gate JSON when present.
- `bundle_hash` tying the reviewed artifact files into one audit index.

## Useful Fixtures

- `tests/fixtures/replay/backtest_forecast_candidate_replay.json`: DraftKings
  make-cut fixture with one approved ticket and one rejected ticket.
- `tests/fixtures/replay/backtest_multi_market_core_replay.json`: FanDuel
  top-10/top-20 core-market fixture with mixed approved/rejected tickets,
  settlement, and CLV.
- `tests/fixtures/replay/backtest_top5_outright_replay.json`: DraftKings
  top-5 plus outright fixture with core and convex-sleeve tickets, mixed
  approved/rejected tickets, settlement, and CLV.

## Verification

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/unit/test_backtest_replay_script.py \
  tests/unit/test_artifact_bundle.py \
  tests/unit/test_backtest_review.py \
  tests/unit/test_paper_trade_report_cli.py \
  tests/unit/test_phase_gate_check.py \
  tests/unit/test_backtest_replay.py \
  tests/unit/test_backtest_summary.py \
  tests/integration/test_backtest_artifact_workflow.py \
  tests/replay/test_backtest_forecast_candidate_replay.py \
  tests/replay/test_backtest_multi_tournament_summary_replay.py \
  -q
```
