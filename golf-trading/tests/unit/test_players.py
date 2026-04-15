"""
Unit tests for src/normalization/players.py

Uses the shared in-memory test DB from conftest.py.
"""

from __future__ import annotations

import pytest

from src.normalization.players import PlayerResolver, _normalize_name
from src.storage.models import Player, PlayerAlias


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_session(db_session):
    """DB session pre-populated with a small set of players and aliases."""
    players = [
        Player(datagolf_player_id="scottie_scheffler", name_canonical="Scottie Scheffler", country="USA"),
        Player(datagolf_player_id="rory_mcilroy", name_canonical="Rory McIlroy", country="NIR"),
        Player(datagolf_player_id="jon_rahm", name_canonical="Jon Rahm", country="ESP"),
        Player(datagolf_player_id="collin_morikawa", name_canonical="Collin Morikawa", country="USA"),
    ]
    db_session.add_all(players)
    db_session.flush()

    # Add a known alias (DK sometimes uses abbreviated names)
    alias = PlayerAlias(
        player_id=players[1].player_id,  # Rory McIlroy
        alias_name="R. McIlroy",
        source="dk",
    )
    db_session.add(alias)
    db_session.flush()

    yield db_session


@pytest.fixture
def resolver(seeded_session):
    return PlayerResolver(seeded_session, fuzzy_threshold=0.85)


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

def test_exact_match_canonical_name(resolver) -> None:
    result = resolver.resolve("Scottie Scheffler", source="dk")
    assert result.datagolf_player_id == "scottie_scheffler"
    assert result.method == "exact"
    assert result.confidence == 1.0


def test_exact_match_case_insensitive(resolver) -> None:
    result = resolver.resolve("JON RAHM", source="fd")
    assert result.datagolf_player_id == "jon_rahm"
    assert result.method == "exact"


def test_exact_match_leading_trailing_whitespace(resolver) -> None:
    result = resolver.resolve("  Rory McIlroy  ", source="dk")
    assert result.datagolf_player_id == "rory_mcilroy"
    assert result.method == "exact"


# ---------------------------------------------------------------------------
# Alias match
# ---------------------------------------------------------------------------

def test_alias_match_source_specific(resolver) -> None:
    result = resolver.resolve("R. McIlroy", source="dk")
    assert result.datagolf_player_id == "rory_mcilroy"
    assert result.method == "alias"
    assert result.confidence == 1.0


def test_alias_not_found_for_different_source(resolver) -> None:
    """The alias 'R. McIlroy' is registered only for 'dk'; FD should not find it by alias."""
    # Should fall through to fuzzy match, not exact or alias
    result = resolver.resolve("R. McIlroy", source="fd")
    # Fuzzy: "R. McIlroy" vs "Rory McIlroy" is not above 0.85
    # Result may be fuzzy or unresolved depending on score — just check not alias
    assert result.method != "alias"


# ---------------------------------------------------------------------------
# Fuzzy match
# ---------------------------------------------------------------------------

def test_fuzzy_match_minor_typo(resolver) -> None:
    """Single character typo should still resolve via fuzzy matching."""
    # "Collin Morikawa" vs "Colin Morikawa" (one extra 'l')
    result = resolver.resolve("Colin Morikawa", source="dk")
    assert result.datagolf_player_id == "collin_morikawa"
    assert result.method == "fuzzy"
    assert result.confidence >= 0.85


def test_fuzzy_match_scores_below_threshold_returns_unresolved() -> None:
    """A name that looks completely different should not match."""
    # Use a very high threshold resolver so that only near-perfect matches pass
    from src.storage.db import get_engine, init_db
    import os
    from sqlalchemy.orm import sessionmaker

    # Reuse existing test DB
    engine = get_engine(os.environ["DATABASE_URL"])
    Session = sessionmaker(bind=engine)
    session = Session()
    players = [
        Player(datagolf_player_id="tiger_woods_test", name_canonical="Tiger Woods", country="USA"),
    ]
    session.add_all(players)
    session.flush()

    # Set threshold to 0.99 — "Eldrick Woods" should not match "Tiger Woods"
    strict_resolver = PlayerResolver(session, fuzzy_threshold=0.99)
    result = strict_resolver.resolve("Eldrick Woods", source="dk")
    assert result.datagolf_player_id is None
    assert result.method == "unresolved"

    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Unresolved
# ---------------------------------------------------------------------------

def test_completely_unknown_player(resolver) -> None:
    result = resolver.resolve("Completely Unknown Golfer XYZABC", source="dk")
    assert result.datagolf_player_id is None
    assert result.method == "unresolved"
    assert result.confidence < 0.85


def test_empty_name_returns_unresolved(resolver) -> None:
    result = resolver.resolve("", source="dk")
    assert result.datagolf_player_id is None
    assert result.method == "unresolved"


def test_whitespace_only_returns_unresolved(resolver) -> None:
    result = resolver.resolve("   ", source="dk")
    assert result.datagolf_player_id is None
    assert result.method == "unresolved"


# ---------------------------------------------------------------------------
# add_alias
# ---------------------------------------------------------------------------

def test_add_alias_persists_and_resolves(resolver, seeded_session) -> None:
    resolver.add_alias("jon_rahm", "J. Rahm", "fd")
    result = resolver.resolve("J. Rahm", source="fd")
    assert result.datagolf_player_id == "jon_rahm"
    assert result.method == "alias"


def test_add_alias_unknown_player_raises(resolver) -> None:
    with pytest.raises(LookupError, match="not found"):
        resolver.add_alias("nonexistent_player", "Ghost Player", "dk")


def test_add_duplicate_alias_raises(resolver, seeded_session) -> None:
    """Adding the same alias twice for the same source should raise ValueError."""
    resolver.add_alias("scottie_scheffler", "S. Scheffler", "fd")
    with pytest.raises(ValueError, match="already exists"):
        resolver.add_alias("scottie_scheffler", "S. Scheffler", "fd")


# ---------------------------------------------------------------------------
# _normalize_name helper
# ---------------------------------------------------------------------------

def test_normalize_name_strips_whitespace() -> None:
    assert _normalize_name("  Jon  Rahm  ") == "Jon Rahm"


def test_normalize_name_collapses_internal_spaces() -> None:
    assert _normalize_name("Jon  Rahm") == "Jon Rahm"
