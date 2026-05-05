"""Persist DataGolf forecast payloads with model-version provenance."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from src.storage.hashing import artifact_hash
from src.storage.models import Forecast, Player, RawSnapshot, Tournament

_FORECAST_PROBABILITY_KEYS: dict[str, str] = {
    "win": "win_probability",
    "top_5": "top_5_probability",
    "top_10": "top_10_probability",
    "top_20": "top_20_probability",
    "make_cut": "make_cut_probability",
}


def persist_pretournament_forecasts(
    session: Session,
    *,
    snapshot: RawSnapshot,
    tournament: Tournament,
    code_version: str | None = None,
) -> list[Forecast]:
    """Persist DataGolf pre-tournament player forecasts from a raw snapshot.

    The persisted rows are intentionally a direct DataGolf translation: no
    custom model overlay, no probability derivation, and no thresholding.
    """
    if snapshot.dg_model_version is None or snapshot.dg_model_version == "":
        raise ValueError("DataGolf forecast snapshot is missing dg_model_version.")

    payload = json.loads(snapshot.response_body)
    player_by_dg_id = _player_lookup(session)
    rows: list[Forecast] = []
    for player_payload in payload.get("players", []):
        player_id = player_payload.get("player_id")
        if player_id not in player_by_dg_id:
            continue
        player = player_by_dg_id[player_id]
        rows.extend(
            _forecast_rows_for_player(
                snapshot=snapshot,
                tournament=tournament,
                player=player,
                player_payload=player_payload,
                code_version=code_version,
            )
        )

    session.add_all(rows)
    session.flush()
    return rows


def _forecast_rows_for_player(
    *,
    snapshot: RawSnapshot,
    tournament: Tournament,
    player: Player,
    player_payload: dict[str, Any],
    code_version: str | None,
) -> list[Forecast]:
    rows = []
    for forecast_type, probability_key in _FORECAST_PROBABILITY_KEYS.items():
        if probability_key not in player_payload:
            continue
        probability = float(player_payload[probability_key])
        _validate_probability(probability, forecast_type, player_payload.get("player_id"))
        inputs = {
            "snapshot_id": snapshot.snapshot_id,
            "tournament_id": tournament.tournament_id,
            "player_id": player.player_id,
            "dg_model_version": snapshot.dg_model_version,
            "forecast_type": forecast_type,
            "probability_key": probability_key,
            "player_payload": player_payload,
        }
        rows.append(
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=player.player_id,
                forecast_type=forecast_type,
                probability=probability,
                datagolf_skill_rating=_optional_float(
                    player_payload.get("datagolf_skill_rating")
                ),
                dg_model_version=snapshot.dg_model_version,
                captured_at=snapshot.fetched_at,
                inputs_hash=artifact_hash(
                    artifact_type="datagolf_forecast",
                    inputs=inputs,
                    config=None,
                    code_version=code_version,
                ),
            )
        )
    return rows


def _player_lookup(session: Session) -> dict[str, Player]:
    return {
        player.datagolf_player_id: player
        for player in session.query(Player).all()
        if player.datagolf_player_id is not None
    }


def _validate_probability(probability: float, forecast_type: str, player_id: str | None) -> None:
    if not (0.0 < probability <= 1.0):
        raise ValueError(
            f"Invalid DataGolf probability {probability} for player={player_id!r} "
            f"forecast_type={forecast_type!r}."
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
