"""
Unit tests for src/ingestion/datagolf.py

httpx calls are intercepted with respx (httpx's built-in mock transport)
so no network access is required.

Covers:
  - Happy-path fetch: response parsed and snapshot persisted.
  - Retry: 429 and 5xx responses trigger backoff then succeed.
  - Non-retryable 4xx (e.g., 401) raises immediately.
  - Timeout: retried up to max attempts then raises RuntimeError.
  - API key is included in every request.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch, PropertyMock

import httpx
import pytest

from src.ingestion.datagolf import DataGolfClient, _MAX_RETRIES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(session, api_key: str = "test-key", base_url: str = "https://feeds.datagolf.com"):
    return DataGolfClient(api_key=api_key, session=session, base_url=base_url)


def _mock_response(status_code: int, body: dict) -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = body
    response.request = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=response.request,
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    return response


SAMPLE_FORECAST = {
    "event_name": "The Players Championship",
    "year": 2024,
    "players": [
        {"player_id": "scottie_scheffler", "win_probability": 0.142},
    ],
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_fetch_pretournament_stores_snapshot(db_session):
    """Successful fetch: snapshot is persisted with correct fields."""
    client = _make_client(db_session)

    with patch("httpx.get", return_value=_mock_response(200, SAMPLE_FORECAST)):
        result = client.fetch_pretournament_predictions(tour="pga")

    assert result.data == SAMPLE_FORECAST
    assert result.snapshot.source == "datagolf"
    assert result.snapshot.endpoint == "pretournament_predictions"
    assert result.snapshot.response_body == json.dumps(SAMPLE_FORECAST)


def test_fetch_player_list_stores_snapshot(db_session):
    """fetch_player_list stores the right endpoint label."""
    client = _make_client(db_session)
    player_list = {"players": [{"player_id": "rory_mcilroy", "player_name": "Rory McIlroy"}]}

    with patch("httpx.get", return_value=_mock_response(200, player_list)):
        result = client.fetch_player_list()

    assert result.snapshot.endpoint == "player_list"
    assert result.data == player_list


def test_api_key_included_in_request(db_session):
    """API key must be sent as the 'key' query parameter on every request."""
    client = _make_client(db_session, api_key="secret-abc")

    with patch("httpx.get", return_value=_mock_response(200, SAMPLE_FORECAST)) as mock_get:
        client.fetch_pretournament_predictions(tour="pga")

    called_params = mock_get.call_args.kwargs.get("params", mock_get.call_args[1].get("params", {}))
    assert called_params.get("key") == "secret-abc"


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

def test_retry_on_429_then_success(db_session):
    """A 429 response triggers a retry; subsequent 200 succeeds."""
    responses = [
        _mock_response(429, {}),
        _mock_response(200, SAMPLE_FORECAST),
    ]

    with patch("httpx.get", side_effect=responses), patch("time.sleep"):
        result = client_with_db(db_session).fetch_pretournament_predictions()

    assert result.data == SAMPLE_FORECAST


def test_retry_on_503_then_success(db_session):
    """A 503 response triggers a retry; subsequent 200 succeeds."""
    responses = [
        _mock_response(503, {}),
        _mock_response(200, SAMPLE_FORECAST),
    ]

    with patch("httpx.get", side_effect=responses), patch("time.sleep"):
        result = client_with_db(db_session).fetch_pretournament_predictions()

    assert result.data == SAMPLE_FORECAST


def test_exhausted_retries_raise_runtime_error(db_session):
    """If all retries return 503, RuntimeError is raised."""
    responses = [_mock_response(503, {})] * (_MAX_RETRIES + 1)

    with patch("httpx.get", side_effect=responses), patch("time.sleep"):
        with pytest.raises(RuntimeError, match="failed after"):
            client_with_db(db_session).fetch_pretournament_predictions()


def test_timeout_triggers_retry(db_session):
    """TimeoutException triggers a retry."""
    responses = [
        httpx.TimeoutException("timed out"),
        _mock_response(200, SAMPLE_FORECAST),
    ]

    with patch("httpx.get", side_effect=responses), patch("time.sleep"):
        result = client_with_db(db_session).fetch_pretournament_predictions()

    assert result.data == SAMPLE_FORECAST


def test_all_timeouts_raise_runtime_error(db_session):
    """All retries timing out raises RuntimeError."""
    responses = [httpx.TimeoutException("timed out")] * (_MAX_RETRIES + 1)

    with patch("httpx.get", side_effect=responses), patch("time.sleep"):
        with pytest.raises(RuntimeError, match="failed after"):
            client_with_db(db_session).fetch_pretournament_predictions()


# ---------------------------------------------------------------------------
# Non-retryable errors
# ---------------------------------------------------------------------------

def test_401_raises_immediately(db_session):
    """A 401 Unauthorized is not retried and raises HTTPStatusError."""
    with patch("httpx.get", return_value=_mock_response(401, {"error": "unauthorized"})):
        with pytest.raises(httpx.HTTPStatusError):
            client_with_db(db_session).fetch_pretournament_predictions()


def test_404_raises_immediately(db_session):
    """A 404 Not Found is not retried."""
    with patch("httpx.get", return_value=_mock_response(404, {"error": "not found"})):
        with pytest.raises(httpx.HTTPStatusError):
            client_with_db(db_session).fetch_pretournament_predictions()


# ---------------------------------------------------------------------------
# Endpoint parameters
# ---------------------------------------------------------------------------

def test_event_id_passed_when_provided(db_session):
    """event_id is forwarded to the API when specified."""
    with patch("httpx.get", return_value=_mock_response(200, SAMPLE_FORECAST)) as mock_get:
        client_with_db(db_session).fetch_pretournament_predictions(tour="pga", event_id="r2024041")

    called_params = mock_get.call_args.kwargs.get("params", {})
    assert called_params.get("event_id") == "r2024041"
    assert called_params.get("tour") == "pga"


def test_event_id_omitted_when_none(db_session):
    """event_id is not sent when not specified."""
    with patch("httpx.get", return_value=_mock_response(200, SAMPLE_FORECAST)) as mock_get:
        client_with_db(db_session).fetch_pretournament_predictions(tour="pga")

    called_params = mock_get.call_args.kwargs.get("params", {})
    assert "event_id" not in called_params


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def client_with_db(session) -> DataGolfClient:
    return _make_client(session)
