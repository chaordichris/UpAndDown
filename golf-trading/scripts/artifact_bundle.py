"""Build a file-hash index for manual review artifact bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.storage.hashing import artifact_hash

ARTIFACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("replay", "replay"),
    ("backtest_review", "backtest-review"),
    ("paper_report", "paper-report"),
    ("phase_gate", "phase-gate"),
)

EMBEDDED_HASH_KEYS = (
    "artifact_hash",
    "manifest_hash",
    "summary_hash",
    "forecast_batch_hash",
    "candidate_batch_hash",
    "ticket_batch_hash",
    "settlement_batch_hash",
    "report_hash",
)


def build_review_bundle_artifact(
    *,
    replay: Path,
    backtest_review: Path,
    paper_report: Path,
    phase_gate: Path,
    code_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic file-level index for one review bundle."""
    path_by_label = {
        "replay": replay,
        "backtest_review": backtest_review,
        "paper_report": paper_report,
        "phase_gate": phase_gate,
    }
    artifacts = [
        _artifact_file_entry(label, path_by_label[label])
        for label, _argument_name in ARTIFACT_FIELDS
    ]
    payload = {
        "artifact_type": "review_bundle",
        "shape": {"artifacts": len(artifacts)},
        "artifacts": artifacts,
    }
    return {
        **payload,
        "bundle_hash": artifact_hash(
            artifact_type="review_bundle",
            inputs={"artifacts": artifacts},
            config=None,
            code_version=code_version,
        ),
    }


def render_review_bundle_artifact_json(artifact: dict[str, Any]) -> str:
    """Render a review bundle artifact as stable JSON."""
    return json.dumps(artifact, sort_keys=True, indent=2)


def write_output(path: Path | None, content: str) -> None:
    """Write rendered output when an operator requests an artifact file."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _artifact_file_entry(label: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} artifact file does not exist: {path}")

    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact file must be valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{label} artifact file must contain a JSON object: {path}")

    return {
        "label": label,
        "artifact_file": path.name,
        "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
        "artifact_type": payload.get("artifact_type"),
        "embedded_hashes": {
            key: payload[key]
            for key in EMBEDDED_HASH_KEYS
            if isinstance(payload.get(key), str)
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic file-hash index for review artifacts."
    )
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--backtest-review", type=Path, required=True)
    parser.add_argument("--paper-report", type=Path, required=True)
    parser.add_argument("--phase-gate", type=Path, required=True)
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument("--output", type=Path, help="Optional path to write the bundle artifact.")
    parser.add_argument("--code-version", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    artifact = build_review_bundle_artifact(
        replay=args.replay,
        backtest_review=args.backtest_review,
        paper_report=args.paper_report,
        phase_gate=args.phase_gate,
        code_version=args.code_version,
    )
    rendered = render_review_bundle_artifact_json(artifact)
    write_output(args.output, rendered)
    print(rendered)


if __name__ == "__main__":
    main()
