"""
Unit tests for database models and connection management.
"""

from datetime import datetime

import pytest


def test_init_db_creates_tables(test_database_url):
    """init_db creates all expected tables."""
    from sqlalchemy import inspect

    from src.storage.db import get_engine, init_db

    engine = get_engine(test_database_url)
    init_db(test_database_url)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    expected_tables = {
        "tournaments",
        "players",
        "player_aliases",
        "raw_snapshots",
        "normalized_odds",
        "forecasts",
        "fair_prices",
        "bet_candidates",
        "bet_tickets",
        "placed_bets",
        "bet_outcomes",
        "clv_snapshots",
        "bankroll_history",
        "splash_raw_snapshots",
    }
    assert expected_tables.issubset(tables), (
        f"Missing tables: {expected_tables - tables}"
    )


def test_init_db_idempotent(test_database_url):
    """Calling init_db twice doesn't raise or corrupt the DB."""
    from src.storage.db import init_db
    init_db(test_database_url)
    init_db(test_database_url)  # should not raise


def test_init_db_retrofits_missing_column_on_existing_table(tmp_path):
    """A model gaining a column shouldn't break a database file created
    before the change — init_db should add the missing column instead of
    every subsequent query raising 'no such column'."""
    import sqlalchemy as sa

    from src.storage.db import get_engine, get_session, init_db
    from src.storage.models import BetCandidate

    # A dedicated, isolated file — the session-scoped test_database_url
    # fixture is shared across the whole test run and would already have a
    # full-shape bet_candidates table from earlier tests' init_db() calls.
    test_database_url = f"sqlite:///{tmp_path / 'retrofit-test.db'}"
    engine = get_engine(test_database_url)
    # Build bet_candidates without vig_removed — the shape it had before that
    # column existed — to simulate a database file from before the change.
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE bet_candidates (
                    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    market_type VARCHAR(50) NOT NULL,
                    side VARCHAR(50) NOT NULL,
                    player_id_1 INTEGER NOT NULL,
                    book VARCHAR(50) NOT NULL,
                    fair_prob FLOAT NOT NULL,
                    book_prob FLOAT NOT NULL,
                    edge_pct FLOAT NOT NULL,
                    passes_fdr BOOLEAN NOT NULL,
                    confidence_score FLOAT NOT NULL,
                    staleness_flag BOOLEAN NOT NULL,
                    inputs_hash VARCHAR(64) NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO bet_candidates
                    (tournament_id, market_type, side, player_id_1, book,
                     fair_prob, book_prob, edge_pct, passes_fdr,
                     confidence_score, staleness_flag, inputs_hash, created_at)
                VALUES (1, 'make_cut', '123', 1, 'draftkings', 0.5, 0.4, 0.1,
                        1, 1.0, 0, 'abc', '2026-01-01')
                """
            )
        )

    init_db(test_database_url)  # should retrofit vig_removed, not raise

    with get_session(test_database_url) as session:
        pre_existing = session.query(BetCandidate).filter_by(inputs_hash="abc").one()
        assert pre_existing.vig_removed is None  # honest "unknown" for old rows

        new_row = BetCandidate(
            tournament_id=1, market_type="make_cut", side="456", player_id_1=1,
            book="fanduel", fair_prob=0.6, book_prob=0.5, edge_pct=0.1,
            passes_fdr=True, confidence_score=1.0, staleness_flag=False,
            inputs_hash="def",
        )
        session.add(new_row)
        session.flush()
        assert new_row.vig_removed is True  # ORM default applies going forward


def test_create_tournament(db_session):
    """Can insert and retrieve a Tournament row."""
    from src.storage.models import Tournament

    t = Tournament(
        name="The Players Championship",
        course="TPC Sawgrass",
        tour="pga",
        start_date=datetime(2024, 3, 14),
        end_date=datetime(2024, 3, 17),
        purse_usd=25_000_000,
        field_size=144,
        datagolf_event_id="tpc_2024",
        status="scheduled",
    )
    db_session.add(t)
    db_session.flush()

    assert t.tournament_id is not None
    fetched = db_session.get(Tournament, t.tournament_id)
    assert fetched.name == "The Players Championship"
    assert fetched.tour == "pga"


def test_create_player_and_alias(db_session):
    """Can insert a Player and a PlayerAlias with FK integrity."""
    from src.storage.models import Player, PlayerAlias

    player = Player(
        datagolf_player_id="scottie_scheffler",
        name_canonical="Scottie Scheffler",
        country="USA",
    )
    db_session.add(player)
    db_session.flush()

    alias = PlayerAlias(
        player_id=player.player_id,
        source="dk",
        alias_name="S. Scheffler",
    )
    db_session.add(alias)
    db_session.flush()

    assert alias.alias_id is not None
    assert alias.player_id == player.player_id


def test_duplicate_alias_raises(db_session):
    """Inserting duplicate (alias_name, source) raises an integrity error."""
    from sqlalchemy.exc import IntegrityError

    from src.storage.models import Player, PlayerAlias

    player = Player(name_canonical="Test Player", datagolf_player_id="test_dup_alias")
    db_session.add(player)
    db_session.flush()

    a1 = PlayerAlias(player_id=player.player_id, source="dk", alias_name="T. Player")
    a2 = PlayerAlias(player_id=player.player_id, source="dk", alias_name="T. Player")
    db_session.add(a1)
    db_session.flush()
    db_session.add(a2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bankroll_history_roundtrip(db_session):
    """BankrollHistory row can be inserted and retrieved correctly."""
    from src.storage.models import BankrollHistory

    entry = BankrollHistory(
        date=datetime(2024, 3, 11),
        total_capital=10_000.0,
        reserve=5_000.0,
        active_core=4_000.0,
        convex_sleeve=1_000.0,
        active_core_peak=4_000.0,
        drawdown_from_peak_pct=0.0,
        drawdown_state="normal",
    )
    db_session.add(entry)
    db_session.flush()

    fetched = db_session.get(BankrollHistory, entry.entry_id)
    assert fetched.total_capital == 10_000.0
    assert fetched.drawdown_state == "normal"
    assert fetched.drawdown_from_peak_pct == 0.0


def test_bet_candidate_risk_metadata_roundtrip(db_session):
    """BetCandidate stores optional Batch C uncertainty and FDR metadata."""
    from src.storage.models import BetCandidate, Player, Tournament

    tournament = Tournament(name="Risk Metadata Open", tour="pga")
    player = Player(datagolf_player_id="risk_meta_player", name_canonical="Risk Meta Player")
    db_session.add_all([tournament, player])
    db_session.flush()

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="matchup_2ball",
        side="risk_meta_player",
        player_id_1=player.player_id,
        book="dk",
        fair_prob=0.56,
        book_prob=0.51,
        book_american_odds=-110,
        edge_pct=0.05,
        edge_sd=0.015,
        p_value=0.002,
        passes_fdr=True,
        confidence_score=1.0,
        staleness_flag=False,
    )
    db_session.add(candidate)
    db_session.flush()

    fetched = db_session.get(BetCandidate, candidate.candidate_id)
    assert fetched.edge_sd == 0.015
    assert fetched.p_value == 0.002
    assert fetched.passes_fdr is True


def test_session_rollback_on_error(test_database_url):
    """Session rolls back cleanly on exception."""
    from src.storage.db import get_session
    from src.storage.models import Player

    # Insert a player successfully
    with get_session(test_database_url) as session:
        player = Player(name_canonical="Rollback Test Player", datagolf_player_id="rollback_test")
        session.add(player)

    # Now cause a rollback by raising inside the context
    try:
        with get_session(test_database_url) as session:
            player2 = Player(name_canonical="Should Not Exist", datagolf_player_id="should_not_exist")
            session.add(player2)
            raise RuntimeError("intentional error")
    except RuntimeError:
        pass

    # Verify "Should Not Exist" is not in the DB
    with get_session(test_database_url) as session:
        result = session.query(Player).filter_by(datagolf_player_id="should_not_exist").first()
        assert result is None
