"""
Tournament-week pipeline: fetch → price → detect edges → persist candidates.

Chains the upstream modules that the paper-trading runbook assumes have
already run.  After this script completes, `paper_trade.py ticket-candidates`
and the operator console can pick up the persisted candidates.

Usage:
    PAPER_DB=sqlite:////private/tmp/upanddown-paper-review.db

    PYTHONPATH=. .venv/bin/python scripts/run_pipeline.py \
      --database-url "$PAPER_DB" \
      --tour pga \
      --books draftkings fanduel \
      --analysis-output artifacts/daily-analysis.json

    # Dry-run mode (print edges, don't persist):
    PYTHONPATH=. .venv/bin/python scripts/run_pipeline.py \
      --tour pga --books draftkings fanduel --dry-run \
      --analysis-output artifacts/daily-analysis-dry-run.json

The script:
  1. Fetches live odds from DataGolf's betting-tools endpoint.
  2. Prices every supported market using DG's own baseline (no custom model overlay).
  3. Parses each requested book's odds from the same response.
  4. Computes edges (fair price vs. book price).
  5. Filters to edges that pass the configured threshold.
  6. Persists Tournament, Player, and BetCandidate rows to the target DB.

Supported live markets: tournament matchups, top_20, top_10, top_5, make_cut,
and outright_win.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.ingestion.datagolf import DataGolfClient
from src.ingestion.sportsbooks import (
    _outright_datagolf_id,
    _outright_entries,
    available_books_in_matchups,
    available_books_in_outrights,
)
from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.pricing.fair_price import METHOD_DATAGOLF_DIRECT, FairPriceResult
from src.pricing.matchups import price_matchup_from_datagolf
from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import EdgeResult, compute_one_sided_edge, compute_two_way_edges
from src.storage.db import get_session, init_db
from src.storage.hashing import stable_hash
from src.storage.models import Player, Tournament

logger = logging.getLogger(__name__)

FORECAST_BACKED_OUTRIGHT_MARKETS = {
    "top_20": "top_20",
    "top_10": "top_10",
    "top_5": "top_5",
    "make_cut": "make_cut",
    "outright_win": "win",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_tournament(
    session,
    event_name: str,
    tour: str,
) -> Tournament:
    """Find an existing tournament row by name+tour, or create one."""
    existing = (
        session.query(Tournament)
        .filter_by(name=event_name, tour=tour)
        .first()
    )
    if existing is not None:
        return existing
    row = Tournament(name=event_name, tour=tour, status="scheduled")
    session.add(row)
    session.flush()
    logger.info("Created tournament: %s (id=%d)", event_name, row.tournament_id)
    return row


def _get_or_create_player(
    session,
    datagolf_id: str,
    display_name: str,
) -> Player:
    """Find an existing player by DG id, or create one."""
    existing = (
        session.query(Player)
        .filter_by(datagolf_player_id=datagolf_id)
        .first()
    )
    if existing is not None:
        return existing
    row = Player(
        datagolf_player_id=datagolf_id,
        name_canonical=display_name,
    )
    session.add(row)
    session.flush()
    return row


def _ensure_players_from_matchups(session, match_list: list[dict]) -> dict[str, int]:
    """Create Player rows for every golfer in the matchup response.

    Returns a mapping of datagolf_id → player_id (DB PK).
    """
    player_map: dict[str, int] = {}
    for entry in match_list:
        n_players = 3 if "p3_player_name" in entry else 2
        for i in range(1, n_players + 1):
            pk = f"p{i}"
            dg_id = entry.get(f"{pk}_datagolf_id", entry.get(f"{pk}_dg_id", ""))
            name = entry.get(f"{pk}_player_name", dg_id)
            if not dg_id or dg_id in player_map:
                continue
            player = _get_or_create_player(session, str(dg_id), name)
            player_map[str(dg_id)] = player.player_id
    return player_map


def _ensure_players_from_outrights(session, player_entries: list[dict]) -> dict[str, int]:
    """Create Player rows for every golfer in an outrights/top-N response."""
    player_map: dict[str, int] = {}
    for entry in player_entries:
        dg_id = _outright_datagolf_id(entry)
        if not dg_id or dg_id in player_map:
            continue
        player = _get_or_create_player(
            session,
            dg_id,
            entry.get("player_name", dg_id),
        )
        player_map[dg_id] = player.player_id
    return player_map


def _resolve_requested_books(books: list[str], available: list[str]) -> list[str]:
    """Cross-reference requested books against what's actually in the response.

    Warns on any requested book that's missing, and exits if none are available
    at all — shared by both the matchup and forecast-backed outright pipelines.
    """
    requested_and_available = [book for book in books if book in available]
    missing = [book for book in books if book not in available]
    if missing:
        print(f"WARNING: requested books not in response: {', '.join(missing)}")
    if not requested_and_available:
        print("ERROR: none of the requested books have odds in this response.")
        sys.exit(1)
    return requested_and_available


def _persist_candidates_and_report(
    *,
    dry_run: bool,
    passing: list[EdgeResult],
    all_edges: list[EdgeResult],
    database_url: str | None,
    event_name: str,
    tour: str,
    ensure_players,
    player_source_entries: list[dict],
    settings,
    as_of: datetime,
) -> list[EdgeResult]:
    """Persist passing candidates and print the operator next-steps epilogue.

    Shared tail of the matchup and forecast-backed outright pipelines — the
    only thing that varies between markets is how player rows get ensured.
    """
    if dry_run:
        print("\n[dry-run] No candidates persisted.")
        return all_edges

    if not passing:
        print("\nNo candidates to persist.")
        return all_edges

    print(f"\nPersisting {len(passing)} candidates to {database_url}...")
    with get_session(database_url) as session:
        tournament = _get_or_create_tournament(session, event_name, tour)
        player_map = ensure_players(session, player_source_entries)

        candidates = build_bet_candidates_from_edges(
            passing,
            tournament_id=tournament.tournament_id,
            player_id_by_datagolf_id=player_map,
            fdr_enabled=settings.edge.fdr_enabled,
            fdr_q_core=settings.edge.fdr_q_core,
            fdr_q_convex=settings.edge.fdr_q_convex,
            staleness_flag=False,
            created_at=as_of,
        )

        for candidate in candidates:
            session.add(candidate)
        session.flush()

        print(f"Persisted {len(candidates)} candidates for tournament_id={tournament.tournament_id}")
        for candidate in candidates:
            print(
                f"  candidate_id={candidate.candidate_id}  {candidate.side:<22} "
                f"market={candidate.market_type:<8} book={candidate.book:<12} "
                f"edge={candidate.edge_pct:>5.1%}"
            )

    print("\nDone. Next steps:")
    print(f"  1. Review candidates:  paper_trade.py list-candidates --database-url {database_url}")
    print(f"  2. Generate tickets:   paper_trade.py ticket-candidates --database-url {database_url} --total-bankroll <AMOUNT>")
    print(f"  3. Or use the console: operator_console.py --database-url {database_url}")

    return all_edges


def _extract_book_odds_for_matchup(
    entry: dict,
    book_id: str,
) -> tuple[int, int] | None:
    """Pull p1/p2 American odds for a specific book from a matchup entry.

    Returns (p1_odds, p2_odds) or None if the book hasn't posted this matchup.

    DataGolf responses may nest book odds under an ``"odds"`` sub-dict or
    place them at the top level of each match entry.  This handles both
    shapes, matching the logic in ``sportsbooks._matchup_book_odds``.
    """
    # Check the nested "odds" sub-dict first, then fall back to top-level keys.
    odds_sub = entry.get("odds")
    if isinstance(odds_sub, dict):
        book_data = odds_sub.get(book_id)
    else:
        book_data = entry.get(book_id)

    if not isinstance(book_data, dict):
        return None

    p1 = book_data.get("p1_odds", book_data.get("p1"))
    p2 = book_data.get("p2_odds", book_data.get("p2"))
    if p1 is None or p2 is None:
        return None
    try:
        return int(p1), int(p2)
    except (TypeError, ValueError):
        return None


def _extract_book_odds_for_outright(entry: dict, book_id: str) -> int | None:
    return _parse_american_odds(entry.get(book_id))


def _extract_datagolf_fair_odds(entry: dict) -> int | None:
    datagolf = entry.get("datagolf")
    if isinstance(datagolf, dict):
        odds = datagolf.get("baseline_history_fit", datagolf.get("baseline"))
        parsed = _parse_american_odds(odds)
        if parsed is not None:
            return parsed
    return _parse_american_odds(
        entry.get("datagolf_baseline_history_fit", entry.get("datagolf_baseline"))
    )


def _parse_american_odds(value) -> int | None:
    if value is None:
        return None
    try:
        return round(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def build_daily_analysis_artifact(
    *,
    event_name: str,
    tour: str,
    market: str,
    last_updated: str,
    requested_books: list[str],
    available_books: list[str],
    evaluated_books: list[str],
    missing_books: list[str],
    rows_seen: int,
    rows_skipped: int,
    edges: list[EdgeResult],
    min_edge_core: float,
    min_edge_convex: float,
    dry_run: bool,
    generated_at: datetime,
    near_miss_limit: int,
) -> dict[str, Any]:
    """Build the durable daily analysis artifact for play and no-play days."""
    qualified = sorted(
        [edge for edge in edges if edge.passes_threshold],
        key=lambda edge: edge.edge,
        reverse=True,
    )
    near_misses = sorted(
        [edge for edge in edges if not edge.passes_threshold],
        key=lambda edge: edge.edge,
        reverse=True,
    )[:near_miss_limit]

    artifact = {
        "artifact_type": "daily_analysis_run",
        "generated_at": generated_at.isoformat(),
        "event_name": event_name,
        "tour": tour,
        "market": market,
        "source_last_updated": last_updated,
        "dry_run": dry_run,
        "requested_books": requested_books,
        "available_books": available_books,
        "evaluated_books": evaluated_books,
        "missing_books": missing_books,
        "rows_seen": rows_seen,
        "rows_skipped": rows_skipped,
        "edges_computed": len(edges),
        "qualified_edges_count": len(qualified),
        "thresholds": {
            "core": min_edge_core,
            "convex": min_edge_convex,
        },
        "qualified_edges": [
            _edge_artifact_payload(edge, min_edge_core, min_edge_convex)
            for edge in qualified
        ],
        "near_misses": [
            _edge_artifact_payload(edge, min_edge_core, min_edge_convex)
            for edge in near_misses
        ],
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return artifact


def write_daily_analysis_artifact(
    output_path: Path | None,
    artifact: dict[str, Any],
) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nAnalysis artifact written: {output_path}")
    print(f"Artifact hash: {artifact['artifact_hash']}")


def _edge_artifact_payload(
    edge: EdgeResult,
    min_edge_core: float,
    min_edge_convex: float,
) -> dict[str, Any]:
    threshold = min_edge_convex if edge.sleeve == "convex" else min_edge_core
    return {
        "datagolf_id": edge.datagolf_id,
        "opponent_id": edge.opponent_id,
        "market_type": edge.market_type,
        "book_id": edge.book_id,
        "fair_prob": edge.fair_prob,
        "book_prob": edge.book_no_vig_prob,
        "vig_removed": edge.vig_removed,
        "edge": edge.edge,
        "threshold": threshold,
        # Positive: cleared the threshold by this much. Negative: still short by this much.
        "margin_to_threshold": edge.edge - threshold,
        "sleeve": edge.sleeve,
        "passes_threshold": edge.passes_threshold,
        "book_american_odds": edge.book_american_odds,
        "edge_sd": edge.edge_sd,
        "p_value": edge.p_value,
        "passes_fdr": edge.passes_fdr,
    }


def _run_forecast_backed_outright_pipeline(
    database_url: str | None,
    tour: str,
    books: list[str],
    market: str,
    datagolf_market: str,
    dry_run: bool,
    settings,
    api_key: str,
    analysis_output: Path | None,
    near_miss_limit: int,
) -> list[EdgeResult]:
    """Execute the live DataGolf outrights fetch → edge → persist pipeline."""
    if settings.edge.fdr_enabled:
        raise SystemExit(
            "edge.fdr_enabled is true, but one-sided forecast markets "
            f"({market}) don't yet populate edge_sd, which FDR control requires. "
            "Set edge.fdr_enabled: false in config/settings.yaml before running "
            "this market, or wait for FDR support to land for one-sided edges."
        )
    if datagolf_market == market:
        print(f"Fetching {market} odds from DataGolf (tour={tour})...")
    else:
        print(f"Fetching {market} odds from DataGolf (market={datagolf_market}, tour={tour})...")

    if not dry_run and database_url:
        init_db(database_url)

    fetch_session_url = database_url
    if dry_run:
        fetch_session_url = "sqlite://"
        init_db(fetch_session_url)

    with get_session(fetch_session_url) as session:
        client = DataGolfClient(api_key=api_key, session=session)
        result = client.fetch_live_outrights(
            tour=tour,
            market=datagolf_market,
            odds_format="american",
        )
    raw = result.data

    event_name = raw.get("event_name", "unknown")
    last_updated = raw.get("last_updated", "")
    player_entries = _outright_entries(raw)
    print(f"Event: {event_name}")
    print(f"Last updated: {last_updated}")
    print(f"Players in response: {len(player_entries)}")

    available = available_books_in_outrights(raw)
    print(f"Books with odds: {', '.join(available) if available else 'none'}")

    requested_and_available = _resolve_requested_books(books, available)
    missing = [book for book in books if book not in available]

    print(f"\nPricing {len(player_entries)} {market} rows via DataGolf baseline...")
    as_of = datetime.now(UTC)
    all_edges: list[EdgeResult] = []
    skipped = 0
    player_names: dict[str, str] = {}

    for entry in player_entries:
        dg_id = _outright_datagolf_id(entry)
        player_names[dg_id] = entry.get("player_name", dg_id)
        fair_odds = _extract_datagolf_fair_odds(entry)
        if not dg_id or fair_odds is None:
            skipped += 1
            continue

        try:
            fair_prob = decimal_to_implied(american_to_decimal(fair_odds))
        except ValueError as exc:
            logger.warning("Skipping %s row (fair odds error): %s", market, exc)
            skipped += 1
            continue

        fair = FairPriceResult(
            market_type=market,
            datagolf_id=dg_id,
            opponent_id=None,
            fair_prob=fair_prob,
            method=METHOD_DATAGOLF_DIRECT,
            as_of=as_of,
        )

        for book_id in requested_and_available:
            book_odds = _extract_book_odds_for_outright(entry, book_id)
            if book_odds is None:
                continue
            try:
                all_edges.append(
                    compute_one_sided_edge(
                        fair=fair,
                        book_american_odds=book_odds,
                        book_id=book_id,
                        min_edge_core=settings.edge.min_edge_core,
                        min_edge_convex=settings.edge.min_edge_convex,
                    )
                )
            except ValueError as exc:
                logger.warning("Skipping %s edge (math error): %s", market, exc)

    passing = [edge for edge in all_edges if edge.passes_threshold]
    print(f"\nEdges computed: {len(all_edges)} total, {len(passing)} pass threshold")
    if skipped:
        print(f"Players skipped (missing/invalid DataGolf fair line): {skipped}")

    if passing:
        print(f"\n{'='*84}")
        print(f"{'Player':<28} {'Book':<12} {'Edge':>6} {'Fair':>6} {'Book':>6} {'Line':>6}")
        print(f"{'='*84}")
        for edge in sorted(passing, key=lambda item: item.edge, reverse=True):
            name = player_names.get(edge.datagolf_id, edge.datagolf_id)
            print(
                f"{name:<28} {edge.book_id:<12} "
                f"{edge.edge:>5.1%} {edge.fair_prob:>5.1%} {edge.book_no_vig_prob:>5.1%} "
                f"{edge.book_american_odds:>+5d}"
            )
        print(f"{'='*84}")
    else:
        print("\nNo edges above threshold. This is a valid outcome — no action needed.")

    write_daily_analysis_artifact(
        analysis_output,
        build_daily_analysis_artifact(
            event_name=event_name,
            tour=tour,
            market=market,
            last_updated=last_updated,
            requested_books=books,
            available_books=available,
            evaluated_books=requested_and_available,
            missing_books=missing,
            rows_seen=len(player_entries),
            rows_skipped=skipped,
            edges=all_edges,
            min_edge_core=settings.edge.min_edge_core,
            min_edge_convex=settings.edge.min_edge_convex,
            dry_run=dry_run,
            generated_at=as_of,
            near_miss_limit=near_miss_limit,
        ),
    )

    return _persist_candidates_and_report(
        dry_run=dry_run,
        passing=passing,
        all_edges=all_edges,
        database_url=database_url,
        event_name=event_name,
        tour=tour,
        ensure_players=_ensure_players_from_outrights,
        player_source_entries=player_entries,
        settings=settings,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    database_url: str | None,
    tour: str,
    books: list[str],
    dry_run: bool,
    market: str,
    analysis_output: Path | None = None,
    near_miss_limit: int = 10,
) -> list[EdgeResult]:
    """Execute the full fetch → price → edge → persist pipeline.

    Returns all edges found (both passing and failing threshold), for
    display purposes.  Only threshold-passing edges become candidates.
    """
    settings = get_settings()
    api_key = settings.secrets.datagolf_api_key
    if not api_key:
        print("ERROR: DATAGOLF_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    if market in FORECAST_BACKED_OUTRIGHT_MARKETS:
        return _run_forecast_backed_outright_pipeline(
            database_url=database_url,
            tour=tour,
            books=books,
            market=market,
            datagolf_market=FORECAST_BACKED_OUTRIGHT_MARKETS[market],
            dry_run=dry_run,
            settings=settings,
            api_key=api_key,
            analysis_output=analysis_output,
            near_miss_limit=near_miss_limit,
        )

    # -- 1. Fetch live matchup odds from DataGolf --------------------------
    print(f"Fetching {market} odds from DataGolf (tour={tour})...")

    if not dry_run and database_url:
        init_db(database_url)

    # Use a temporary session just for the fetch (snapshot persistence),
    # then a real session for candidate persistence.
    fetch_session_url = database_url
    if dry_run:
        # In dry-run we still need a session for the DG client, but we
        # don't want to write to the paper DB.  Use an in-memory DB.
        fetch_session_url = "sqlite://"
        init_db(fetch_session_url)

    with get_session(fetch_session_url) as session:
        client = DataGolfClient(api_key=api_key, session=session)
        result = client.fetch_live_matchups(
            tour=tour,
            market=market,
            odds_format="american",
        )
    raw = result.data

    event_name = raw.get("event_name", "unknown")
    last_updated = raw.get("last_updated", "")
    match_list = raw.get("match_list", [])
    print(f"Event: {event_name}")
    print(f"Last updated: {last_updated}")
    print(f"Matchups in response: {len(match_list)}")

    # Discover which books are actually present
    available = available_books_in_matchups(raw)
    print(f"Books with odds: {', '.join(available) if available else 'none'}")

    requested_and_available = _resolve_requested_books(books, available)
    missing = [b for b in books if b not in available]

    # -- 2. Price every matchup using DG baseline --------------------------
    print(f"\nPricing {len(match_list)} matchups via DataGolf baseline...")

    as_of = datetime.now(UTC)
    all_edges: list[EdgeResult] = []
    skipped = 0

    for entry in match_list:
        # Skip 3-balls in MVP — only 2-ball matchups
        if "p3_player_name" in entry:
            skipped += 1
            continue

        # Get DG fair prices for both sides
        try:
            fair_prices = price_matchup_from_datagolf(entry, as_of=as_of)
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping matchup (pricing error): %s", exc)
            skipped += 1
            continue

        if len(fair_prices) != 2:
            skipped += 1
            continue

        fair_p1, fair_p2 = fair_prices

        # -- 3. For each book, compute edges -------------------------------
        for book_id in requested_and_available:
            odds = _extract_book_odds_for_matchup(entry, book_id)
            if odds is None:
                continue
            p1_odds, p2_odds = odds

            try:
                edge_p1, edge_p2 = compute_two_way_edges(
                    fair_p1=fair_p1,
                    fair_p2=fair_p2,
                    book_odds_p1=p1_odds,
                    book_odds_p2=p2_odds,
                    book_id=book_id,
                    min_edge_core=settings.edge.min_edge_core,
                    min_edge_convex=settings.edge.min_edge_convex,
                    vig_method=settings.vig_removal.two_way_method,
                )
                all_edges.extend([edge_p1, edge_p2])
            except (ValueError, ZeroDivisionError) as exc:
                logger.warning("Skipping matchup edge (math error): %s", exc)

    passing = [e for e in all_edges if e.passes_threshold]
    print(f"\nEdges computed: {len(all_edges)} total, {len(passing)} pass threshold")
    if skipped:
        print(f"Matchups skipped (3-balls or errors): {skipped}")

    # -- 4. Display results ------------------------------------------------
    if passing:
        print(f"\n{'='*72}")
        print(f"{'Player':<22} {'vs':<22} {'Book':<12} {'Edge':>6} {'Fair':>6} {'NoVig':>6} {'Line':>6}")
        print(f"{'='*72}")
        for e in sorted(passing, key=lambda x: x.edge, reverse=True):
            opp = e.opponent_id or ""
            print(
                f"{e.datagolf_id:<22} {opp:<22} {e.book_id:<12} "
                f"{e.edge:>5.1%} {e.fair_prob:>5.1%} {e.book_no_vig_prob:>5.1%} "
                f"{e.book_american_odds:>+5d}"
            )
        print(f"{'='*72}")
    else:
        print("\nNo edges above threshold. This is a valid outcome — no action needed.")

    write_daily_analysis_artifact(
        analysis_output,
        build_daily_analysis_artifact(
            event_name=event_name,
            tour=tour,
            market=market,
            last_updated=last_updated,
            requested_books=books,
            available_books=available,
            evaluated_books=requested_and_available,
            missing_books=missing,
            rows_seen=len(match_list),
            rows_skipped=skipped,
            edges=all_edges,
            min_edge_core=settings.edge.min_edge_core,
            min_edge_convex=settings.edge.min_edge_convex,
            dry_run=dry_run,
            generated_at=as_of,
            near_miss_limit=near_miss_limit,
        ),
    )

    # -- 5. Persist candidates to DB ---------------------------------------
    return _persist_candidates_and_report(
        dry_run=dry_run,
        passing=passing,
        all_edges=all_edges,
        database_url=database_url,
        event_name=event_name,
        tour=tour,
        ensure_players=_ensure_players_from_matchups,
        player_source_entries=match_list,
        settings=settings,
        as_of=as_of,
    )

    return all_edges


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tournament-week pipeline: fetch → price → edge → persist candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy DB URL for the paper-trading database. "
             "Required unless --dry-run is set.",
    )
    parser.add_argument(
        "--tour",
        default="pga",
        help="DataGolf tour identifier (default: pga).",
    )
    parser.add_argument(
        "--books",
        nargs="+",
        default=["draftkings", "fanduel"],
        help="Sportsbooks to compute edges against (default: draftkings fanduel).",
    )
    parser.add_argument(
        "--market",
        default="tournament_matchups",
        choices=["tournament_matchups", "round_matchups", "3_balls", *FORECAST_BACKED_OUTRIGHT_MARKETS],
        help="DataGolf market type (default: tournament_matchups).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compute edges but don't persist anything.",
    )
    parser.add_argument(
        "--analysis-output",
        type=Path,
        default=None,
        help="Optional path to write a daily analysis JSON artifact.",
    )
    parser.add_argument(
        "--near-miss-limit",
        type=int,
        default=10,
        help="Number of non-qualified edges to include in the analysis artifact.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.database_url:
        parser.error("--database-url is required unless --dry-run is set.")
    if args.near_miss_limit < 0:
        parser.error("--near-miss-limit must be non-negative.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    run_pipeline(
        database_url=args.database_url,
        tour=args.tour,
        books=args.books,
        dry_run=args.dry_run,
        market=args.market,
        analysis_output=args.analysis_output,
        near_miss_limit=args.near_miss_limit,
    )


if __name__ == "__main__":
    main()
