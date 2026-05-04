from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backtest.leakage_guard import (
    DataGolfLeakageError,
    ModelVersionPublication,
    VersionedForecastRecord,
    assert_forecasts_backtest_safe,
)

DECISION_TIME = datetime(2026, 4, 30, 14, 0, tzinfo=UTC)


def test_forecasts_are_safe_when_version_and_capture_precede_decision() -> None:
    assert_forecasts_backtest_safe(
        [
            VersionedForecastRecord(
                forecast_id=1,
                dg_model_version="dg-2026-04-01",
                captured_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
            )
        ],
        decision_time=DECISION_TIME,
        model_versions=[
            ModelVersionPublication(
                dg_model_version="dg-2026-04-01",
                published_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            )
        ],
    )


def test_naive_storage_datetimes_are_treated_as_utc() -> None:
    assert_forecasts_backtest_safe(
        [
            VersionedForecastRecord(
                forecast_id=10,
                dg_model_version="dg-2026-04-01",
                captured_at=datetime(2026, 4, 29, 12, 0),
            )
        ],
        decision_time=DECISION_TIME,
        model_versions=[
            ModelVersionPublication(
                dg_model_version="dg-2026-04-01",
                published_at=datetime(2026, 4, 1, 8, 0),
            )
        ],
    )


def test_future_model_version_raises_hard_error() -> None:
    with pytest.raises(DataGolfLeakageError, match="before it was published"):
        assert_forecasts_backtest_safe(
            [
                VersionedForecastRecord(
                    forecast_id=2,
                    dg_model_version="dg-2026-05-01",
                    captured_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
                )
            ],
            decision_time=DECISION_TIME,
            model_versions=[
                ModelVersionPublication(
                    dg_model_version="dg-2026-05-01",
                    published_at=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
                )
            ],
        )


def test_missing_model_version_raises_hard_error() -> None:
    with pytest.raises(DataGolfLeakageError, match="missing dg_model_version"):
        assert_forecasts_backtest_safe(
            [
                VersionedForecastRecord(
                    forecast_id=3,
                    dg_model_version=None,
                    captured_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
                )
            ],
            decision_time=DECISION_TIME,
            model_versions=[],
        )


def test_unknown_model_version_raises_hard_error() -> None:
    with pytest.raises(DataGolfLeakageError, match="unknown dg_model_version"):
        assert_forecasts_backtest_safe(
            [
                VersionedForecastRecord(
                    forecast_id=4,
                    dg_model_version="dg-unregistered",
                    captured_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
                )
            ],
            decision_time=DECISION_TIME,
            model_versions=[
                ModelVersionPublication(
                    dg_model_version="dg-2026-04-01",
                    published_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
                )
            ],
        )


def test_future_capture_time_raises_hard_error() -> None:
    with pytest.raises(DataGolfLeakageError, match="captured after"):
        assert_forecasts_backtest_safe(
            [
                VersionedForecastRecord(
                    forecast_id=5,
                    dg_model_version="dg-2026-04-01",
                    captured_at=datetime(2026, 4, 30, 15, 0, tzinfo=UTC),
                )
            ],
            decision_time=DECISION_TIME,
            model_versions=[
                ModelVersionPublication(
                    dg_model_version="dg-2026-04-01",
                    published_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
                )
            ],
        )
