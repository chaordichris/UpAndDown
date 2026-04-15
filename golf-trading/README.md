# UpAndDown

A systematic golf betting framework for PGA Tour pre-tournament markets.

**Status:** Phase 0 — Foundation  
**Philosophy:** Survival first. DataGolf as pricing anchor. Matchups as core edge engine.

## Quick start

```bash
# 1. Clone and install
pip install -e ".[dev]"

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
├── config/           # settings.yaml, books.yaml, .env.example
├── docs/
│   ├── adr/          # Architecture decision records
│   └── skills/       # Skill specs per module
├── src/
│   ├── config.py     # Config loading
│   ├── storage/      # Database models and connection
│   ├── ingestion/    # DataGolf + sportsbook data fetching
│   ├── normalization/# Odds conversion, vig removal
│   ├── pricing/      # Fair odds engine
│   ├── risk/         # Bankroll, sizing, exposure
│   ├── execution/    # Bet tickets and logging
│   ├── backtest/     # Walk-forward simulator
│   └── monitoring/   # CLV, reporting
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── scripts/          # init_db.py, backtest.py, report.py
```

## Build phases

| Phase | Status | Description |
|-------|--------|-------------|
| 0 | ✅ Complete | Foundation: repo, config, storage, tests |
| 1 | 🔜 Next | Ingestion + normalization |
| 2 | ⏳ | Pricing + risk engine |
| 3 | ⏳ | Paper trading |
| 4 | ⏳ | Shadow live |
| 5 | ⏳ | Capital deployment |
| 6 | ⏳ | Iteration + expansion |

## Documentation

- [Build plan](../upanddown-build-plan.md) — Full architecture and roadmap
- [agent.md](agent.md) — Project charter for agentic development
- [ADRs](docs/adr/) — Architecture decisions
