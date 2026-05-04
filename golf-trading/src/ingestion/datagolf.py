"""
DataGolf API client.

Fetches pre-tournament forecasts, field updates, and player data from
https://feeds.datagolf.com. Every response is stored as-is in the
RawSnapshot table before any transformation.

Usage:
    from src.ingestion.datagolf import DataGolfClient
    client = DataGolfClient(api_key="your-key", session=db_session)
    snapshot = client.fetch_pretournament_predictions(tour="pga")

Rate limits: DataGolf documents limits in their API reference. The client
applies exponential backoff on 429 and 5xx responses (up to 3 retries).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from src.storage.models import RawSnapshot

logger = logging.getLogger(__name__)

_BASE_URL = "https://feeds.datagolf.com"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 3
_RETRY_INITIAL_WAIT = 1.0   # seconds; doubles on each retry
_DG_MODEL_VERSION_KEYS = (
    "dg_model_version",
    "model_version",
    "data_golf_model_version",
)


# ---------------------------------------------------------------------------
# Typed response containers
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    """Wraps a raw API response together with the DB snapshot record."""

    snapshot: RawSnapshot
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DataGolfClient:
    """HTTP client for the DataGolf REST API.

    Args:
        api_key: DataGolf API key (from config/secrets).
        session: SQLAlchemy session used to persist RawSnapshots.
                 Must be managed (commit/rollback/close) by the caller.
        base_url: Override the default base URL (useful for testing).
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        session: Any,   # SQLAlchemy Session; typed as Any to avoid circular import
        base_url: str = _BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    def fetch_pretournament_predictions(
        self,
        tour: str = "pga",
        event_id: str | None = None,
        odds_format: str = "decimal",
    ) -> FetchResult:
        """Fetch pre-tournament win/top-N/make-cut probabilities.

        Endpoint: /preds/pre-tournament

        Args:
            tour: Tour identifier (e.g., "pga", "euro", "kft").
            event_id: DataGolf event ID. If None, fetches the current or
                      next upcoming event.
            odds_format: "decimal" | "american" | "percent". Default "decimal".

        Returns:
            FetchResult with stored snapshot and parsed response dict.
        """
        params = {"tour": tour, "odds_format": odds_format}
        if event_id is not None:
            params["event_id"] = event_id
        return self._fetch_and_store(
            endpoint="/preds/pre-tournament",
            params=params,
            source="datagolf",
            endpoint_label="pretournament_predictions",
        )

    def fetch_field_updates(
        self,
        tour: str = "pga",
        event_id: str | None = None,
    ) -> FetchResult:
        """Fetch current field and withdrawal information.

        Endpoint: /field-updates
        """
        params = {"tour": tour}
        if event_id is not None:
            params["event_id"] = event_id
        return self._fetch_and_store(
            endpoint="/field-updates",
            params=params,
            source="datagolf",
            endpoint_label="field_updates",
        )

    def fetch_tournament_schedule(self, tour: str = "pga") -> FetchResult:
        """Fetch the tournament schedule for the given tour.

        Endpoint: /get-schedule
        """
        return self._fetch_and_store(
            endpoint="/get-schedule",
            params={"tour": tour},
            source="datagolf",
            endpoint_label="tournament_schedule",
        )

    def fetch_player_list(self) -> FetchResult:
        """Fetch the full DataGolf player list.

        Endpoint: /preds/player-list
        """
        return self._fetch_and_store(
            endpoint="/preds/player-list",
            params={},
            source="datagolf",
            endpoint_label="player_list",
        )

    # ------------------------------------------------------------------
    # Live betting-tools endpoints (odds from 8-12 sportsbooks + DG model)
    # ------------------------------------------------------------------

    def fetch_live_matchups(
        self,
        tour: str = "pga",
        market: str = "tournament_matchups",
        odds_format: str = "american",
    ) -> FetchResult:
        """Fetch live matchup and 3-ball odds from up to 8 sportsbooks
        alongside DataGolf's model prediction.

        Endpoint: /betting-tools/matchups

        Args:
            tour: "pga" | "euro" | "opp" | "alt"
            market: "tournament_matchups" | "round_matchups" | "3_balls"
            odds_format: "american" | "decimal" | "percent"

        Response shape (assumed from API docs — verify against live data):
            {
              "event_name": str,
              "tour": str,
              "market": str,
              "last_updated": str,   # "YYYY-MM-DD HH:MM:SS"
              "match_list": [
                {
                  "p1_player_name": str,
                  "p2_player_name": str,
                  "p1_datagolf_id": str,
                  "p2_datagolf_id": str,
                  "<book_id>": {"p1_odds": int, "p2_odds": int},
                  ...
                  "datagolf_baseline": {"p1_odds": int, "p2_odds": int}
                }
              ]
            }
        """
        return self._fetch_and_store(
            endpoint="/betting-tools/matchups",
            params={"tour": tour, "market": market, "odds_format": odds_format},
            source="datagolf",
            endpoint_label=f"live_matchups_{market}",
        )

    def fetch_live_outrights(
        self,
        tour: str = "pga",
        market: str = "win",
        odds_format: str = "american",
    ) -> FetchResult:
        """Fetch live outright odds (win, top-5, top-10, top-20, make-cut)
        from up to 11 sportsbooks alongside DataGolf's model prediction.

        Endpoint: /betting-tools/outrights

        Args:
            tour: "pga" | "euro" | "opp" | "alt"
            market: "win" | "top_5" | "top_10" | "top_20" | "make_cut" | "miss_cut"
            odds_format: "american" | "decimal" | "percent"

        Response shape (assumed from API docs — verify against live data):
            {
              "event_name": str,
              "tour": str,
              "market": str,
              "last_updated": str,
              "player_list": [
                {
                  "player_name": str,
                  "datagolf_id": str,
                  "<book_id>": int | float,   # American odds for this player
                  ...
                  "datagolf_baseline_history_fit": int | float
                }
              ]
            }
        """
        return self._fetch_and_store(
            endpoint="/betting-tools/outrights",
            params={"tour": tour, "market": market, "odds_format": odds_format},
            source="datagolf",
            endpoint_label=f"live_outrights_{market}",
        )

    # ------------------------------------------------------------------
    # Historical odds endpoints (opening + closing lines with outcomes)
    # ------------------------------------------------------------------

    def fetch_historical_event_list(self, tour: str = "pga") -> FetchResult:
        """Fetch the list of events for which historical odds are available.

        Endpoint: /historical-odds/event-list
        """
        return self._fetch_and_store(
            endpoint="/historical-odds/event-list",
            params={"tour": tour},
            source="datagolf",
            endpoint_label="historical_event_list",
        )

    def fetch_historical_outrights(
        self,
        tour: str = "pga",
        event_id: str | None = None,
        year: int | None = None,
        market: str = "win",
        book: str = "draftkings",
        odds_format: str = "american",
    ) -> FetchResult:
        """Fetch historical opening + closing lines with bet outcomes.

        Endpoint: /historical-odds/outrights

        Args:
            tour: Tour identifier.
            event_id: DataGolf event ID (use fetch_historical_event_list to find).
            year: Season year (2019–present). Defaults to current year if None.
            market: "win" | "top_5" | "top_10" | "top_20" | "make_cut"
            book: Sportsbook ID (e.g., "draftkings", "fanduel", "pinnacle").
            odds_format: "american" | "decimal" | "percent"
        """
        params: dict[str, str] = {"tour": tour, "market": market, "book": book, "odds_format": odds_format}
        if event_id is not None:
            params["event_id"] = event_id
        if year is not None:
            params["year"] = str(year)
        return self._fetch_and_store(
            endpoint="/historical-odds/outrights",
            params=params,
            source="datagolf",
            endpoint_label=f"historical_outrights_{market}_{book}",
        )

    def fetch_historical_matchups(
        self,
        tour: str = "pga",
        event_id: str | None = None,
        year: int | None = None,
        book: str = "draftkings",
        odds_format: str = "american",
    ) -> FetchResult:
        """Fetch historical matchup opening + closing lines with outcomes.

        Endpoint: /historical-odds/matchups

        Args:
            tour: Tour identifier.
            event_id: DataGolf event ID.
            year: Season year (2019–present).
            book: Sportsbook ID.
            odds_format: "american" | "decimal" | "percent"
        """
        params: dict[str, str] = {"tour": tour, "book": book, "odds_format": odds_format}
        if event_id is not None:
            params["event_id"] = event_id
        if year is not None:
            params["year"] = str(year)
        return self._fetch_and_store(
            endpoint="/historical-odds/matchups",
            params=params,
            source="datagolf",
            endpoint_label=f"historical_matchups_{book}",
        )

    # ------------------------------------------------------------------
    # Internal fetch + store
    # ------------------------------------------------------------------

    def _fetch_and_store(
        self,
        endpoint: str,
        params: dict[str, str],
        source: str,
        endpoint_label: str,
    ) -> FetchResult:
        """Make an authenticated GET request, retry on transient errors,
        persist the raw response, and return a FetchResult.

        Raises:
            httpx.HTTPStatusError: For non-retryable 4xx errors.
            RuntimeError: If all retry attempts are exhausted.
        """
        url = f"{self._base_url}{endpoint}"
        all_params = {"key": self._api_key, **params}

        data = self._get_with_retry(url, all_params)
        snapshot = self._persist_snapshot(source, endpoint_label, data)
        return FetchResult(snapshot=snapshot, data=data)

    def _get_with_retry(
        self,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """GET with exponential backoff on 429 and 5xx responses.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            httpx.HTTPStatusError: For non-retryable errors (4xx except 429).
            RuntimeError: If max retries exhausted.
        """
        wait = _RETRY_INITIAL_WAIT
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = httpx.get(url, params=params, timeout=self._timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    logger.warning(
                        "DataGolf API returned %d (attempt %d/%d). Retrying in %.1fs.",
                        response.status_code, attempt, _MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    wait *= 2.0
                    last_exc = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()  # raises for other 4xx
                return response.json()
            except httpx.TimeoutException as exc:
                logger.warning(
                    "DataGolf request timed out (attempt %d/%d). Retrying in %.1fs.",
                    attempt, _MAX_RETRIES, wait,
                )
                time.sleep(wait)
                wait *= 2.0
                last_exc = exc
                continue
            except httpx.HTTPStatusError:
                # Non-retryable client error — re-raise immediately
                raise

        raise RuntimeError(
            f"DataGolf API request to {url!r} failed after {_MAX_RETRIES} attempts."
        ) from last_exc

    def _persist_snapshot(
        self,
        source: str,
        endpoint_label: str,
        data: dict[str, Any],
    ) -> RawSnapshot:
        """Write the raw API response to the RawSnapshot table.

        Returns:
            The newly created RawSnapshot ORM object (not yet committed).
        """
        snapshot = RawSnapshot(
            source=source,
            endpoint=endpoint_label,
            fetched_at=datetime.now(UTC),
            response_body=json.dumps(data),
            dg_model_version=extract_dg_model_version(data),
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot


def extract_dg_model_version(data: Any) -> str | None:
    """Extract DataGolf model-version metadata from a raw API payload."""
    if not isinstance(data, dict):
        return None

    for key in _DG_MODEL_VERSION_KEYS:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    metadata = data.get("metadata") or data.get("meta")
    if isinstance(metadata, dict):
        for key in _DG_MODEL_VERSION_KEYS:
            value = metadata.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None
