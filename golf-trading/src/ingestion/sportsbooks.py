"""
Sportsbook odds parsing.

DataGolf's betting-tools endpoints return odds from multiple sportsbooks
in a single response, so there is no need for separate per-book fetchers.
Use DataGolfClient.fetch_live_matchups() / fetch_live_outrights() to
retrieve raw data, then call the parsers here to produce typed objects.

Two response shapes are handled:

  /betting-tools/matchups  →  parse_datagolf_matchups_response()
  /betting-tools/outrights →  parse_datagolf_outrights_response()

Both return a list of typed odds objects plus a BookSnapshot (one per
book_id extracted from the response). Downstream modules consume the
typed objects; the BookSnapshot is persisted to the DB for audit.

NOTE: The DataGolf response format documented here is inferred from API
descriptions (not a live response). If field names differ, update the
_MATCHUP_PLAYER_KEYS / _OUTRIGHT_BOOKS constants and re-run tests.
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
# DataGolf book IDs present in betting-tools responses.
# These are the keys in each match/player dict that hold book odds.
# Update this list when DataGolf adds or removes a book.
# ---------------------------------------------------------------------------
DATAGOLF_BOOK_IDS: tuple[str, ...] = (
    "draftkings",
    "fanduel",
    "betmgm",
    "caesars",
    "bet365",
    "pinnacle",
    "betway",
    "unibet",
    "williamhill",
    "bovada",
    "betonline",
)

# Keys in a matchup entry that are NOT book odds (structural fields).
_MATCHUP_META_KEYS = frozenset({
    "p1_player_name", "p2_player_name", "p3_player_name",
    "p1_datagolf_id", "p2_datagolf_id", "p3_datagolf_id",
    "datagolf_baseline", "datagolf_baseline_history_fit",
})

# Keys in an outright player entry that are NOT book odds.
_OUTRIGHT_META_KEYS = frozenset({
    "player_name", "datagolf_id",
    "datagolf_baseline", "datagolf_baseline_history_fit",
})


# ---------------------------------------------------------------------------
# Typed output containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawPlayerOdds:
    """One player's odds on one side of a matchup."""
    name: str
    datagolf_id: str
    american_odds: int


@dataclass(frozen=True)
class RawMatchupOdds:
    """A single matchup (2-ball or 3-ball) from one book, one snapshot."""
    matchup_id: str             # "<event>_<p1_id>_vs_<p2_id>"
    players: list[RawPlayerOdds]
    market_type: str            # "tournament_matchups" | "round_matchups" | "3_balls"
    book_id: str
    captured_at: datetime


@dataclass(frozen=True)
class RawOutrightOdds:
    """One player's outright odds from one book, one snapshot."""
    player_name: str
    datagolf_id: str
    american_odds: int
    market: str                 # "win" | "top_5" | "top_10" | "top_20" | "make_cut"
    book_id: str
    captured_at: datetime


@dataclass
class BookSnapshot:
    """Parsed output of one betting-tools response, for one book."""
    book_id: str
    market_type: str
    event_name: str
    captured_at: datetime
    matchups: list[RawMatchupOdds] = field(default_factory=list)
    outrights: list[RawOutrightOdds] = field(default_factory=list)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_datagolf_matchups_response(
    raw: dict[str, Any],
    book_id: str,
) -> BookSnapshot:
    """Parse a DataGolf /betting-tools/matchups response for one book.

    Expected top-level keys: event_name, tour, market, last_updated, match_list.

    Each entry in match_list:
      p1_player_name, p2_player_name, [p3_player_name]
      p1_datagolf_id, p2_datagolf_id, [p3_datagolf_id]
      "<book_id>": {"p1_odds": int, "p2_odds": int, ["p3_odds": int]}
      datagolf_baseline: {"p1_odds": int, "p2_odds": int, ...}

    Args:
        raw: Parsed JSON dict from the DataGolf API response.
        book_id: The sportsbook to extract (e.g., "draftkings", "fanduel").
                 Must be a key present in the match entries.

    Returns:
        BookSnapshot containing RawMatchupOdds for every matchup where
        the requested book has odds.

    Raises:
        KeyError: If required top-level fields are missing.
    """
    event_name = raw["event_name"]
    market_type = raw["market"]
    captured_at = _parse_last_updated(raw["last_updated"])

    matchups = []
    for entry in raw.get("match_list", []):
        book_odds = entry.get(book_id)
        if book_odds is None:
            # This book hasn't posted odds for this matchup — skip it.
            continue

        n_players = 3 if "p3_player_name" in entry else 2
        players = []
        for i in range(1, n_players + 1):
            pk = f"p{i}"
            odds_val = book_odds.get(f"{pk}_odds")
            if odds_val is None:
                continue
            players.append(RawPlayerOdds(
                name=entry[f"{pk}_player_name"],
                datagolf_id=entry.get(f"{pk}_datagolf_id", ""),
                american_odds=int(odds_val),
            ))

        if len(players) < 2:
            logger.warning("Skipping matchup entry with < 2 players: %s", entry)
            continue

        p_ids = "_vs_".join(p.datagolf_id for p in players)
        matchup_id = f"{event_name}_{p_ids}".replace(" ", "_").lower()

        matchups.append(RawMatchupOdds(
            matchup_id=matchup_id,
            players=players,
            market_type=market_type,
            book_id=book_id,
            captured_at=captured_at,
        ))

    return BookSnapshot(
        book_id=book_id,
        market_type=market_type,
        event_name=event_name,
        captured_at=captured_at,
        matchups=matchups,
        raw=raw,
    )


