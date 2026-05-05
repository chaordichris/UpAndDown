from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.artifact_bundle import (
    build_review_bundle_artifact,
    render_review_bundle_artifact_json,
    write_output,
)


def test_review_bundle_artifact_indexes_file_hashes_and_embedded_hashes(
    tmp_path: Path,
) -> None:
    replay = _write_json(
        tmp_path / "replay.json",
        {
            "manifest_hash": "replay-manifest-hash",
            "forecast_batch_hash": "forecast-hash",
        },
    )
    backtest_review = _write_json(
        tmp_path / "backtest-review.json",
        {
            "artifact_type": "backtest_review",
            "summary_hash": "summary-hash",
            "manifest_hash": "review-manifest-hash",
        },
    )
    paper_report = _write_json(
        tmp_path / "paper-report.json",
        {
            "artifact_type": "paper_trade_report",
            "artifact_hash": "paper-hash",
        },
    )
    phase_gate = _write_json(
        tmp_path / "phase-gate.json",
        {
            "artifact_type": "phase_gate_review",
            "artifact_hash": "phase-hash",
        },
    )

    first = build_review_bundle_artifact(
        replay=replay,
        backtest_review=backtest_review,
        paper_report=paper_report,
        phase_gate=phase_gate,
        code_version="artifact-bundle-test",
    )
    second = build_review_bundle_artifact(
        replay=replay,
        backtest_review=backtest_review,
        paper_report=paper_report,
        phase_gate=phase_gate,
        code_version="artifact-bundle-test",
    )
    rendered = render_review_bundle_artifact_json(first)

    assert first == second
    assert first["artifact_type"] == "review_bundle"
    assert first["shape"] == {"artifacts": 4}
    assert [artifact["label"] for artifact in first["artifacts"]] == [
        "replay",
        "backtest_review",
        "paper_report",
        "phase_gate",
    ]
    assert first["artifacts"][0]["embedded_hashes"] == {
        "manifest_hash": "replay-manifest-hash",
        "forecast_batch_hash": "forecast-hash",
    }
    assert first["artifacts"][1]["artifact_type"] == "backtest_review"
    assert first["artifacts"][2]["embedded_hashes"] == {"artifact_hash": "paper-hash"}
    assert first["bundle_hash"] == "e2c3e4cedf6f8e89674347651e29d7873e707fd91f049aa0a7404472772796af"
    assert '"bundle_hash":' in rendered


def test_review_bundle_artifact_hash_changes_when_file_content_changes(
    tmp_path: Path,
) -> None:
    replay = _write_json(tmp_path / "replay.json", {"manifest_hash": "replay-v1"})
    backtest_review = _write_json(tmp_path / "backtest-review.json", {})
    paper_report = _write_json(tmp_path / "paper-report.json", {})
    phase_gate = _write_json(tmp_path / "phase-gate.json", {})

    first = build_review_bundle_artifact(
        replay=replay,
        backtest_review=backtest_review,
        paper_report=paper_report,
        phase_gate=phase_gate,
    )
    _write_json(tmp_path / "replay.json", {"manifest_hash": "replay-v2"})
    second = build_review_bundle_artifact(
        replay=replay,
        backtest_review=backtest_review,
        paper_report=paper_report,
        phase_gate=phase_gate,
    )

    assert first["artifacts"][0]["file_sha256"] != second["artifacts"][0]["file_sha256"]
    assert first["bundle_hash"] != second["bundle_hash"]


def test_review_bundle_refuses_missing_artifact(tmp_path: Path) -> None:
    existing = _write_json(tmp_path / "existing.json", {})

    with pytest.raises(ValueError, match="artifact file does not exist"):
        build_review_bundle_artifact(
            replay=tmp_path / "missing.json",
            backtest_review=existing,
            paper_report=existing,
            phase_gate=existing,
        )


def test_review_bundle_refuses_non_object_json(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text("[]")
    existing = _write_json(tmp_path / "existing.json", {})

    with pytest.raises(ValueError, match="must contain a JSON object"):
        build_review_bundle_artifact(
            replay=replay,
            backtest_review=existing,
            paper_report=existing,
            phase_gate=existing,
        )


def test_write_output_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "review-bundle.json"

    write_output(path, '{"artifact_type": "review_bundle"}')

    assert path.read_text() == '{"artifact_type": "review_bundle"}'


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2))
    return path
