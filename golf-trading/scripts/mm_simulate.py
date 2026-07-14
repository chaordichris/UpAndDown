"""Run the market-making simulator (MM-0) and optionally publish status.

Usage:
    python scripts/mm_simulate.py [--episodes 100] [--seed 7] [--publish-status]

Writes artifacts/mm-simulation-report.json and, with --publish-status, the
control-plane contract file for the pm-market-making pod.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.marketmaking.config import load_mm_config
from src.marketmaking.simulator import report_artifact, run_simulation


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


def build_status(artifact: dict) -> dict:
    summary = artifact["summary"]
    ratio = summary["adverse_to_spread_ratio"]
    gate_note = (
        f"MM-0→MM-1 gate: adverse/spread ratio {ratio} (needs <= 0.5 over >= 1000 episodes)"
        if ratio is not None
        else "MM-0→MM-1 gate: no spread capture recorded yet"
    )
    return {
        "contract_version": "1.0",
        "strategy_id": "pm-market-making",
        "strategy_name": "Prediction Market MM (Kalshi, simulator)",
        "sleeve": "mm",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs_hash": artifact["inputs_hash"],
        "health": {
            "status": "ok",
            "notes": [
                "SIMULATOR ONLY — no live venue, no real capital",
                f"{summary['episodes']} episodes, total P&L {summary['total_pnl']}",
                f"spread {summary['spread_capture']} / adverse {summary['adverse_selection']}"
                f" / settlement {summary['inventory_settlement']}",
                gate_note,
            ],
        },
        "opportunities": [],
        "positions": [],
        "exposures": {"total_at_risk": 0.0},
        "actions": [{"id": "mm-simulate", "label": "MM simulator (paper)"}],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--publish-status", action="store_true")
    args = parser.parse_args()

    config = load_mm_config()
    report = run_simulation(config, episodes=args.episodes, base_seed=args.seed)
    artifact = report_artifact(report, config)

    out = PROJECT_ROOT / "artifacts" / "mm-simulation-report.json"
    _atomic_write(out, artifact)
    summary = artifact["summary"]
    print(f"wrote {out.name}: {summary['episodes']} episodes, "
          f"total P&L {summary['total_pnl']} "
          f"(spread {summary['spread_capture']}, adverse {summary['adverse_selection']}, "
          f"settlement {summary['inventory_settlement']})")

    if args.publish_status:
        status_path = (
            PROJECT_ROOT / "artifacts" / "control-plane" / "pm-market-making.status.json"
        )
        _atomic_write(status_path, build_status(artifact))
        print(f"published {status_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
