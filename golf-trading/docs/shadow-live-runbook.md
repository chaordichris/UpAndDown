# Shadow-Live / Minimum-Stake Runbook

Shadow-live is **Phase 4 operational learning**: real money at minimum stakes,
manually placed at the book, recorded in the same database as paper bets.

Shadow-live activity is NOT Phase 3 gate evidence. The paper-trade count,
CLV, and phase-gate artifacts remain the formal gate path. Shadow-live bets
are excluded from all paper-trade metrics and evidence checks.

## Separation guarantee

| Dimension | Paper | Shadow-Live |
|---|---|---|
| `placed_bets.placement_method` | `manual` | `shadow_live` |
| Counts in paper report | YES | NO |
| Counts toward Phase 3 gate | YES | NO |
| Evidence check contamination | NO | NO (real, intentional) |
| Operator console metric panel | Paper summary | Shadow-live panel |

## Preconditions

- Phase 3 paper trading is running and at least partially complete.
- You have a small real bankroll at one or more sportsbooks.
- You have read and accepted the constraints in `agent.md`.
- No automated placement of any kind.

## 1. Enable Shadow-Live Mode

Edit `config/settings.yaml`. The defaults are conservative:

```yaml
shadow_live:
  enabled: true              # flip to true to allow real-stake placements
  starting_bankroll_dollars: 500.0
  per_bet_cap_dollars: 25.0
  per_tournament_cap_dollars: 100.0
```

Keep `enabled: false` for pure paper-trading weeks. Set `enabled: true` only
when you intend to place real bets this tournament week.

**Do not increase the caps without deliberate review.** The per-bet and
per-tournament caps are enforced by the guardrail before any write.

## 2. Open the Operator Console

Use the same console as paper trading — both modes live in the same DB:

```bash
PAPER_DB=sqlite:////private/tmp/upanddown-paper-review.db
PYTHONPATH=. .venv/bin/python scripts/operator_console.py \
  --database-url "$PAPER_DB" \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765`.

The **Shadow-Live Status** panel shows:

- Mode: ENABLED / DISABLED (reflects `shadow_live.enabled`)
- Per-bet and per-tournament caps
- Current tournament shadow-live totals
- Running P&L (informational)

## 3. Select Candidates and Create Tickets

Candidate import, ticketing, and ticket review work identically to paper
trading. There is no separate ticket type for shadow-live — you use the same
tickets for both.

```bash
# (same as paper — use operator console or CLI)
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py ticket-candidates \
  --database-url "$PAPER_DB" \
  --total-bankroll 25000
```

## 4. Place a Shadow-Live Bet

In the **Tickets** table, locate an approved unplaced ticket. In the Place
form:

1. Confirm actual odds (update if line has moved).
2. Set stake (must not exceed `per_bet_cap_dollars`).
3. **Change the mode dropdown from `PAPER` to `SHADOW LIVE`.**
4. Add audit notes (e.g. "Placed DraftKings 12:05 ET, line at -108").
5. Click **Place**.

The guardrail runs before any write. If shadow-live is disabled or a cap
is exceeded, the console returns an error and nothing is written.

**Manually place the bet at the book BEFORE or IMMEDIATELY AFTER recording
it in the console.** The console records provenance; the book records the
actual wager.

## 5. Settlement, CLV, and Attribution

Settlement, CLV, and attribution workflows are identical to paper bets —
the console settle, CLV, and attribution forms work on any `placed_bet` row
regardless of placement method.

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py settle-bet BET_ID win \
  --database-url "$PAPER_DB"

PYTHONPATH=. .venv/bin/python scripts/paper_trade.py record-clv BET_ID \
  --database-url "$PAPER_DB" \
  --closing-odds -115
```

Shadow-live outcomes feed the informational Shadow-Live Status panel but are
excluded from the Phase 3 paper report and phase-gate artifacts.

## 6. Audit and Provenance

Every shadow-live placement is recorded with:
- `placement_method = "shadow_live"` (permanent discriminator)
- `placed_at` timestamp
- `actual_american_odds` (odds at time of placement)
- `actual_stake` (real money placed)
- `notes` (operator audit notes — include book, time, and any line detail)

Run the paper report to confirm shadow-live bets are excluded from gate
evidence counts:

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py report \
  --database-url "$PAPER_DB"
```

The paper report counts only `manual` placements. Shadow-live bets appear
only in the Shadow-Live Status panel of the operator console.

## 7. Evidence Check Before Gate Review

Run the evidence check as normal. Shadow-live bets do NOT cause the
`manual_placements_only` criterion to fail — they are intentional real
placements, not synthetic contamination.

```bash
PYTHONPATH=. .venv/bin/python scripts/paper_trade.py evidence-check \
  --database-url "$PAPER_DB" \
  --required-tournaments 4 \
  --required-settled-bets 60
```

## Guardrails summary

| Check | Blocks on |
|---|---|
| `enabled` flag | Mode is `false` in settings |
| Per-bet cap | `actual_stake > per_bet_cap_dollars` |
| Per-tournament cap | Tournament shadow-live total + stake > `per_tournament_cap_dollars` |

All three checks happen before any DB write. Errors are shown in the
console message bar.

## What shadow-live is not

- It is not automated. You still walk to DraftKings or FanDuel and place the
  bet yourself.
- It is not Phase 3 gate evidence. Paper remains the gate.
- It is not a substitute for the CLV and attribution discipline.
- It is not permission to increase stake sizes. Stay within the caps.
