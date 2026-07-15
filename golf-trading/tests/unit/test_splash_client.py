from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts import capture_splash_contest as capture_script
from scripts import discover_splash_contests as discover_script
from src.fantasy.splash.client import (
    SPLASH_LOBBY_CONTEST_MESSAGE,
    SplashReadOnlyClient,
    contest_id_from_ref,
    league_id_from_lobby_url,
    slate_id_from_contest_detail,
)

CONTEST_ID = "e5c2f351-fda7-4d42-ba7f-6ab8aee29a03"
LEAGUE_ID = "166b6639-8972-41e7-a962-b415f3e93847"


def test_fetch_contest_detail_uses_public_read_headers() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")

    with patch("httpx.get", return_value=_mock_response({"id": "contest-1", "slates": []})) as get:
        result = client.fetch_contest_detail("contest-1")

    assert result.response_body["id"] == "contest-1"
    assert get.call_args.args[0] == "https://splash.test/api/contests/contest-1"
    headers = get.call_args.kwargs["headers"]
    assert headers["X-App-Platform"] == "web"
    assert "Authorization" not in headers
    assert "location-token-v2" not in headers


def test_search_contests_uses_only_public_search_post() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")

    with patch("httpx.post", return_value=_mock_response({"data": [_contest_row()]})) as post:
        result = client.search_contests(
            league_id=LEAGUE_ID,
            contest_type="player_tier",
            limit=25,
            offset=5,
        )

    assert result.response_body["data"][0]["id"] == CONTEST_ID
    assert post.call_args.args[0] == "https://splash.test/api/contests/search"
    assert post.call_args.kwargs["json"] == {
        "filter": {"leagueId": LEAGUE_ID, "contestType": "player_tier"},
        "includeFull": False,
        "hideUnlisted": True,
        "limit": 25,
        "offset": 5,
    }
    headers = post.call_args.kwargs["headers"]
    assert "Authorization" not in headers
    assert "location-token-v2" not in headers


def test_capture_tier_player_pools_paginates_into_fixture_shape() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")
    page_one = {
        "data": [_player("one"), _player("two")],
        "total": 3,
        "limit": 2,
        "offset": 0,
        "metadata": {"canMakePicks": True},
    }
    page_two = {
        "data": [_player("three")],
        "total": 3,
        "limit": 2,
        "offset": 2,
        "metadata": {"canMakePicks": True},
    }

    with patch("httpx.get", side_effect=[_mock_response(page_one), _mock_response(page_two)]) as get:
        fixture = client.capture_tier_player_pools(
            contest_id="contest-1",
            slate_id="slate-1",
            tier_ids=(1,),
            limit=2,
        )

    body = fixture["1"]["response_body"]
    assert [row["name"] for row in body["data"]] == ["one", "two", "three"]
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["metadata"] == {"canMakePicks": True}
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["params"] == {"tierId": 1, "offset": 0, "limit": 2}
    assert get.call_args_list[1].kwargs["params"] == {"tierId": 1, "offset": 2, "limit": 2}


def test_client_rejects_protected_splash_headers() -> None:
    with pytest.raises(ValueError, match="Unsafe Splash headers"):
        SplashReadOnlyClient(headers={"Authorization": "Bearer token"})


def test_client_rejects_unsafe_paths_before_network_call() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")

    with patch("httpx.get") as get:
        with pytest.raises(ValueError, match="Unsafe Splash endpoint"):
            client._get_json("/v2/entries", params={})

    get.assert_not_called()

    with patch("httpx.post") as post:
        with pytest.raises(ValueError, match="Unsafe Splash endpoint"):
            client._post_json("/v2/entries", json_body={})

    post.assert_not_called()


def test_client_rejects_search_get_and_detail_post_before_network_call() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")

    with patch("httpx.get") as get:
        with pytest.raises(ValueError, match="not allowlisted for GET"):
            client._get_json("/contests/search", params={})

    get.assert_not_called()

    with patch("httpx.post") as post:
        with pytest.raises(ValueError, match="not allowlisted for POST"):
            client._post_json(f"/contests/{CONTEST_ID}", json_body={})

    post.assert_not_called()


