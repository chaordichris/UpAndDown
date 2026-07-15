from __future__ import annotations

from scripts import run_splash_workflow as workflow


def test_run_splash_weekly_workflow_writes_manifest_and_next_commands(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "discover_splash_contests", _fake_discover)

    manifest = workflow.run_splash_weekly_workflow(
        league_id=None,
        lobby_url="https://app.splashsports.com/contest-lobby?league=league-1",
        bankroll=1_000,
        artifact_dir=tmp_path,
        limit=50,
        offset=0,
        include_full=False,
        include_hidden=False,
        contest_type="player_tier",
        weekly_cap_fraction=0.10,
        per_contest_cap_fraction=0.10,
        max_entries_per_contest=8,
        capture_top=0,
        tiers=(1, 2, 3, 4, 5, 6),
        player_pool_limit=50,
        base_url="https://splash.test/api",
    )

    assert manifest["artifact_type"] == "splash_weekly_workflow"
    assert manifest["capital_plan"]["planned_entries"] == 3
    assert manifest["artifacts"]["discovery_json"] == str(tmp_path / "discovery.json")
    assert manifest["artifacts"]["evaluation_json"] == str(tmp_path / "lobby-evaluation.json")
    assert manifest["artifacts"]["workflow_json"] == str(tmp_path / "weekly-workflow.json")
    assert manifest["recommended_next_steps"][0]["capture_command"].startswith(
        ".venv/bin/python scripts/capture_splash_contest.py --contest-id contest-1"
    )
    assert "scripts/splash_operator_console.py" in manifest["console"]["command"]
    assert (tmp_path / "discovery.json").exists()
    assert (tmp_path / "lobby-evaluation.json").exists()
    assert (tmp_path / "weekly-workflow.json").exists()
    assert manifest["artifact_hash"]


def test_run_splash_weekly_workflow_can_capture_top_public_contests(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workflow, "discover_splash_contests", _fake_discover)
    monkeypatch.setattr(workflow, "capture_splash_contest", _fake_capture)

    manifest = workflow.run_splash_weekly_workflow(
        league_id="league-1",
        lobby_url=None,
        bankroll=1_000,
        artifact_dir=tmp_path,
        limit=50,
        offset=0,
        include_full=False,
        include_hidden=False,
        contest_type="player_tier",
        weekly_cap_fraction=0.10,
        per_contest_cap_fraction=0.10,
        max_entries_per_contest=8,
        capture_top=1,
        tiers=(1, 2),
        player_pool_limit=25,
        base_url="https://splash.test/api",
    )

    capture = manifest["artifacts"]["capture_artifacts"][0]
    assert capture["contest_id"] == "contest-1"
    assert capture["contest_detail_json"] == str(tmp_path / "contests" / "contest-1" / "contest-detail.json")
    assert capture["player_pools_json"] == str(tmp_path / "contests" / "contest-1" / "player-pools-by-tier.json")
    assert capture["capture_artifact_hash"] == "capture-hash-contest-1"


def test_render_workflow_summary_handles_no_playable_contests() -> None:
    rendered = workflow.render_workflow_summary(
        {
            "artifacts": {"artifact_dir": "artifacts/splash"},
            "console": {"command": "run console"},
            "capital_plan": {
                "planned_spend_dollars": 0.0,
                "planned_contest_count": 0,
                "planned_contests": [],
            },
        }
    )

    assert "No playable contests" in rendered


def _fake_discover(**kwargs):
    output = kwargs["output"]
    manifest = {
        "artifact_hash": "discovery-hash",
        "source": {"league_id": "league-1", "lobby_url": kwargs["lobby_url"]},
        "contests": [
            {
                "id": "contest-1",
                "name": "RunGood Total Strokes",
                "contest_type": "player_tier",
                "contest_type_alt_text": "Tiers",
                "entry_fee_cents": 2500,
                "entry_fee_dollars": 25,
                "prize_pool_cents": 2502000,
                "prize_pool_dollars": 25020,
                "start_date": "2026-07-09T12:00:00.000Z",
                "status": "SCHEDULED",
                "entries": {"filled": 22, "max": 1000, "max_per_user": 40},
                "scoring_type": "golf_score",
                "expected_picks_count": 6,
                "drop_worst_count": 1,
                "league": {"id": "league-1", "name": "PGA", "sport": "golf"},
            }
        ],
    }
    if output is not None:
        workflow._write_json(output, manifest)
    return manifest


def _fake_capture(
    *,
    contest_id,
    slate_id,
    tiers,
    limit,
    contest_output,
    player_pools_output,
    base_url,
):
    assert contest_id == "contest-1"
    assert slate_id is None
    assert tiers == (1, 2)
    assert limit == 25
    assert base_url == "https://splash.test/api"
    workflow._write_json(contest_output, {"response_body": {"id": contest_id}})
    workflow._write_json(player_pools_output, {"1": {"response_body": {"data": []}}})
    return {
        "contest": {"id": contest_id, "name": "RunGood Total Strokes"},
        "artifact_hash": f"capture-hash-{contest_id}",
    }
