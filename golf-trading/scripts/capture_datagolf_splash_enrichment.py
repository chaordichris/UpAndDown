"""Capture DataGolf enrichment payloads for Splash fantasy analysis."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.hashing import stable_hash  # noqa: E402

BASE_URL = "https://feeds.datagolf.com"
DEFAULT_ADD_POSITIONS = ",".join(str(position) for position in range(2, 51))
DEFAULT_SKILL_STATS = "sg_ott,sg_app,sg_arg,sg_putt,sg_t2g,sg_total"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture richer DataGolf payloads used to improve Splash fantasy inputs."
    )
    parser.add_argument("--output-dir", default="artifacts/splash-capture/datagolf-enrichment")
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--sites", nargs="+", default=["draftkings", "fanduel", "yahoo"])
    parser.add_argument("--add-position", default=DEFAULT_ADD_POSITIONS)
    parser.add_argument("--skill-stats", default=DEFAULT_SKILL_STATS)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    manifest = capture_datagolf_enrichment(
        output_dir=Path(args.output_dir),
        tour=args.tour,
        sites=tuple(args.sites),
        add_position=args.add_position,
        skill_stats=args.skill_stats,
        base_url=args.base_url,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def capture_datagolf_enrichment(
    *,
    output_dir: Path,
    tour: str,
    sites: tuple[str, ...],
    add_position: str,
    skill_stats: str,
    base_url: str = BASE_URL,
) -> dict[str, Any]:
    """Fetch DataGolf enrichment payloads and write an audit manifest."""
    api_key = _api_key()
    output_dir.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(UTC).isoformat()
    captures: list[dict[str, Any]] = []

    captures.append(
        _capture_endpoint(
            base_url=base_url,
            endpoint="/field-updates",
            label="field_updates",
            params={"tour": tour, "file_format": "json"},
            api_key=api_key,
            output_path=output_dir / "field-updates.json",
        )
    )
    captures.append(
        _capture_endpoint(
            base_url=base_url,
            endpoint="/preds/pre-tournament",
            label="pre_tournament",
            params={
                "tour": tour,
                "add_position": add_position,
                "dead_heat": "yes",
                "odds_format": "percent",
                "file_format": "json",
            },
            api_key=api_key,
            output_path=output_dir / "pre-tournament.json",
        )
    )
    captures.append(
        _capture_endpoint(
            base_url=base_url,
            endpoint="/preds/player-decompositions",
            label="player_decompositions",
            params={"tour": tour, "file_format": "json"},
            api_key=api_key,
            output_path=output_dir / "player-decompositions.json",
        )
    )
    captures.append(
        _capture_endpoint(
            base_url=base_url,
            endpoint="/preds/skill-ratings",
            label="skill_ratings",
            params={"display": "value", "stats": skill_stats, "file_format": "json"},
            api_key=api_key,
            output_path=output_dir / "skill-ratings.json",
        )
    )

    for site in sites:
        captures.append(
            _capture_endpoint(
                base_url=base_url,
                endpoint="/preds/fantasy-projection-defaults",
                label=f"fantasy_projection_defaults_{site}",
                params={
                    "tour": tour,
                    "site": site,
                    "slate": "main",
                    "file_format": "json",
                },
                api_key=api_key,
                output_path=output_dir / f"fantasy-projection-defaults-{site}.json",
            )
        )

    manifest = {
        "captured_at": captured_at,
        "tour": tour,
        "sites": sites,
        "captures": captures,
        "output_dir": str(output_dir),
    }
    manifest["artifact_hash"] = stable_hash(manifest)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _capture_endpoint(
    *,
    base_url: str,
    endpoint: str,
    label: str,
    params: dict[str, Any],
    api_key: str,
    output_path: Path,
) -> dict[str, Any]:
    safe_params = dict(params)
    request_params = {**safe_params, "key": api_key}
    response = httpx.get(
        f"{base_url.rstrip('/')}{endpoint}",
        params=request_params,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    _write_json(output_path, payload)
    return {
        "label": label,
        "endpoint": endpoint,
        "params": safe_params,
        "output_path": str(output_path),
        "response_status": response.status_code,
        "summary": _payload_summary(payload),
        "inputs_hash": stable_hash(
            {
                "label": label,
                "endpoint": endpoint,
                "params": safe_params,
                "payload_summary": _payload_summary(payload),
            }
        ),
    }


def _payload_summary(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"type": "list", "row_count": len(payload)}
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    list_counts = {
        key: len(value)
        for key, value in payload.items()
        if isinstance(value, list)
    }
    scalar_values = {
        key: value
        for key, value in payload.items()
        if key in {"event_name", "event_id", "last_updated", "tour", "course_name"}
        and not isinstance(value, (dict, list))
    }
    return {
        "type": "dict",
        "keys": sorted(payload.keys()),
        "list_counts": list_counts,
        "scalars": scalar_values,
    }


def _api_key() -> str:
    load_dotenv(".env")
    api_key = os.getenv("DATAGOLF_API_KEY")
    if not api_key:
        raise RuntimeError("DATAGOLF_API_KEY is not set")
    return api_key


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
