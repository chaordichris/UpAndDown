"""Read-only Splash public API capture client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

SPLASH_CONTESTS_BASE_URL = "https://api.splashsports.com/contests-service/api"
DEFAULT_SPLASH_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-App-Platform": "web",
    "X-App-Version": "1.251.0",
    "User-Agent": "Mozilla/5.0",
}
FORBIDDEN_SPLASH_PATH_PARTS = (
    "/v2/entries",
    "/picks",
    "/buybacks",
    "/payments",
    "/kyc",
    "/universal-auth",
    "/oauth",
    "/wallet",
)
SPLASH_LOBBY_CONTEST_MESSAGE = (
    "This is a Splash lobby URL containing a league id. "
    "Use discover_splash_contests.py first."
)
_UUID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass(frozen=True)
class SplashPublicFetchResult:
    url: str
    params: dict[str, Any]
    response_status: int
    response_body: dict[str, Any]
    response_headers: dict[str, str]
    request_body: dict[str, Any] | None = None


class SplashReadOnlyClient:
    """HTTP client for public Splash contest and player-pool captures."""

    def __init__(
        self,
        *,
        base_url: str = SPLASH_CONTESTS_BASE_URL,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = dict(DEFAULT_SPLASH_HEADERS)
        if headers:
            unsafe_headers = {"authorization", "location-token-v2"}
            supplied_unsafe = unsafe_headers & {key.casefold() for key in headers}
            if supplied_unsafe:
                raise ValueError(f"Unsafe Splash headers are not allowed: {sorted(supplied_unsafe)}")
            self._headers.update(headers)

    def fetch_contest_detail(self, contest_id: str) -> SplashPublicFetchResult:
        """Fetch one public contest-detail payload."""
        _validate_path_token(contest_id, "contest_id")
        return self._get_json(f"/contests/{contest_id}", params={})

    def search_contests(
        self,
        *,
        league_id: str,
        limit: int = 50,
        offset: int = 0,
        include_full: bool = False,
        hide_unlisted: bool = True,
        contest_type: str | None = None,
    ) -> SplashPublicFetchResult:
        """Search public lobby contests for one league via Splash's read-only endpoint."""
        _validate_path_token(league_id, "league_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if contest_type is not None:
            _validate_path_token(contest_type, "contest_type")

        filter_payload: dict[str, Any] = {"leagueId": league_id}
        if contest_type:
            filter_payload["contestType"] = contest_type
        request_body = {
            "filter": filter_payload,
            "includeFull": include_full,
            "hideUnlisted": hide_unlisted,
            "limit": limit,
            "offset": offset,
        }
        return self._post_json("/contests/search", json_body=request_body)

    def fetch_player_pool_page(
        self,
        *,
        contest_id: str,
        slate_id: str,
        tier_id: int,
        offset: int = 0,
        limit: int = 50,
    ) -> SplashPublicFetchResult:
        """Fetch one public player-pool page for a contest tier."""
        _validate_path_token(contest_id, "contest_id")
        _validate_path_token(slate_id, "slate_id")
        _validate_tier_id(tier_id)
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit <= 0:
            raise ValueError("limit must be positive")

        return self._get_json(
            f"/contests/{contest_id}/slates/{slate_id}/player-pool",
            params={"tierId": tier_id, "offset": offset, "limit": limit},
        )

    def capture_tier_player_pools(
        self,
        *,
        contest_id: str,
        slate_id: str,
        tier_ids: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
        limit: int = 50,
    ) -> dict[str, dict[str, Any]]:
        """Fetch and merge all pages for each requested tier into fixture shape."""
        return {
            str(tier_id): {
                "response_body": self._fetch_complete_player_pool(
                    contest_id=contest_id,
                    slate_id=slate_id,
                    tier_id=tier_id,
                    limit=limit,
                )
            }
            for tier_id in tier_ids
        }

    def contest_detail_fixture(self, contest_id: str) -> dict[str, Any]:
        """Fetch one contest detail response in parser fixture shape."""
        result = self.fetch_contest_detail(contest_id)
        return {"response_body": result.response_body}

    def _fetch_complete_player_pool(
        self,
        *,
        contest_id: str,
        slate_id: str,
        tier_id: int,
        limit: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        first_body: dict[str, Any] | None = None
        offset = 0
        total: int | None = None

        while total is None or len(rows) < total:
            result = self.fetch_player_pool_page(
                contest_id=contest_id,
                slate_id=slate_id,
                tier_id=tier_id,
                offset=offset,
                limit=limit,
            )
            body = result.response_body
            if first_body is None:
                first_body = dict(body)
            page_rows = body.get("data") or []
            if not isinstance(page_rows, list):
                raise TypeError("Splash player-pool response data must be a list")
            rows.extend(page_rows)
            total = int(body.get("total") or len(rows))
            if not page_rows:
                break
            offset += limit

        merged = dict(first_body or {})
        merged["data"] = rows
        merged["total"] = total or len(rows)
        merged["limit"] = limit
        merged["offset"] = 0
        return merged

    def _get_json(self, endpoint: str, *, params: dict[str, Any]) -> SplashPublicFetchResult:
        _assert_read_only_path("GET", endpoint)
        url = f"{self._base_url}{endpoint}"
        response = httpx.get(
            url,
            params=params,
            headers=self._headers,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("Splash API response must be a JSON object")
        return SplashPublicFetchResult(
            url=url,
            params=dict(params),
            response_status=response.status_code,
            response_body=body,
            response_headers=dict(response.headers),
        )

    def _post_json(self, endpoint: str, *, json_body: dict[str, Any]) -> SplashPublicFetchResult:
        _assert_read_only_path("POST", endpoint)
        url = f"{self._base_url}{endpoint}"
        response = httpx.post(
            url,
            json=json_body,
            headers=self._headers,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("Splash API response must be a JSON object")
        return SplashPublicFetchResult(
            url=url,
            params={},
            request_body=dict(json_body),
            response_status=response.status_code,
            response_body=body,
            response_headers=dict(response.headers),
        )


def slate_id_from_contest_detail(contest_detail: dict[str, Any]) -> str:
    """Return the first slate id from a contest-detail fixture or response body."""
    body = contest_detail.get("response_body", contest_detail)
    slates = body.get("slates") or []
    if not slates:
        raise ValueError("Splash contest detail does not include a slate")
    slate_id = slates[0].get("id")
    if not slate_id:
        raise ValueError("Splash contest slate does not include an id")
    return str(slate_id)


def contest_id_from_ref(contest_ref: str) -> str:
    """Return a contest id from a raw UUID or recognized Splash contest URL."""
    value = contest_ref.strip()
    if _is_uuid(value):
        return value

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("contest ref must be a raw contest UUID or full Splash contest URL")

    query = parse_qs(parsed.query)
    if parsed.path.rstrip("/") == "/contest-lobby" and query.get("league"):
        raise ValueError(SPLASH_LOBBY_CONTEST_MESSAGE)

    contest_query_ids = query.get("contestId") or query.get("contest_id")
    if contest_query_ids:
        contest_id = contest_query_ids[0]
        if not _is_uuid(contest_id):
            raise ValueError("contest URL contest id must be a UUID")
        return contest_id

    path_parts = [part for part in parsed.path.split("/") if part]
    for marker in ("contest", "contests"):
        if marker in path_parts:
            marker_index = path_parts.index(marker)
            if marker_index + 1 < len(path_parts):
                contest_id = path_parts[marker_index + 1]
                if not _is_uuid(contest_id):
                    raise ValueError("contest URL contest id must be a UUID")
                return contest_id

    raise ValueError("Splash contest URL must include /contest/{contest_id} or contestId")


def league_id_from_lobby_url(lobby_url: str) -> str:
    """Return the league id from a Splash lobby URL."""
    parsed = urlparse(lobby_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("lobby URL must be a full Splash URL")
    if parsed.path.rstrip("/") != "/contest-lobby":
        raise ValueError("Splash lobby URL must use /contest-lobby")
    league_values = parse_qs(parsed.query).get("league") or []
    if not league_values:
        raise ValueError("Splash lobby URL must include a league query parameter")
    league_id = league_values[0]
    if not _is_uuid(league_id):
        raise ValueError("Splash lobby league id must be a UUID")
    return league_id


def _assert_read_only_path(method: str, endpoint: str) -> None:
    if method not in {"GET", "POST"}:
        raise ValueError(f"Splash HTTP method is not allowlisted: {method}")
    if not endpoint.startswith("/"):
        raise ValueError("Splash endpoint must start with /")
    if any(part in endpoint for part in FORBIDDEN_SPLASH_PATH_PARTS):
        raise ValueError(f"Unsafe Splash endpoint is not allowed: {endpoint}")
    contest_detail = endpoint.startswith("/contests/") and endpoint.count("/") == 2
    player_pool = endpoint.startswith("/contests/") and endpoint.endswith("/player-pool")
    contest_search = endpoint == "/contests/search"
    if method == "GET" and (contest_detail or player_pool) and not contest_search:
        return
    if method == "POST" and contest_search:
        return
    if method == "POST" and (contest_detail or player_pool):
        raise ValueError(f"Splash endpoint is not allowlisted for POST: {endpoint}")
    if method == "GET" and contest_search:
        raise ValueError(f"Splash endpoint is not allowlisted for GET: {endpoint}")
    if not (contest_detail or player_pool or contest_search):
        raise ValueError(f"Splash endpoint is not allowlisted: {endpoint}")


def _validate_path_token(value: str, label: str) -> None:
    if not value or "/" in value or "?" in value or "#" in value:
        raise ValueError(f"{label} must be a single path token")


def _validate_tier_id(tier_id: int) -> None:
    if tier_id < 1:
        raise ValueError("tier_id must be positive")


def _is_uuid(value: str) -> bool:
    import re

    return re.fullmatch(_UUID_PATTERN, value) is not None