def parse_datagolf_outrights_response(
    raw: dict[str, Any],
    book_id: str,
) -> BookSnapshot:
    """Parse a DataGolf /betting-tools/outrights response for one book.

    Expected top-level keys: event_name, tour, market, last_updated, player_list.

    Each entry in player_list:
      player_name, datagolf_id
      "<book_id>": int | float   # American odds for this player
      datagolf_baseline_history_fit: int | float

    Args:
        raw: Parsed JSON dict from the DataGolf API response.
        book_id: The sportsbook to extract.

    Returns:
        BookSnapshot containing RawOutrightOdds for every player where
        the requested book has odds.

    Raises:
        KeyError: If required top-level fields are missing.
    """
    event_name = raw["event_name"]
    market = raw["market"]
    captured_at = _parse_last_updated(raw["last_updated"])

    outrights = []
    for entry in raw.get("player_list", []):
        odds_val = entry.get(book_id)
        if odds_val is None:
            continue
        outrights.append(RawOutrightOdds(
            player_name=entry["player_name"],
            datagolf_id=entry.get("datagolf_id", ""),
            american_odds=int(odds_val),
            market=market,
            book_id=book_id,
            captured_at=captured_at,
        ))

    return BookSnapshot(
        book_id=book_id,
        market_type=market,
        event_name=event_name,
        captured_at=captured_at,
        outrights=outrights,
        raw=raw,
    )


def available_books_in_matchups(raw: dict[str, Any]) -> list[str]:
    """Return which book IDs are present in a matchups response.

    Useful to discover which books have posted lines before parsing each.
    """
    if not raw.get("match_list"):
        return []
    first_entry = raw["match_list"][0]
    return [k for k in first_entry if k not in _MATCHUP_META_KEYS]


def available_books_in_outrights(raw: dict[str, Any]) -> list[str]:
    """Return which book IDs are present in an outrights response."""
    if not raw.get("player_list"):
        return []
    first_entry = raw["player_list"][0]
    return [k for k in first_entry if k not in _OUTRIGHT_META_KEYS]


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def persist_book_snapshot(
    snapshot: BookSnapshot,
    session: Any,  # SQLAlchemy Session
    tournament_id: int | None = None,
) -> RawSnapshot:
    """Persist the raw DataGolf payload to the RawSnapshot table.

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
        "Persisted snapshot: book=%s market=%s matchups=%d outrights=%d",
        snapshot.book_id,
        snapshot.market_type,
        len(snapshot.matchups),
        len(snapshot.outrights),
    )
    return raw_record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_last_updated(value: str) -> datetime:
    """Parse DataGolf's 'last_updated' timestamp to a UTC datetime.

    DataGolf uses "YYYY-MM-DD HH:MM:SS" (no timezone; assumed UTC).
    """
    try:
        # Try ISO format with timezone first
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    # Fall back to DataGolf's space-separated format "YYYY-MM-DD HH:MM:SS"
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)
