"""Splash preflight integrity gate (SP-1).

Validates the week's captured fixtures BEFORE portfolio generation and tells
you exactly what to fix when they can't support a lineup card. Exits non-zero
on any blocking failure so orchestration and the control plane fail closed.

Usage (fixture args mirror generate_rungood_splash_portfolios.py):
    python scripts/splash_preflight.py \
        --contest-fixture artifacts/splash-capture/rungood-contest-detail.json \
        --player-pools-fixture artifacts/splash-capture/rungood-player-pools-by-tier.json \
        --datagolf-ranks-fixture artifacts/splash-capture/rungood-datagolf-player-ranks.json \
        --score-anchors-fixture artifacts/splash-capture/rungood-datagolf-score-anchors-enriched.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.integrity import (  # noqa: E402
    report_to_artifact,
    run_preflight,
)
from src.fantasy.splash.parser import (  # noqa: E402
    parse_contest_detail,
    parse_contest_player_pool,
)
from src.fantasy.splash.scoring_model import (  # noqa: E402
    datagolf_score_anchor_from_row,
)


def _fixture_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_json(path: Path):
    return json.loads(path.read_text())


def _age_hours(path: Path, now: float) -> float:
    return (now - path.stat().st_mtime) / 3600.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contest-fixture", required=True)
    parser.add_argument("--player-pools-fixture", required=True)
    parser.add_argument("--datagolf-ranks-fixture", required=True)
    parser.add_argument("--score-anchors-fixture", required=True)
    parser.add_argument(
        "--output",
        default="artifacts/splash-preflight-report.json",
        help="Where to write the preflight report artifact.",
    )
    parser.add_argument(
        "--max-fixture-age-hours",
        type=float,
        default=72.0,
        help="Fixtures older than this block the run.",
    )
    parser.add_argument(
        "--min-depth-multiple",
        type=float,
        default=2.0,
        help="Warn when a tier has fewer anchored players than this multiple of its requirement.",
    )
    parser.add_argument(
        "--skip-freshness",
        action="store_true",
        help="Skip fixture mtime freshness checks (for replaying archived weeks).",
    )
    args = parser.parse_args()

    fixtures = {
        "contest": _fixture_path(args.contest_fixture),
        "player_pools": _fixture_path(args.player_pools_fixture),
        "datagolf_ranks": _fixture_path(args.datagolf_ranks_fixture),
        "score_anchors": _fixture_path(args.score_anchors_fixture),
    }
    missing = [f"{name}: {path}" for name, path in fixtures.items() if not path.exists()]
    if missing:
        print("PREFLIGHT BLOCKED — missing fixture files:", file=sys.stderr)
        for line in missing:
            print(f"  ✗ {line}", file=sys.stderr)
        return 1

    contest = parse_contest_detail(_load_json(fixtures["contest"]))
    player_pool = parse_contest_player_pool(
        contest,
        _load_json(fixtures["player_pools"]),
        _load_json(fixtures["datagolf_ranks"]),
    )
    anchors = tuple(
        datagolf_score_anchor_from_row(row)
        for row in _load_json(fixtures["score_anchors"])
    )

    ages = None
    if not args.skip_freshness:
        now = time.time()
        ages = {name: _age_hours(path, now) for name, path in fixtures.items()}

    report = run_preflight(
        player_pool,
        anchors,
        ages,
        max_fixture_age_hours=args.max_fixture_age_hours,
        min_depth_multiple=args.min_depth_multiple,
    )

    artifact = report_to_artifact(report)
    artifact["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifact["contest"] = {"id": contest.splash_id, "name": contest.name}
    artifact["fixtures"] = {name: str(path) for name, path in fixtures.items()}
    output_path = _fixture_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, output_path)

    print(f"Splash preflight — {contest.name}")
    for check in report.checks:
        mark = "✓" if check.passed else ("✗" if check.severity == "block" else "⚠")
        print(f"  {mark} {check.check_id}: {check.detail}")
        if not check.passed and check.remediation:
            print(f"      fix: {check.remediation}")
    verdict = "PASS — data can support a lineup card" if report.passed else (
        f"BLOCKED — {len(report.blocking_failures)} failure(s) must be repaired first"
    )
    print(f"\n{verdict}")
    print(f"report: {output_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
