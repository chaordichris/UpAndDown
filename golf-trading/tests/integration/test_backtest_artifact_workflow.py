from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.artifact_bundle import (
    build_review_bundle_artifact,
    render_review_bundle_artifact_json,
)
from scripts.backtest_replay import (
    load_fixture,
    render_replay_manifest_json,
    run_fixture_replay,
)
from scripts.backtest_review import (
    build_backtest_review_artifact,
    collect_backtest_report_slices,
    render_backtest_review_artifact_json,
)
from scripts.paper_trade import render_stored_report_json
from scripts.phase_gate_check import (
    render_phase_gate_artifact_json,
    run_phase3_check_artifact,
)
from src.monitoring.reports import build_stored_paper_trade_report
from src.storage.db import get_session, init_db

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "replay"
CORE_FIXTURE_PATH = FIXTURE_DIR / "backtest_multi_market_core_replay.json"
MAKE_CUT_FIXTURE_PATH = (
    FIXTURE_DIR / "backtest_forecast_candidate_replay.json"
)
TOP5_OUTRIGHT_FIXTURE_PATH = FIXTURE_DIR / "backtest_top5_outright_replay.json"


def test_backtest_artifact_workflow_writes_review_bundle(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    replay_path = artifacts_dir / "replay.json"
    review_path = artifacts_dir / "backtest-review.json"
    paper_report_path = artifacts_dir / "paper-report.json"
    phase_gate_path = artifacts_dir / "phase-gate.json"
    bundle_path = artifacts_dir / "review-bundle.json"
    core_event_db_url = f"sqlite:///{tmp_path / 'core-event.db'}"
    make_cut_event_db_url = f"sqlite:///{tmp_path / 'make-cut-event.db'}"
    top5_outright_event_db_url = f"sqlite:///{tmp_path / 'top5-outright-event.db'}"
    paper_db_url = f"sqlite:///{tmp_path / 'paper.db'}"

    replay_manifest = run_fixture_replay(
        load_fixture(CORE_FIXTURE_PATH),
        database_url=core_event_db_url,
    )
    _write_artifact(replay_path, render_replay_manifest_json(replay_manifest))
    make_cut_manifest = run_fixture_replay(
        load_fixture(MAKE_CUT_FIXTURE_PATH),
        database_url=make_cut_event_db_url,
    )
    top5_outright_manifest = run_fixture_replay(
        load_fixture(TOP5_OUTRIGHT_FIXTURE_PATH),
        database_url=top5_outright_event_db_url,
    )

    review_artifact = build_backtest_review_artifact(
        collect_backtest_report_slices(
            [
                ("core_markets", core_event_db_url),
                ("make_cut", make_cut_event_db_url),
                ("top5_outright", top5_outright_event_db_url),
            ]
        ),
        code_version="artifact-workflow-test",
    )
    _write_artifact(review_path, render_backtest_review_artifact_json(review_artifact))

    init_db(paper_db_url)
    with get_session(paper_db_url) as session:
        paper_report = build_stored_paper_trade_report(session)
    _write_artifact(
        paper_report_path,
        render_stored_report_json(paper_report, code_version="artifact-workflow-test"),
    )

    phase_gate_artifact = run_phase3_check_artifact(
        argparse.Namespace(
            database_url=paper_db_url,
            paper_tournaments=1,
            pipeline_crashes=0,
            data_completeness=1.0,
            starting_bankroll=10_000.0,
            peak_bankroll=10_000.0,
            stake_fraction=0.01,
            expected_return=0.02,
            return_sd=1.0,
            backtest_summary_json=str(review_path),
        ),
        code_version="artifact-workflow-test",
    )
    phase_gate_artifact = {
        key: value
        for key, value in phase_gate_artifact.items()
        if key != "result_obj"
    }
    _write_artifact(phase_gate_path, render_phase_gate_artifact_json(phase_gate_artifact))

    bundle_artifact = build_review_bundle_artifact(
        replay=replay_path,
        backtest_review=review_path,
        paper_report=paper_report_path,
        phase_gate=phase_gate_path,
        code_version="artifact-workflow-test",
    )
    _write_artifact(bundle_path, render_review_bundle_artifact_json(bundle_artifact))

    bundle = json.loads(bundle_path.read_text())
    bundle_by_label = {artifact["label"]: artifact for artifact in bundle["artifacts"]}

    assert bundle["artifact_type"] == "review_bundle"
    assert bundle["shape"] == {"artifacts": 4}
    assert review_artifact["summary"]["tournament_count"] == 3
    assert review_artifact["summary"]["settled_count"] == 5
    assert bundle_by_label["replay"]["artifact_type"] == "backtest_replay_manifest"
    assert bundle_by_label["replay"]["embedded_hashes"]["manifest_hash"] == replay_manifest[
        "manifest_hash"
    ]
    assert bundle_by_label["backtest_review"]["embedded_hashes"]["manifest_hash"] == review_artifact[
        "manifest_hash"
    ]
    assert bundle_by_label["paper_report"]["embedded_hashes"]["artifact_hash"]
    assert bundle_by_label["phase_gate"]["embedded_hashes"]["artifact_hash"]
    assert phase_gate_artifact["metrics"]["backtest_summary"]["manifest_hash"] == review_artifact[
        "manifest_hash"
    ]
    assert make_cut_manifest["manifest_hash"] == (
        "8f6c3fb56dad485222429c56c4061da184e2c73b1b2b494cf3e9eb5509d4d66a"
    )
    assert top5_outright_manifest["manifest_hash"] == (
        "1ef37fac8050811557706e859055ea6655a2fca419d75268a0d79a1823b0b264"
    )


def _write_artifact(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)