def test_client_rejects_non_token_ids_before_network_call() -> None:
    client = SplashReadOnlyClient(base_url="https://splash.test/api")

    with patch("httpx.get") as get:
        with pytest.raises(ValueError, match="contest_id"):
            client.fetch_contest_detail("../contest")

    get.assert_not_called()


def test_lobby_url_extracts_league_id() -> None:
    url = f"https://app.splashsports.com/contest-lobby?league={LEAGUE_ID}"

    assert league_id_from_lobby_url(url) == LEAGUE_ID


def test_contest_ref_accepts_raw_uuid_and_contest_url() -> None:
    assert contest_id_from_ref(CONTEST_ID) == CONTEST_ID
    assert contest_id_from_ref(f"https://app.splashsports.com/contest/{CONTEST_ID}") == CONTEST_ID
    assert contest_id_from_ref(
        f"https://app.splashsports.com/contests/details?contestId={CONTEST_ID}"
    ) == CONTEST_ID


def test_lobby_url_is_rejected_as_contest_ref() -> None:
    url = f"https://app.splashsports.com/contest-lobby?league={LEAGUE_ID}"

    with pytest.raises(ValueError, match="discover_splash_contests.py"):
        contest_id_from_ref(url)


def test_slate_id_from_contest_detail_accepts_fixture_or_body() -> None:
    body = {"slates": [{"id": "slate-1"}]}

    assert slate_id_from_contest_detail(body) == "slate-1"
    assert slate_id_from_contest_detail({"response_body": body}) == "slate-1"


def test_capture_script_writes_fixture_outputs(tmp_path, monkeypatch) -> None:
    contest_output = tmp_path / "contest.json"
    pools_output = tmp_path / "pools.json"
    monkeypatch.setattr(capture_script, "SplashReadOnlyClient", _fake_capture_client)

    manifest = capture_script.capture_splash_contest(
        contest_id=CONTEST_ID,
        slate_id=None,
        tiers=(1, 2),
        limit=50,
        contest_output=contest_output,
        player_pools_output=pools_output,
        base_url="https://splash.test/api",
    )

    assert manifest["contest"]["name"] == "RunGood Test"
    assert manifest["slate_id"] == "slate-1"
    assert manifest["tiers"]["1"]["player_count"] == 1
    assert manifest["tiers"]["2"]["player_count"] == 1
    assert manifest["artifact_hash"]
    assert contest_output.exists()
    assert pools_output.exists()


def test_capture_script_rejects_lobby_url_before_fetch(monkeypatch) -> None:
    monkeypatch.setattr(capture_script, "SplashReadOnlyClient", _fake_capture_client)

    with pytest.raises(ValueError, match=SPLASH_LOBBY_CONTEST_MESSAGE):
        capture_script.capture_splash_contest(
            contest_id=f"https://app.splashsports.com/contest-lobby?league={LEAGUE_ID}",
            slate_id=None,
            tiers=(1,),
            limit=50,
            contest_output=None,
            player_pools_output=None,
            base_url="https://splash.test/api",
        )


def test_discovery_script_outputs_manifest_shape(tmp_path, monkeypatch) -> None:
    output = tmp_path / "discovery.json"
    monkeypatch.setattr(discover_script, "SplashReadOnlyClient", _fake_discovery_client)

    manifest = discover_script.discover_splash_contests(
        league_id=None,
        lobby_url=f"https://app.splashsports.com/contest-lobby?league={LEAGUE_ID}",
        limit=50,
        offset=0,
        include_full=False,
        include_hidden=False,
        contest_type="player_tier",
        output=output,
        base_url="https://splash.test/api",
    )

    assert manifest["source"]["league_id"] == LEAGUE_ID
    assert manifest["request"]["endpoint"] == "/contests/search"
    assert manifest["request"]["method"] == "POST"
    assert manifest["request"]["body"]["filter"] == {
        "leagueId": LEAGUE_ID,
        "contestType": "player_tier",
    }
    assert manifest["contest_count"] == 1
    assert manifest["contests"][0] == {
        "id": CONTEST_ID,
        "name": "RunGood $30K Genesis Scottish Open - Total Strokes",
        "contest_type": "player_tier",
        "contest_type_alt_text": "Pick 6",
        "entry_fee_cents": 2500,
        "entry_fee_dollars": 25,
        "prize_pool_cents": 3000000,
        "prize_pool_dollars": 30000,
        "start_date": "2026-07-09T12:00:00.000Z",
        "status": "SCHEDULED",
        "entries": {"filled": 22, "max": 1334, "max_per_user": 40},
        "scoring_type": "golf_score",
        "expected_picks_count": 6,
        "drop_worst_count": 1,
        "league": {"id": LEAGUE_ID, "name": "PGA", "sport": "golf"},
    }
    assert manifest["artifact_hash"]
    assert output.exists()
    assert "RunGood $30K" in discover_script.render_discovery_summary(manifest)


