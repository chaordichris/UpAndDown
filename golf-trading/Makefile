.PHONY: install test test-cov lint fmt check backtest report init-db clean

PYTHON ?= python3
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) tests/ -v --tb=short

test-cov:
	$(PYTEST) tests/ --cov=src --cov-report=term-missing

lint:
	$(RUFF) check src/ tests/

fmt:
	$(RUFF) format src/ tests/

check: lint test

init-db:
	$(PYTHON) scripts/init_db.py

backtest:
	@echo "Backtesting is not implemented yet. See docs/agent-execution-plan.md (WS-7)." >&2
	@exit 1

report:
	@echo "Reporting is not implemented yet. See docs/agent-execution-plan.md (WS-8)." >&2
	@exit 1

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/
