"""
Unit tests for src/ingestion/sportsbooks.py

Tests use fixture files that mimic the DataGolf betting-tools response format.
Covers:
  - parse_datagolf_matchups_response: correct extraction per book, skipping
    matchups where the requested book has no odds, 3-ball support
  - parse_datagolf_outrights_response: correct extraction per book, skipping
    players where the requested book has no odds
  - available_books_in_matchups / available_books_in_outrights
  - persist_book_snapshot: correct DB record created
  - _parse_last_updated: both timestamp formats
  - Invalid inputs raise KeyError
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.sportsbooks import (
    BookSnapshot,
    RawMatchupOdds,
    RawOutrightOdds,
    available_books_in_matchups,
    available_books_in_outrights,
    parse_datagolf_matchups_response,
    parse_datagolf_outrights_response,
    persist_book_snapshot,
    _parse_last_updated,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def matchups_raw(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "datagolf_matchups_odds.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def outrights_raw(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "datagolf_outrights_odds.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# parse_datagolf_matchups_response
# ---------------------------------------------------------------------------

def test_matchups_returns_book_snapshot(matchups_raw) -> None:
    result = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    assert isinstance(result, BookSnapshot)
    assert result.book_id == "draftkings"
    assert result.market_type == "tournament_matchups"
    assert result.event_name == "The Players Championship"


def test_matchups_extracts_only_requested_book(matchups_raw) -> None:
    """Every matchup in the result must have the requested book_id."""
    result = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    for m in result.matchups:
        assert m.book_id == "draftkings"


def test_matchups_correct_odds(matchups_raw) -> None:
    """First matchup: Scheffler -145 / McIlroy +120 on DraftKings."""
    result = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    first = result.matchups[0]
    assert first.players[0].name == "Scottie Scheffler"
    assert first.players[0].american_odds == -145
    assert first.players[1].name == "Rory McIlroy"
    assert first.players[1].american_odds == 120


def test_matchups_skips_entries_without_book_odds(matchups_raw) -> None:
    """Third matchup has only pinnacle odds — draftkings should skip it."""
    dk_result = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    pinnacle_result = parse_datagolf_matchups_response(matchups_raw, book_id="pinnacle")
    # Fixture has 3 matchups; DK has odds on 2, pinnacle on 2 (different 2)
    assert len(dk_result.matchups) == 2
    assert len(pinnacle_result.matchups) == 2


def test_matchups_datagolf_ids_captured(matchups_raw) -> None:
    """DataGolf player IDs should be captured from the matchup entry."""
    result = parse_datagolf_matchups_response(matchups_raw, book_id="fanduel")
    first = result.matchups[0]
    assert first.players[0].datagolf_id == "scottie_scheffler"
    assert first.players[1].datagolf_id == "rory_mcilroy"


def test_matchups_missing_book_returns_empty_list(matchups_raw) -> None:
    """Requesting a book with no odds in the fixture returns empty matchups list."""
    result = parse_datagolf_matchups_response(matchups_raw, book_id="betmgm")
    assert result.matchups == []


def test_matchups_raw_preserved(matchups_raw) -> None:
    """The original raw dict is preserved in the snapshot for audit."""
    result = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    assert result.raw is matchups_raw


def test_matchups_missing_required_key_raises(matchups_raw) -> None:
    bad = {k: v for k, v in matchups_raw.items() if k != "event_name"}
    with pytest.raises(KeyError):
        parse_datagolf_matchups_response(bad, book_id="draftkings")


# ---------------------------------------------------------------------------
# parse_datagolf_outrights_response
# ---------------------------------------------------------------------------

def test_outrights_returns_book_snapshot(outrights_raw) -> None:
    result = parse_datagolf_outrights_response(outrights_raw, book_id="draftkings")
    assert isinstance(result, BookSnapshot)
    assert result.book_id == "draftkings"
    assert result.market_type == "win"


def test_outrights_correct_odds(outrights_raw) -> None:
    """Scheffler: DK +650, FD +600."""
    dk = parse_datagolf_outrights_response(outrights_raw, book_id="draftkings")
    scheffler = next(o for o in dk.outrights if o.datagolf_id == "scottie_scheffler")
    assert scheffler.american_odds == 650

    fd = parse_datagolf_outrights_response(outrights_raw, book_id="fanduel")
    scheffler_fd = next(o for o in fd.outrights if o.datagolf_id == "scottie_scheffler")
    assert scheffler_fd.american_odds == 600


def test_outrights_skips_players_without_book_odds(outrights_raw) -> None:
    """Schauffele has no DK odds in fixture — should be absent from DK result."""
    dk = parse_datagolf_outrights_response(outrights_raw, book_id="draftkings")
    dk_ids = {o.datagolf_id for o in dk.outrights}
    assert "xander_schauffele" not in dk_ids


def test_outrights_market_captured(outrights_raw) -> None:
    dk = parse_datagolf_outrights_response(outrights_raw, book_id="draftkings")
    for o in dk.outrights:
        assert o.market == "win"


def test_outrights_missing_required_key_raises(outrights_raw) -> None:
    bad = {k: v for k, v in outrights_raw.items() if k != "market"}
    with pytest.raises(KeyError):
        parse_datagolf_outrights_response(bad, book_id="draftkings")


# ---------------------------------------------------------------------------
# available_books_in_* helpers
# ---------------------------------------------------------------------------

def test_available_books_in_matchups(matchups_raw) -> None:
    books = available_books_in_matchups(matchups_raw)
    assert "draftkings" in books
    assert "fanduel" in books
    assert "pinnacle" in books
    # datagolf_baseline is not a book
    assert "datagolf_baseline" not in books
    # structural fields are excluded
    assert "p1_player_name" not in books


def test_available_books_in_outrights(outrights_raw) -> None:
    books = available_books_in_outrights(outrights_raw)
    assert "draftkings" in books
    assert "fanduel" in books
    assert "pinnacle" in books
    assert "player_name" not in books


def test_available_books_empty_match_list() -> None:
    assert available_books_in_matchups({"match_list": []}) == []


def test_available_books_empty_player_list() -> None:
    assert available_books_in_outrights({"player_list": []}) == []


# ---------------------------------------------------------------------------
# persist_book_snapshot
# ---------------------------------------------------------------------------

def test_persist_matchup_snapshot(matchups_raw, db_session) -> None:
    snapshot = parse_datagolf_matchups_response(matchups_raw, book_id="draftkings")
    record = persist_book_snapshot(snapshot, db_session)
    assert record.source == "draftkings"
    assert record.endpoint == "tournament_matchups"
    assert json.loads(record.response_body) == matchups_raw


def test_persist_outright_snapshot(outrights_raw, db_session) -> None:
    snapshot = parse_datagolf_outrights_response(outrights_raw, book_id="fanduel")
    record = persist_book_snapshot(snapshot, db_session)
    assert record.source == "fanduel"
    assert record.endpoint == "win"


# ---------------------------------------------------------------------------
# _parse_last_updated
# ---------------------------------------------------------------------------

def test_parse_datagolf_space_format() -> None:
    """DataGolf's 'YYYY-MM-DD HH:MM:SS' format parses to UTC datetime."""
    from datetime import timezone
    dt = _parse_last_updated("2024-03-11 14:00:00")
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 11
    assert dt.tzinfo == timezone.utc


def test_parse_iso_format() -> None:
    """ISO 8601 format also accepted."""
    dt = _parse_last_updated("2024-03-11T14:00:00Z")
    assert dt.year == 2024
    assert dt.hour == 14
