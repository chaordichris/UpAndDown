from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from scripts.capture_datagolf_splash_enrichment import capture_datagolf_enrichment


def test_capture_datagolf_enrichment_writes_payloads_and_safe_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATAGOLF_API_KEY", "secret-key")
    responses = [
        _response({"event_name": "John Deere Classic", "field": [{"dg_id": 1}]}),
        _response({"event_name": "John Deere Classic", "baseline": [{"dg_id": 1}]}),
        _response({"event_name": "John Deere Classic", "players": [{"dg_id": 1}]}),
        _response([{"dg_id": 1, "sg_total": 1.2}]),
        _response({"projections": [{"dg_id": 1, "points": 80}]}),
    ]

    with patch("httpx.get", side_effect=responses) as get:
        manifest = capture_datagolf_enrichment(
            output_dir=tmp_path,
            tour="pga",
            sites=("draftkings",),
            add_position="2,3",
            skill_stats="sg_total",
            base_url="https://feeds.test",
        )

    assert [capture["label"] for capture in manifest["captures"]] == [
        "field_updates",
        "pre_tournament",
        "player_decompositions",
        "skill_ratings",
        "fantasy_projection_defaults_draftkings",
    ]
    assert all("key" not in capture["params"] for capture in manifest["captures"])
    assert manifest["artifact_hash"]
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "field-updates.json").exists()
    assert (tmp_path / "pre-tournament.json").exists()
    assert (tmp_path / "player-decompositions.json").exists()
    assert (tmp_path / "skill-ratings.json").exists()
    assert (tmp_path / "fantasy-projection-defaults-draftkings.json").exists()
    assert get.call_args_list[1].kwargs["params"]["add_position"] == "2,3"
    assert get.call_args_list[4].kwargs["params"]["site"] == "draftkings"
    assert get.call_args_list[4].kwargs["params"]["key"] == "secret-key"


def _response(payload):
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response
