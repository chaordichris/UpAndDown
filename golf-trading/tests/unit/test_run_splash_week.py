"""SP-2 weekly-runner tests.

Two layers:
  * Engine tests drive the orchestrator with fake stage handlers (same stage
    names/outputs as production) so the resume / force / gate / seed machinery
    is verified without the heavier transform dependencies.
  * One integration test runs the REAL preflight stage against the checked-in
    rungood fixtures to prove the gate fails closed end to end. It skips when
    the transform modules can't import (they require Python 3.11+).
"""

from __future__ import annotations

import pytest

from scripts import run_splash_week as rw

CONFIG = rw.SplashRunConfig(simulations=10, sensitivity_simulations=5)


# ---------------------------------------------------------------------------
# Fake stage handlers
# ---------------------------------------------------------------------------

def _writer(name: str):
    def handler(ctx: rw.StageContext) -> rw.StageResult:
        for label, path in ctx.output_paths.items():
            rw._write_json(path, {"stage": name, "label": label})
        return rw.StageResult()

    return handler


def _fake_preflight(block: bool):
    def handler(ctx: rw.StageContext) -> rw.StageResult:
        rw._write_json(ctx.output_paths["preflight_report"], {"passed": not block})
        return rw.StageResult(blocked=block, detail="preflight blocked: test" if block else "")

    return handler


def _fake_stages(*, block_preflight: bool = False) -> tuple[rw.Stage, ...]:
    stages = []
    for stage in rw.STAGES:
        if stage.name == "preflight":
            handler = _fake_preflight(block_preflight)
        else:
            handler = _writer(stage.name)
        stages.append(rw.Stage(stage.name, stage.outputs, handler))
    return tuple(stages)


def _run(tmp_path, **kwargs):
    params = dict(contest_ref="contest-1", week_dir=tmp_path, config=CONFIG, stages=_fake_stages())
    params.update(kwargs)
    return rw.run_splash_week(**params)


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------

def test_full_run_completes_and_writes_terminal_artifacts(tmp_path) -> None:
    manifest = _run(tmp_path)

    assert manifest["status"] == "completed"
    assert manifest["blocked_stage"] is None
    assert [s["name"] for s in manifest["stages"]] == list(rw.STAGE_NAMES)
    assert all(s["status"] == "completed" for s in manifest["stages"])
    # Terminal artifacts land at the production filenames.
    assert (tmp_path / "lineup-card.json").exists()
    assert (tmp_path / "splash-dfs.status.json").exists()
    assert (tmp_path / rw.MANIFEST_FILENAME).exists()


def test_rerun_replays_deterministically(tmp_path) -> None:
    first = _run(tmp_path)
    second = _run(tmp_path)

    assert all(s["status"] == "skipped" for s in second["stages"])
    # Same inputs_hash and output hashes stage-for-stage.
    assert [s["inputs_hash"] for s in first["stages"]] == [
        s["inputs_hash"] for s in second["stages"]
    ]
    assert [s["outputs"] for s in first["stages"]] == [s["outputs"] for s in second["stages"]]


def test_config_change_invalidates_cache(tmp_path) -> None:
    _run(tmp_path)
    changed = rw.run_splash_week(
        contest_ref="contest-1",
        week_dir=tmp_path,
        config=rw.replace(CONFIG, simulations=999),
        stages=_fake_stages(),
    )
    # Config feeds every inputs_hash, so nothing may skip on a config change.
    assert all(s["status"] == "completed" for s in changed["stages"])


def test_force_from_reruns_from_stage_onward(tmp_path) -> None:
    _run(tmp_path)
    forced = _run(tmp_path, force_from="portfolios")

    by_name = {s["name"]: s for s in forced["stages"]}
    assert by_name["capture"]["status"] == "skipped"
    assert by_name["anchors"]["status"] == "skipped"
    assert by_name["preflight"]["status"] == "skipped"
    assert by_name["portfolios"]["status"] == "completed"
    assert by_name["sensitivity"]["status"] == "completed"
    assert by_name["status"]["status"] == "completed"


def test_preflight_block_halts_pipeline(tmp_path) -> None:
    manifest = rw.run_splash_week(
        contest_ref="contest-1",
        week_dir=tmp_path,
        config=CONFIG,
        stages=_fake_stages(block_preflight=True),
    )

    assert manifest["status"] == "blocked"
    assert manifest["blocked_stage"] == "preflight"
    ran = [s["name"] for s in manifest["stages"]]
    assert ran[-1] == "preflight"
    assert "portfolios" not in ran
    # The pipeline never pushed through the gate.
    assert not (tmp_path / "rungood-splash-portfolios.json").exists()
    assert not (tmp_path / "lineup-card.json").exists()


def _seed_prep_outputs(week_dir) -> None:
    prep = ("capture", "enrich", "anchors")
    for stage in rw.STAGES:
        if stage.name not in prep:
            continue
        for filename in stage.outputs.values():
            rw._write_json(week_dir / filename, {"seeded": filename})


def test_start_stage_seeds_earlier_stages_from_disk(tmp_path) -> None:
    _seed_prep_outputs(tmp_path)
    manifest = _run(tmp_path, start_stage="preflight")

    by_name = {s["name"]: s for s in manifest["stages"]}
    assert {n: by_name[n]["status"] for n in ("capture", "enrich", "anchors")} == {
        "capture": "seeded",
        "enrich": "seeded",
        "anchors": "seeded",
    }
    assert by_name["preflight"]["status"] == "completed"
    assert manifest["status"] == "completed"


def test_start_stage_missing_seed_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="seeded outputs"):
        _run(tmp_path, start_stage="preflight")


def test_unknown_stage_arg_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="force_from"):
        _run(tmp_path, force_from="nope")


# ---------------------------------------------------------------------------
# Real preflight against checked-in fixtures (fail-closed contract)
# ---------------------------------------------------------------------------

def _transform_importable() -> bool:
    try:
        import src.fantasy.splash.parser  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _transform_importable(),
    reason="transform chain modules require Python 3.11+",
)
def test_real_preflight_blocks_on_checked_in_fixtures(tmp_path) -> None:
    root = rw.PROJECT_ROOT
    seeds = {
        "contest-detail.json": root / "docs/fixtures/splash/contest-detail.redacted.json",
        "player-pools-by-tier.json": root / "tests/fixtures/splash/rungood-player-pools-by-tier.json",
        "datagolf-player-ranks.json": root / "tests/fixtures/splash/rungood-datagolf-player-ranks.json",
        "score-anchors-enriched.json": root / "tests/fixtures/splash/rungood-datagolf-score-anchors.json",
    }
    for filename, source in seeds.items():
        (tmp_path / filename).write_bytes(source.read_bytes())
    # Enrich outputs aren't read by preflight but must exist to seed the stage.
    rw._write_json(tmp_path / "pre-tournament.json", {})
    rw._write_json(tmp_path / "player-decompositions.json", {})
    rw._write_json(tmp_path / "score-anchors-review.json", {})

    manifest = rw.run_splash_week(
        contest_ref=None,
        week_dir=tmp_path,
        config=CONFIG,
        start_stage="preflight",
        stages=rw.STAGES,  # real handlers
    )

    # The minimal fixture set (2 anchors across 6 tiers) must fail closed.
    assert manifest["status"] == "blocked"
    assert manifest["blocked_stage"] == "preflight"
    assert (tmp_path / "preflight-report.json").exists()
    assert not (tmp_path / "rungood-splash-portfolios.json").exists()
