"""Build auditable WS-7 backtest review artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.backtest.summary import (
    BacktestReportSlice,
    aggregate_backtest_reports,
    render_backtest_summary,
)
from src.monitoring.reports import build_stored_paper_trade_report
from src.storage.db import get_session, init_db
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Forecast, Tournament


def parse_event_arg(value: str) -> tuple[str, str]:
    """Parse one LABEL=DATABASE_URL event reference."""
    label, separator, database_url = value.partition("=")
    if not separator or not label or not database_url:
        raise argparse.ArgumentTypeError("events must use LABEL=DATABASE_URL.")
    return label, database_url


def collect_backtest_report_slices(
    events: list[tuple[str, str]],
) -> list[BacktestReportSlice]:
    """Load one stored report per event database."""
    if not events:
        raise ValueError("At least one --event LABEL=DATABASE_URL is required.")

    slices: list[BacktestReportSlice] = []
    for label, database_url in events:
        init_db(database_url)
        with get_session(database_url) as session:
            _assert_event_db_has_replay_rows(session, label)
            slices.append(
                BacktestReportSlice(
                    label=label,
                    report=build_stored_paper_trade_report(session),
                )
            )
    return slices


def build_backtest_review_artifact(
    report_slices: list[BacktestReportSlice],
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic multi-tournament backtest review artifact."""
    reports_payload = [
        {"label": item.label, "report": asdict(item.report)}
        for item in report_slices
    ]
    summary = aggregate_backtest_reports(report_slices)
    summary_payload = _rounded(asdict(summary))
    manifest = {
        "artifact_type": "backtest_review",
        "shape": {"reports": len(report_slices)},
        "reports": reports_payload,
        "summary": summary_payload,
        "summary_hash": artifact_hash(
            artifact_type="backtest_multi_tournament_summary",
            inputs={
                "reports": reports_payload,
                "summary": summary_payload,
            },
            config=None,
            code_version=code_version,
        ),
    }
    return {**manifest, "manifest_hash": stable_hash(manifest)}


def render_backtest_review_artifact_json(artifact: dict[str, Any]) -> str:
    """Render a backtest review artifact as stable JSON."""
    return json.dumps(artifact, sort_keys=True, indent=2)


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded


def _assert_event_db_has_replay_rows(session: Any, label: str) -> None:
    has_tournament = session.query(Tournament).first() is not None
    has_forecast = session.query(Forecast).first() is not None
    if not has_tournament or not has_forecast:
        raise ValueError(
            f"Backtest event {label!r} has no replay rows. "
            "Check the --event database URL."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a multi-tournament WS-7 backtest review artifact."
    )
    parser.add_argument(
        "--event",
        action="append",
        default=[],
        type=parse_event_arg,
        metavar="LABEL=DATABASE_URL",
        help="Event database to include. Repeat once per tournament.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", type=Path, help="Optional path to write the rendered artifact.")
    parser.add_argument("--code-version", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report_slices = collect_backtest_report_slices(args.event)
    artifact = build_backtest_review_artifact(
        report_slices,
        code_version=args.code_version,
    )
    if args.format == "json":
        rendered = render_backtest_review_artifact_json(artifact)
        _write_output(args.output, rendered)
        print(rendered)
        return

    summary = aggregate_backtest_reports(report_slices)
    rendered = "\n".join(
        [
            render_backtest_summary(summary),
            f"Summary hash: {artifact['summary_hash']}",
            f"Manifest hash: {artifact['manifest_hash']}",
        ]
    )
    _write_output(args.output, rendered)
    print(rendered)


def _write_output(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


if __name__ == "__main__":
    main()
