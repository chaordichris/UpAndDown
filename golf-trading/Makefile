.PHONY: install test lint fmt check backtest report init-db clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/

check: lint test

init-db:
	python scripts/init_db.py

backtest:
	python scripts/backtest.py

report:
	python scripts/report.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/
