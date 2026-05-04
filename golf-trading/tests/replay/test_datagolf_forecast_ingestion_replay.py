from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backtest.leakage_guard import (
    ModelVersionPublication,
    assert_forecasts_backtest_safe,
    forecast_record_from_orm,
)
from src.ingestion.forecasts import persist_pretournament_forecasts
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Base, Player, RawSnapshot, Tournament

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "datagolf_forecast_ingestion.json"
)


def test_datagolf_forecast_ingestion_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "raw_snapshots": 1,
        "players": 2,
        "forecasts": fixture["expected"]["forecast_count"],
    }
    assert first["summary"]["players_persisted"] == fixture["expected"]["players_persisted"]
    assert first["summary"]["model_versions"] == [fixture["expected"]["model_version"]]
    assert first["summary"]["forecast_types"] == fixture["expected"]["forecast_types"]
    assert first["summary"]["leakage_guard_passed"] is fixture["expected"][
        "leakage_guard_passed"
    ]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "snapshot_inputs_hash": manifest["snapshot"]["inputs_hash"],
        "forecast_batch_hash": manifest["forecast_batch_hash"],
        "leakage_guard_hash": manifest["leakage_guard_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        tournament = Tournament(**fixture["tournament"])
        players = [Player(**player) for player in fixture["players"]]
        snapshot = _snapshot_from_fixture(fixture)
        session.add_all([tournament, *players, snapshot])
        session.flush()

        forecast_rows = persist_pretournament_forecasts(
            session,
            snapshot=snapshot,
            tournament=tournament,
            code_version=fixture["code_version"],
        )
        model_versions = [
            ModelVersionPublication(
                dg_model_version=version["dg_model_version"],
                published_at=_dt(version["published_at"]),
            )
            for version in fixture["model_versions"]
        ]
        assert_forecasts_backtest_safe(
            [forecast_record_from_orm(row) for row in forecast_rows],
            decision_time=_dt(fixture["decision_time"]),
            model_versions=model_versions,
        )

        forecast_payloads = [
            {
                "forecast_id": row.forecast_id,
                "player_id": row.player_id,
                "forecast_type": row.forecast_type,
                "probability": row.probability,
                "datagolf_skill_rating": row.datagolf_skill_rating,
                "dg_model_version": row.dg_model_version,
                "captured_at": row.captured_at.isoformat(),
                "inputs_hash": row.inputs_hash,
            }
            for row in forecast_rows
        ]
        leakage_payload = {
            "decision_time": fixture["decision_time"],
            "forecast_count": len(forecast_rows),
            "model_versions": fixture["model_versions"],
            "passed": True,
        }
        manifest = {
            "scenario": fixture["scenario"],
            "shape": {
                "raw_snapshots": 1,
                "players": len(players),
                "forecasts": len(forecast_rows),
            },
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "source": snapshot.source,
                "endpoint": snapshot.endpoint,
                "dg_model_version": snapshot.dg_model_version,
                "inputs_hash": snapshot.inputs_hash,
            },
            "forecasts": forecast_payloads,
            "summary": {
                "players_persisted": len({row.player_id for row in forecast_rows}),
                "forecast_types": sorted({row.forecast_type for row in forecast_rows}),
                "model_versions": sorted({row.dg_model_version for row in forecast_rows}),
                "leakage_guard_passed": True,
            },
            "forecast_batch_hash": stable_hash(forecast_payloads),
            "leakage_guard_hash": artifact_hash(
                artifact_type="datagolf_leakage_guard",
                inputs=leakage_payload,
                config=None,
                code_version=fixture["code_version"],
            ),
        }
        return {**manifest, "manifest_hash": stable_hash(manifest)}
    finally:
        session.close()
        engine.dispose()


def _snapshot_from_fixture(fixture: dict[str, Any]) -> RawSnapshot:
    payload = fixture["raw_snapshot"]
    response_body = json.dumps(payload["response_body"])
    inputs_hash = artifact_hash(
        artifact_type="raw_snapshot",
        inputs={
            "source": payload["source"],
            "endpoint": payload["endpoint"],
            "fetched_at": fixture["captured_at"],
            "response_body": payload["response_body"],
            "dg_model_version": payload["dg_model_version"],
        },
        config=None,
        code_version=fixture["code_version"],
    )
    return RawSnapshot(
        source=payload["source"],
        endpoint=payload["endpoint"],
        fetched_at=_dt(fixture["captured_at"]),
        response_body=response_body,
        dg_model_version=payload["dg_model_version"],
        inputs_hash=inputs_hash,
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
