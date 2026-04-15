"""
Sportsbook odds ingestion.

DraftKings and FanDuel don't expose public APIs for golf markets.
Phase 1 provides:
  1. Typed dataclasses for raw book odds (the interface downstream modules consume).
  2. Parsers for the fixture JSON formats used in tests.
  3. A snapshot persister that writes a RawSnapshot to the DB.
  4. Stub fetchers (TODO) with clear contracts for live implementation.

Live fetching will require either:
  - A commercial odds aggregator API (e.g., OddsJam, The Odds API).
  - Manual export / paste from book.
  - Headless browser scraping (maintenance-heavy; not built here yet).

The parsers and DB persistence logic are complete and tested.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.storage.models import RawSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed raw data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawPlayerOdds:
    """A single player's raw odds from one side of a matchup."""

    name: str           # Player name as displayed by the book
    american_odds: int  # American odds (e.g., -145 or +120)


@dataclass(frozen=True)
class RawMatchupOdds:
    """Raw two-way or three-way matchup odds from a single book snapshot."""

    matchup_id: str             # Book-assigned matchup identifier
    players: list[RawPlayerOdds]  # 2 (matchup) or 3 (3-ball) players
    market_type: str            # "matchup_2ball" or "matchup_3ball"
    book_id: str                # "dk" | "fd"
    captured_at: datetime       # When this snapshot was taken


@dataclass
class BookSnapshot:
    """Parsed output of one raw book response."""

    book_id: str
    market_type: str
    event_name: str
    captured_at: datetime
    matchups: list[RawMatchupOdds]
    raw: dict[str, Any] = field(repr=False)  # original dict for audit


# ---------------------------------------------------------------------------
# Parsers — convert raw dict (from fixture or live source) to BookSnapshot
# ---------------------------------------------------------------------------

def parse_dk_matchups(raw: dict[str, Any]) -> BookSnapshot:
    """Parse a DraftKings matchup odds payload.

    Expected structure matches tests/fixtures/dk_matchups.json:
    {
      "source": "draftkings",
      "event": "<name>",
      "market_type": "matchup_2ball",
      "captured_at": "<ISO8601>",
      "matchups": [
        {
          "matchup_id": "<id>",
          "player_1": {"name": "<name>", "american_odds": <int>},
          "player_2": {"name": "<name>", "american_odds": <int>}
        }
      ]
    }

    Raises:
        KeyError: If required fields are missing.
        ValueError: If the payload cannot be interpreted.
    """
    _validate_book_source(raw, expected_source="draftkings")
    market_type = raw["market_type"]
    captured_at = _parse_datetime(raw["captured_at"])
    n_players = _players_for_market(market_type)

    matchups = []
    for m in raw["matchups"]:
        players = _extract_players(m, n_players, book_id="dk")
        matchups.append(
            RawMatchupOdds(
                matchup_id=m["matchup_id"],
                players=players,
                market_type=market_type,
                book_id="dk",
                captured_at=captured_at,
            )
        )

    return BookSnapshot(
        book_id="dk",
        market_type=market_type,
        event_name=raw.get("event", ""),
        captured_at=captured_at,
        matchups=matchups,
        raw=raw,
    )


def parse_fd_matchups(raw: dict[str, Any]) -> BookSnapshot:
    """Parse a FanDuel matchup odds payload.

    FanDuel uses the same JSON structure as DraftKings in our internal format
    (sportsbooks export / intermediary layer normalises to a shared schema).
    The only difference is source="fanduel".

    Raises:
        KeyError: If required fields are missing.
        ValueError: If the payload cannot be interpreted.
    """
    _validate_book_source(raw, expected_source="fanduel")
    market_type = raw["market_type"]
    captured_at = _parse_datetime(raw["captured_at"])
    n_players = _players_for_market(market_type)

    matchups = []
    for m in raw["matchups"]:
        players = _extract_players(m, n_players, book_id="fd")
        matchups.append(
            RawMatchupOdds(
                matchup_id=m["matchup_id"],
                players=players,
                market_type=market_type,
                book_id="fd",
                captured_at=captured_at,
            )
        )

    return BookSnapshot(
        book_id="fd",
        market_type=market_type,
        event_name=raw.get("event", ""),
        captured_at=captured_at,
        matchups=matchups,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def persist_book_snapshot(
    snapshot: BookSnapshot,
    session: Any,  # SQLAlchemy Session
    tournament_id: int | None = None,
) -> RawSnapshot:
    """Persist the raw book payload to the RawSnapshot table.

    Args:
        snapshot: Parsed BookSnapshot (raw dict included).
        session: Active SQLAlchemy session. Caller manages lifecycle.
        tournament_id: FK to the Tournament table if known; None otherwise.

    Returns:
        The newly created RawSnapshot ORM object (flushed, not committed).
    """
    raw_record = RawSnapshot(
        source=snapshot.book_id,
        endpoint=snapshot.market_type,
        tournament_id=tournament_id,
        fetched_at=snapshot.captured_at,
        response_body=json.dumps(snapshot.raw),
    )
    session.add(raw_record)
    session.flush()
    logger.debug(
        "Persisted %s snapshot: book=%s market=%s matchups=%d",
        snapshot.captured_at.isoformat(),
        snapshot.book_id,
        snapshot.market_type,
        len(snapshot.matchups),
    )
    return raw_record


# ---------------------------------------------------------------------------
# Live fetch stubs (TODO)
# ---------------------------------------------------------------------------

def fetch_dk_matchups(
    tour: str = "pga",
    event_id: str | None = None,
) -> dict[str, Any]:
    """Fetch live DraftKings matchup odds.

    TODO: Implement via commercial odds API or scraping layer.
          For now, raises NotImplementedError to make the gap explicit.
    """
    raise NotImplementedError(
        "Live DraftKings odds fetching is not yet implemented. "
        "Use a fixture file or a commercial odds aggregator API."
    )


def fetch_fd_matchups(
    tour: str = "pga",
    event_id: str | None = None,
) -> dict[str, Any]:
    """Fetch live FanDuel matchup odds.

    TODO: Implement via commercial odds API or scraping layer.
    """
    raise NotImplementedError(
        "Live FanDuel odds fetching is not yet implemented. "
        "Use a fixture file or a commercial odds aggregator API."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_book_source(raw: dict[str, Any], expected_source: str) -> None:
    source = raw.get("source", "")
    if source.lower() != expected_source.lower():
        raise ValueError(
            f"Expected source={expected_source!r}, got {source!r}. "
            "Check that you're using the right parser."
        )


def _players_for_market(market_type: str) -> int:
    """Return the expected number of players for a market type."""
    mapping = {
        "matchup_2ball": 2,
        "matchup_3ball": 3,
    }
    n = mapping.get(market_type)
    if n is None:
        raise ValueError(
            f"Unknown market type: {market_type!r}. "
            f"Supported: {sorted(mapping)}"
        )
    return n


def _extract_players(
    matchup_dict: dict[str, Any],
    n_players: int,
    book_id: str,
) -> list[RawPlayerOdds]:
    """Extract player odds from a matchup dict.

    Supports:
      - player_1 / player_2 keys (2-ball)
      - player_1 / player_2 / player_3 keys (3-ball)
    """
    players = []
    for i in range(1, n_players + 1):
        key = f"player_{i}"
        p = matchup_dict[key]
        players.append(
            RawPlayerOdds(
                name=p["name"],
                american_odds=int(p["american_odds"]),
            )
        )
    return players


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
