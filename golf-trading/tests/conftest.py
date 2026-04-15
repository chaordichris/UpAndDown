"""
Shared pytest fixtures for all tests.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Point tests at a temp SQLite DB
@pytest.fixture(scope="session", autouse=True)
def test_database_url(tmp_path_factory):
    """Create a temporary database URL for the test session."""
    tmp_dir = tmp_path_factory.mktemp("db")
    db_path = tmp_dir / "test_golf_trading.db"
    url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = url
    yield url
    # Cleanup handled automatically by tmp_path_factory


@pytest.fixture(scope="session")
def db_engine(test_database_url):
    """Create and initialize test DB engine."""
    from src.storage.db import get_engine, init_db
    engine = get_engine(test_database_url)
    init_db(test_database_url)
    yield engine


@pytest.fixture
def db_session(db_engine, test_database_url):
    """Yield a DB session that rolls back after each test."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def datagolf_forecast_fixture(fixtures_dir) -> dict:
    with open(fixtures_dir / "datagolf_forecast.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def dk_matchups_fixture(fixtures_dir) -> dict:
    with open(fixtures_dir / "dk_matchups.json") as f:
        return json.load(f)
