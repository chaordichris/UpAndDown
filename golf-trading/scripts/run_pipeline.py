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
      --books draftkings fanduel

    # Dry-run mode (print edges, don't persist):
    PYTHONPATH=. .venv/bin/python scripts/run_pipeline.py \
      --tour pga --books draftkings fanduel --dry-run

The script:
  1. Fetches live matchup odds from DataGolf's betting-tools endpoint.
  2. Prices every matchup using DG's own baseline (no custom model overlay).
  3. Parses each requested book's odds from the same response.
  4. Computes two-way edges (fair price vs. book no-vig price).
  5. Filters to edges that pass the configured threshold.
  6. Persists Tournament, Player, and BetCandidate rows to the target DB.

No markets beyond tournament matchups are processed in MVP.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from src.config import get_settings
from src.ingestion.datagolf import DataGolfClient
from src.ingestion.sportsbooks import available_books_in_matchups
from src.pricing.matchups import price_matchup_from_datagolf
from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import EdgeResult, compute_two_way_edges
from src.storage.db import get_session, init_db
from src.storage.models import BetCandidate, Player, Tournament

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    database_url: str | None,
    tour: str,
    books: list[str],
    dry_run: bool,
    market: str,
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

    requested_and_available = [b for b in books if b in available]
    missing = [b for b in books if b not in available]
    if missing:
        print(f"WARNING: requested books not in response: {', '.join(missing)}")
    if not requested_and_available:
        print("ERROR: none of the requested books have odds in this response.")
        sys.exit(1)

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

    if dry_run:
        print("\n[dry-run] No candidates persisted.")
        return all_edges

    if not passing:
        print("\nNo candidates to persist.")
        return all_edges

    # -- 5. Persist candidates to DB ---------------------------------------
    print(f"\nPersisting {len(passing)} candidates to {database_url}...")

    with get_session(database_url) as session:
        tournament = _get_or_create_tournament(session, event_name, tour)
        player_map = _ensure_players_from_matchups(session, match_list)

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

        for c in candidates:
            session.add(c)
        session.flush()

        print(f"Persisted {len(candidates)} candidates for tournament_id={tournament.tournament_id}")
        for c in candidates:
            print(
                f"  candidate_id={c.candidate_id}  {c.side:<22} "
                f"book={c.book:<12} edge={c.edge_pct:>5.1%}"
            )

    print("\nDone. Next steps:")
    print(f"  1. Review candidates:  paper_trade.py list-candidates --database-url {database_url}")
    print(f"  2. Generate tickets:   paper_trade.py ticket-candidates --database-url {database_url} --total-bankroll <AMOUNT>")
    print(f"  3. Or use the console: operator_console.py --database-url {database_url}")

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
        choices=["tournament_matchups", "round_matchups", "3_balls"],
        help="DataGolf matchup market type (default: tournament_matchups).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compute edges but don't persist anything.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.database_url:
        parser.error("--database-url is required unless --dry-run is set.")

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
    )


if __name__ == "__main__":
    main()