def _mock_response(body: dict) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def _player(name: str) -> dict:
    return {
        "id": f"row-{name}",
        "playerId": f"player-{name}",
        "slateId": "slate-1",
        "attributes": {"datagolf_rank": 1},
        "name": name,
        "isPlayerSelectable": True,
    }


def _contest_row() -> dict:
    return {
        "id": CONTEST_ID,
        "name": "RunGood $30K Genesis Scottish Open - Total Strokes",
        "contest_type": "player_tier",
        "contest_type_alt_text": "Pick 6",
        "entry_fee": 2500,
        "entry_fee_in_dollars": 25,
        "prize_pool": 3000000,
        "prize_pool_in_dollars": 30000,
        "start_date": "2026-07-09T12:00:00.000Z",
        "status": "SCHEDULED",
        "entries": {"filled": 22, "max": 1334, "max_per_user": 40},
        "settings": {
            "scoreType": "golf_score",
            "expectedPicksCount": 6,
            "dropWorstCount": 1,
        },
        "league": {"id": LEAGUE_ID, "name": "PGA", "sport": "golf"},
    }


class _fake_capture_client:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url

    def contest_detail_fixture(self, contest_id: str) -> dict:
        return {
            "response_body": {
                "id": contest_id,
                "name": "RunGood Test",
                "contest_type": "player_tier",
                "status": "SCHEDULED",
                "entry_fee": 2500,
                "entry_fee_in_dollars": 25,
                "prize_pool": 2502000,
                "prize_pool_in_dollars": 25020,
                "entries": {"filled": 1, "max": 2, "max_per_user": 1},
                "settings": {
                    "scoreType": "golf_score",
                    "dropWorstCount": 1,
                    "expectedPicksCount": 2,
                },
                "tier_rules_settings": {
                    "numberOfTiers": 2,
                    "numberPerTier": 1,
                    "metricName": "datagolf_rank",
                },
                "payout_schedule": [],
                "rules": "",
                "roster_requirements": "select 1 golfer from each tier",
                "slates": [{"id": "slate-1", "name": "Slate", "status": "SCHEDULED"}],
            }
        }

    def capture_tier_player_pools(
        self,
        *,
        contest_id: str,
        slate_id: str,
        tier_ids: tuple[int, ...],
        limit: int,
    ) -> dict:
        return {
            str(tier_id): {
                "response_body": {
                    "data": [_player(f"tier-{tier_id}")],
                    "total": 1,
                    "limit": limit,
                    "offset": 0,
                }
            }
            for tier_id in tier_ids
        }


class _fake_discovery_client:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url

    def search_contests(
        self,
        *,
        league_id: str,
        limit: int,
        offset: int,
        include_full: bool,
        hide_unlisted: bool,
        contest_type: str | None,
    ):
        return type(
            "FakeResult",
            (),
            {
                "url": f"{self.base_url}/contests/search",
                "request_body": {
                    "filter": {"leagueId": league_id, "contestType": contest_type},
                    "includeFull": include_full,
                    "hideUnlisted": hide_unlisted,
                    "limit": limit,
                    "offset": offset,
                },
                "response_status": 200,
                "response_body": {"data": [_contest_row()], "total": 1},
            },
        )()
