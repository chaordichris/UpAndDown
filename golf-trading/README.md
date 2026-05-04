# UpAndDown

A systematic golf betting framework for PGA Tour pre-tournament markets.

**Status:** Phase 2 baseline complete; Phase 3 paper trading underway  
**Philosophy:** Survival first. DataGolf as pricing anchor. Matchups as core edge engine.

## Quick start

```bash
# 1. Use Python 3.11+ and install
python3 -m pip install -e ".[dev]"

# 2. Configure secrets
cp config/.env.example .env
# Edit .env: add your DATAGOLF_API_KEY

# 3. Initialize the database
make init-db

# 4. Run tests
make test
```

## Project structure

```
golf-trading/
├── AGENTS.md         # Codex-local repo instructions
├── CLAUDE.md         # Claude-local repo instructions
├── agent.md          # Shared project charter
├── config/           # settings.yaml, books.yaml, .env.example
├── docs/
│   ├── adr/          # Architecture decision records
│   ├── agent-execution-plan.md
│   └── backtest-artifact-runbook.md
├── src/
│   ├── config.py     # Config loading
│   ├── storage/      # Database models and connection
│   ├── ingestion/    # DataGolf + sportsbook data fetching
│   ├── normalization/ # Odds conversion, vig removal
│   ├── pricing/      # Fair odds engine
│   ├── risk/         # Bankroll, sizing, exposure
│   ├── execution/    # Paper-trade tickets, placement, settlement
│   ├── backtest/     # Leakage-checked replay and summaries
│   └── monitoring/   # CLV, attribution, reports
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── scripts/          # init_db.py today; paper-trading/reporting scripts planned
```

## Build phases

| Phase | Status | Description |
|-------|--------|-------------|
| 0 | ✅ Complete | Foundation: repo, config, storage, tests |
| 1 | ✅ Complete | Ingestion + normalization |
| 2 | ✅ Complete | Pricing + baseline risk engine |
| 3 | In progress | Paper trading |
| 4 | ⏳ | Shadow live |
| 5 | ⏳ | Capital deployment |
| 6 | ⏳ | Iteration + expansion |

## Documentation

- [Build plan](../upanddown-build-plan.md) — Full architecture and roadmap
- [Build plan addendum](../upanddown-build-plan-v0.2-addendum.md) — Quant-risk review and v0.2 upgrades
- [agent.md](agent.md) — Shared project charter
- [AGENTS.md](AGENTS.md) — Codex-local repo instructions
- [Agent execution plan](docs/agent-execution-plan.md) — Current workstream backlog and handoff rules
- [Backtest artifact runbook](docs/backtest-artifact-runbook.md) — Manual WS-7 replay, review, and phase-gate artifact chain
- [ADRs](docs/adr/) — Architecture decisions
- [Shared skills](../skills/README.md) — Tool-agnostic skill source
