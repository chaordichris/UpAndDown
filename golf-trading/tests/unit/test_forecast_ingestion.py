from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.backtest.leakage_guard import (
    ModelVersionPublication,
    assert_forecasts_backtest_safe,
    forecast_record_from_orm,
)
from src.ingestion.forecasts import persist_pretournament_forecasts
from src.storage.models import Player, RawSnapshot, Tournament

CAPTURED_AT = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)


def test_persist_pretournament_forecasts_carries_model_version_and_hash(db_session) -> None:
    tournament, snapshot = _seed_forecast_inputs(db_session)

    rows = persist_pretournament_forecasts(
        db_session,
        snapshot=snapshot,
        tournament=tournament,
        code_version="forecast-ingestion-test",
    )

    assert len(rows) == 4
    assert {row.forecast_type for row in rows} == {"win", "top_5", "top_10", "make_cut"}
    assert {row.dg_model_version for row in rows} == {"dg-2026-04-01"}
    assert all(row.inputs_hash for row in rows)
    assert rows[0].captured_at == CAPTURED_AT


def test_persisted_forecasts_feed_leakage_guard(db_session) -> None:
    tournament, snapshot = _seed_forecast_inputs(db_session)
    rows = persist_pretournament_forecasts(
        db_session,
        snapshot=snapshot,
        tournament=tournament,
    )

    assert_forecasts_backtest_safe(
        [forecast_record_from_orm(row) for row in rows],
        decision_time=datetime(2026, 4, 30, 14, 0, tzinfo=UTC),
        model_versions=[
            ModelVersionPublication(
                dg_model_version="dg-2026-04-01",
                published_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            )
        ],
    )


def test_persist_pretournament_forecasts_requires_model_version(db_session) -> None:
    tournament, snapshot = _seed_forecast_inputs(db_session, dg_model_version=None)

    with pytest.raises(ValueError, match="dg_model_version"):
        persist_pretournament_forecasts(
            db_session,
            snapshot=snapshot,
            tournament=tournament,
        )


def test_persist_pretournament_forecasts_rejects_invalid_probability(db_session) -> None:
    tournament, snapshot = _seed_forecast_inputs(
        db_session,
        payload={
            "players": [
                {
                    "player_id": "dg_scottie",
                    "win_probability": 1.2,
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="Invalid DataGolf probability"):
        persist_pretournament_forecasts(
            db_session,
            snapshot=snapshot,
            tournament=tournament,
        )


def _seed_forecast_inputs(
    db_session,
    *,
    dg_model_version: str | None = "dg-2026-04-01",
    payload: dict | None = None,
) -> tuple[Tournament, RawSnapshot]:
    tournament = Tournament(name="Forecast Ingestion Open", tour="pga")
    player = Player(datagolf_player_id="dg_scottie", name_canonical="Scottie")
    ignored_player = Player(datagolf_player_id="dg_known_unused", name_canonical="Known Unused")
    payload = payload or {
        "players": [
            {
                "player_id": "dg_scottie",
                "win_probability": 0.12,
                "top_5_probability": 0.31,
                "top_10_probability": 0.49,
                "make_cut_probability": 0.88,
                "datagolf_skill_rating": 2.4,
            },
            {
                "player_id": "dg_unknown",
                "win_probability": 0.01,
            },
        ]
    }
    snapshot = RawSnapshot(
        source="datagolf",
        endpoint="pretournament_predictions",
        fetched_at=CAPTURED_AT,
        response_body=json.dumps(payload),
        dg_model_version=dg_model_version,
    )
    db_session.add_all([tournament, player, ignored_player, snapshot])
    db_session.flush()
    return tournament, snapshot
