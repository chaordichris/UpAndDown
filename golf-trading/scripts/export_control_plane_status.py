"""Export strategy status files for the control plane (contract v1.0).

Reads existing pipeline artifacts and the paper DB, and publishes one
``<strategy_id>.status.json`` per strategy to ``artifacts/control-plane/``.
Stdlib-only on purpose so it runs anywhere the repo is checked out.

See ``control-plane/CONTRACT.md`` for the schema.

Usage:
    python scripts/export_control_plane_status.py [--artifact-dir artifacts]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "1.0"
PAPER_DB = PROJECT_ROOT / "data" / "db" / "phase3-paper.db"
NEAR_MISS_DISPLAY_LIMIT = 5

DAILY_ANALYSIS_RE = re.compile(r"daily-analysis-(?P<market>[a-z0-9-]+)-\d{4}-\d{2}-\d{2}\.json$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inputs_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


def _player_names_by_datagolf_id() -> dict[str, str]:
    if not PAPER_DB.exists():
        return {}
    con = sqlite3.connect(f"file:{PAPER_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT datagolf_player_id, name_canonical FROM players"
        ).fetchall()
    finally:
        con.close()
    return {str(dg_id): name for dg_id, name in rows if dg_id is not None}


# ---------------------------------------------------------------------------
# sportsbook-edges
# ---------------------------------------------------------------------------

def _latest_daily_analysis_per_market(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(artifact_dir.glob("daily-analysis-*.json")):
        match = DAILY_ANALYSIS_RE.search(path.name)
        if not match:
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        payload["_source_file"] = path.name
        market = match.group("market")
        current = latest.get(market)
        if current is None or payload.get("generated_at", "") >= current.get("generated_at", ""):
            latest[market] = payload
    return latest


def _edge_opportunity(
    edge: dict[str, Any],
    source_file: str,
    names: dict[str, str],
    action: str,
) -> dict[str, Any]:
    player = names.get(str(edge.get("datagolf_id")), f"dg:{edge.get('datagolf_id')}")
    odds = edge.get("book_american_odds")
    odds_str = f"{'+' if isinstance(odds, int) and odds > 0 else ''}{odds}"
    return {
        "id": f"{edge.get('market_type')}-{edge.get('book_id')}-{edge.get('datagolf_id')}",
        "market": edge.get("market_type"),
        "description": f"{player} {edge.get('market_type')} @ {edge.get('book_id')} {odds_str}",
        "fair_prob": edge.get("fair_prob"),
        "book_prob": edge.get("book_prob"),
        "edge": edge.get("edge"),
        "recommended_action": action,
        "stake_suggestion": None,
        "expires_at": None,
        "provenance": {"artifact": source_file, "passes_fdr": edge.get("passes_fdr")},
    }


def _open_paper_positions() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Open paper bets (placed, unsettled) and exposure aggregates from the paper DB."""
    if not PAPER_DB.exists():
        return [], {"total_at_risk": 0.0}
    con = sqlite3.connect(f"file:{PAPER_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT pb.bet_id, pb.book, pb.actual_stake, pb.actual_american_odds,
                   pb.placed_at, bc.market_type, bc.side,
                   p1.name_canonical AS player_name, t.name AS tournament_name
            FROM placed_bets pb
            JOIN bet_tickets bt ON bt.ticket_id = pb.ticket_id
            JOIN bet_candidates bc ON bc.candidate_id = bt.candidate_id
            LEFT JOIN players p1 ON p1.player_id = bc.player_id_1
            LEFT JOIN tournaments t ON t.tournament_id = bc.tournament_id
            LEFT JOIN bet_outcomes bo ON bo.bet_id = pb.bet_id
            WHERE bo.outcome_id IS NULL
            """
        ).fetchall()
    finally:
        con.close()

    positions: list[dict[str, Any]] = []
    by_golfer: dict[str, float] = {}
    by_tournament: dict[str, float] = {}
    total = 0.0
    for row in rows:
        stake = float(row["actual_stake"] or 0.0)
        player = row["player_name"] or "unknown"
        tournament = row["tournament_name"] or "unknown"
        odds = row["actual_american_odds"]
        positions.append(
            {
                "id": f"bet-{row['bet_id']}",
                "description": (
                    f"{player} {row['market_type']} ({row['side']}) @ {row['book']} {odds}"
                ),
                "stake": stake,
                "placed_at": row["placed_at"],
                "status": "open",
                "detail": {"market": row["market_type"], "book": row["book"]},
            }
        )
        by_golfer[player] = by_golfer.get(player, 0.0) + stake
        by_tournament[tournament] = by_tournament.get(tournament, 0.0) + stake
        total += stake

    exposures = {
        "total_at_risk": round(total, 2),
        "by_golfer": {k: round(v, 2) for k, v in by_golfer.items()},
        "by_tournament": {k: round(v, 2) for k, v in by_tournament.items()},
    }
    return positions, exposures


def build_sportsbook_status(artifact_dir: Path) -> dict[str, Any]:
    latest = _latest_daily_analysis_per_market(artifact_dir)
    names = _player_names_by_datagolf_id()

    opportunities: list[dict[str, Any]] = []
    notes: list[str] = []
    for market, payload in sorted(latest.items()):
        source = payload["_source_file"]
        for edge in payload.get("qualified_edges", []):
            opportunities.append(_edge_opportunity(edge, source, names, "bet"))
        for edge in payload.get("near_misses", [])[:NEAR_MISS_DISPLAY_LIMIT]:
            opportunities.append(_edge_opportunity(edge, source, names, "review"))
        missing = payload.get("missing_books", [])
        if missing:
            notes.append(f"{market}: {len(missing)} books missing odds")
        event = payload.get("event_name")
        if event:
            notes.append(f"{market}: {event} ({payload.get('generated_at', '?')[:10]})")

    positions, exposures = _open_paper_positions()
    status = "ok" if latest else "error"
    if not latest:
        notes.append("no daily-analysis artifacts found; run scripts/run_pipeline.py")

    return {
        "contract_version": CONTRACT_VERSION,
        "strategy_id": "sportsbook-edges",
        "strategy_name": "Sportsbook Weekly Edges",
        "sleeve": "core",
        "generated_at": _now_iso(),
        "inputs_hash": _inputs_hash({k: v.get("artifact_hash") for k, v in latest.items()}),
        "health": {"status": status, "notes": notes},
        "opportunities": opportunities,
        "positions": positions,
        "exposures": exposures,
        "actions": [
            {"id": "run-edge-pipeline-dry", "label": "Edge pipeline (dry run)"},
            {"id": "run-edge-pipeline", "label": "Edge pipeline (persist)"},
        ],
    }


# ---------------------------------------------------------------------------
# splash-dfs
# ---------------------------------------------------------------------------

def build_splash_status(artifact_dir: Path) -> dict[str, Any]:
    portfolio_file = artifact_dir / "rungood-splash-portfolios.json"
    opportunities: list[dict[str, Any]] = []
    notes: list[str] = []
    payload: dict[str, Any] = {}

    if portfolio_file.exists():
        payload = json.loads(portfolio_file.read_text())
        contest = payload.get("contest", {})
        entry_fee = contest.get("entry_fee_cents", 0) / 100.0
        for name, portfolio in sorted(payload.get("portfolios", {}).items()):
            lineups = portfolio.get("lineup_count", 0)
            roi = portfolio.get("expected_roi")
            opportunities.append(
                {
                    "id": f"splash-portfolio-{name}",
                    "market": "splash_contest",
                    "description": (
                        f"{contest.get('name', 'contest')}: '{name}' portfolio, "
                        f"{lineups} lineups @ ${entry_fee:.0f}"
                    ),
                    "fair_prob": None,
                    "book_prob": None,
                    "edge": roi,
                    "recommended_action": "review",
                    "stake_suggestion": f"${entry_fee * lineups:.0f} total entries",
                    "expires_at": None,
                    "provenance": {
                        "artifact": portfolio_file.name,
                        "inputs_hash": portfolio.get("inputs_hash"),
                    },
                }
            )
        for item in payload.get("hard_review_items", []):
            notes.append(str(item))
    else:
        notes.append("no splash portfolio artifact; run scripts/run_splash_workflow.py")

    ledger_file = artifact_dir / "splash-capture" / "splash-results-ledger.json"
    positions: list[dict[str, Any]] = []
    total_at_risk = 0.0
    if ledger_file.exists():
        try:
            for entry in json.loads(ledger_file.read_text()).get("entries", []):
                if entry.get("status", "open") != "open":
                    continue
                stake = float(entry.get("entry_cost_dollars", 0.0))
                positions.append(
                    {
                        "id": str(entry.get("id", "splash-entry")),
                        "description": entry.get("description", "splash entry"),
                        "stake": stake,
                        "placed_at": entry.get("placed_at"),
                        "status": "open",
                        "detail": {"market": "splash_contest"},
                    }
                )
                total_at_risk += stake
        except (json.JSONDecodeError, TypeError, ValueError):
            notes.append(f"unparseable ledger: {ledger_file.name}")

    return {
        "contract_version": CONTRACT_VERSION,
        "strategy_id": "splash-dfs",
        "strategy_name": "Splash Sports DFS",
        "sleeve": "dfs",
        "generated_at": _now_iso(),
        "inputs_hash": _inputs_hash(payload.get("artifact_hash", "")),
        "health": {"status": "ok" if portfolio_file.exists() else "error", "notes": notes},
        "opportunities": opportunities,
        "positions": positions,
        "exposures": {"total_at_risk": round(total_at_risk, 2)},
        "actions": [{"id": "splash-preflight", "label": "Splash preflight gate"}],
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts",
        help="Directory containing pipeline artifacts (default: artifacts/)",
    )
    args = parser.parse_args()

    out_dir = args.artifact_dir / "control-plane"
    statuses = [
        build_sportsbook_status(args.artifact_dir),
        build_splash_status(args.artifact_dir),
    ]
    for status in statuses:
        out = out_dir / f"{status['strategy_id']}.status.json"
        _atomic_write(out, status)
        print(
            f"wrote {out.relative_to(PROJECT_ROOT) if out.is_relative_to(PROJECT_ROOT) else out}"
            f" — {len(status['opportunities'])} opportunities,"
            f" {len(status['positions'])} open positions,"
            f" health={status['health']['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
