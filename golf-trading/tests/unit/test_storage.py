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
    }
    assert expected_tables.issubset(tables), (
        f"Missing tables: {expected_tables - tables}"
    )


def test_init_db_idempotent(test_database_url):
    """Calling init_db twice doesn't raise or corrupt the DB."""
    from src.storage.db import init_db
    init_db(test_database_url)
    init_db(test_database_url)  # should not raise


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
