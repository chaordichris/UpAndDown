"""
Database connection and session management.

Usage:
    from src.storage.db import get_engine, get_session, init_db

    # Create all tables (idempotent)
    init_db()

    # Use a session
    with get_session() as session:
        tournaments = session.query(Tournament).all()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def _get_database_url() -> str:
    """
    Resolve the database URL.

    Avoids importing get_settings() at module level so this module
    can be imported without pydantic-settings being configured.
    """
    url = os.environ.get("DATABASE_URL", "sqlite:///./data/db/golf_trading.db")
    return url


def _ensure_sqlite_dir(url: str) -> None:
    """Create the SQLite database directory if it doesn't exist."""
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _is_memory_sqlite(url: str) -> bool:
    """True for pure in-memory SQLite URLs, where each new Engine gets its own
    isolated database — unlike a file path or a real server, which persist
    state across separate Engine instances pointed at the same URL."""
    return url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url


# In-memory SQLite engines are cached by URL so that, e.g., a dry-run's
# init_db(url) and a later get_session(url) share the same actual database
# instead of each silently getting its own empty one (real file/server URLs
# don't need this — the file/server itself is the shared state).
_memory_engines_by_url: dict[str, Engine] = {}


def get_engine(database_url: str | None = None) -> Engine:
    """
    Create a SQLAlchemy engine.

    For SQLite, enables WAL mode and foreign key enforcement.
    For other databases, uses default settings.
    """
    url = database_url or _get_database_url()
    _ensure_sqlite_dir(url)

    if _is_memory_sqlite(url) and url in _memory_engines_by_url:
        return _memory_engines_by_url[url]

    engine = create_engine(
        url,
        echo=False,  # Set to True for SQL debug logging
        # SQLite-specific: allow sharing connection across threads
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )

    # SQLite pragmas: WAL mode for better concurrency, FK enforcement
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    if _is_memory_sqlite(url):
        _memory_engines_by_url[url] = engine

    return engine


# Module-level engine and session factory (lazy-initialized)
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _get_or_create_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def _get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_or_create_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


@contextmanager
def get_session(database_url: str | None = None) -> Generator[Session, None, None]:
    """
    Context manager that yields a SQLAlchemy Session.

    Commits on clean exit, rolls back on exception.

    Example:
        with get_session() as session:
            session.add(some_record)
            # auto-committed on exit
    """
    if database_url:
        engine = get_engine(database_url)
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    else:
        factory = _get_session_factory()

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(database_url: str | None = None) -> None:
    """
    Create all tables. Safe to call multiple times (idempotent via CREATE IF NOT EXISTS).
    """
    engine = get_engine(database_url) if database_url else _get_or_create_engine()
    Base.metadata.create_all(bind=engine)


def drop_all(database_url: str | None = None) -> None:
    """
    Drop all tables. Used in tests only.
    """
    engine = get_engine(database_url) if database_url else _get_or_create_engine()
    Base.metadata.drop_all(bind=engine)
