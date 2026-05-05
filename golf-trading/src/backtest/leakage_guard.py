"""Backtest leakage checks for DataGolf model-version usage."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime


class DataGolfLeakageError(ValueError):
    """Raised when a backtest attempts to use unavailable DataGolf data."""


@dataclass(frozen=True)
class VersionedForecastRecord:
    """Minimal forecast metadata needed for leakage checks."""

    forecast_id: int | str
    dg_model_version: str | None
    captured_at: datetime


@dataclass(frozen=True)
class ModelVersionPublication:
    """When a DataGolf model version first became available."""

    dg_model_version: str
    published_at: datetime


def assert_forecasts_backtest_safe(
    forecasts: Iterable[VersionedForecastRecord],
    *,
    decision_time: datetime,
    model_versions: Iterable[ModelVersionPublication],
) -> None:
    """Raise if any forecast was unavailable at the simulated decision time."""
    normalized_decision_time = _as_utc(decision_time)
    version_publication_times = {
        version.dg_model_version: _as_utc(version.published_at) for version in model_versions
    }
    for forecast in forecasts:
        if forecast.dg_model_version is None or forecast.dg_model_version == "":
            raise DataGolfLeakageError(
                f"Forecast {forecast.forecast_id} is missing dg_model_version."
            )
        captured_at = _as_utc(forecast.captured_at)
        if captured_at > normalized_decision_time:
            raise DataGolfLeakageError(
                f"Forecast {forecast.forecast_id} was captured after the decision time."
            )

        published_at = version_publication_times.get(forecast.dg_model_version)
        if published_at is None:
            raise DataGolfLeakageError(
                f"Forecast {forecast.forecast_id} uses unknown dg_model_version "
                f"{forecast.dg_model_version!r}."
            )
        if published_at > normalized_decision_time:
            raise DataGolfLeakageError(
                f"Forecast {forecast.forecast_id} uses dg_model_version "
                f"{forecast.dg_model_version!r} before it was published."
            )


def forecast_record_from_orm(forecast) -> VersionedForecastRecord:
    """Build leakage-check metadata from a storage Forecast ORM row."""
    return VersionedForecastRecord(
        forecast_id=forecast.forecast_id,
        dg_model_version=forecast.dg_model_version,
        captured_at=forecast.captured_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
