"""Phase 3 paper-trade CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_settings
from src.execution.candidates import build_ticket_from_candidate, ticket_unticketed_candidates
from src.execution.persistence import (
    persist_clv,
    persist_placement,
    persist_settlement,
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.execution.placement import log_placement
from src.execution.settlement import settle_placement
from src.execution.tickets import generate_ticket, render_ticket
from src.monitoring.attribution import record_attribution_for_bet_row
from src.monitoring.clv import compute_clv
from src.monitoring.reports import (
    Phase3EvidenceReport,
    Phase3ReadinessReport,
    build_phase3_evidence_report,
    build_phase3_readiness_report,
    build_stored_paper_trade_report,
    export_tickets_csv,
    render_open_actions,
    render_phase3_evidence_report,
    render_phase3_readiness_report,
    render_stored_report,
    render_ticket_detail,
)
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet
from src.storage.db import get_session, init_db
from src.storage.hashing import artifact_hash
from src.storage.models import BetCandidate, BetOutcome, BetTicket, PlacedBet, Player, Tournament


def _sample_edge() -> EdgeResult:
    return EdgeResult(
        datagolf_id="scheffler",
        opponent_id="mcIlroy",
        market_type="matchup_2ball",
        book_id="dk",
        fair_prob=0.56,
        book_no_vig_prob=0.51,
        edge=0.05,
        sleeve="core",
        passes_threshold=True,
        book_american_odds=-110,
    )


def _sample_ticket():
    edge = _sample_edge()
    sizing = size_core_bet(
        edge=edge,
        active_bankroll=10_000.0,
        total_bankroll=25_000.0,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    return generate_ticket(
        edge,
        sizing,
        tournament_id="paper_trade_smoke",
        created_at=datetime.now(UTC),
    )


def run_smoke(args: argparse.Namespace) -> None:
    del args
    print(render_ticket(_sample_ticket()))


def run_persist_smoke(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        ticket = _sample_ticket()
        candidate = _create_sample_candidate(session)
        ticket_row = persist_ticket(session, ticket, candidate_id=candidate.candidate_id)

        placement = log_placement(
            ticket,
            actual_american_odds=args.actual_odds,
            actual_stake=args.actual_stake,
            placed_at=datetime.now(UTC),
            notes="paper_trade.py persist-smoke",
        )
        placed_row = persist_placement(
            session,
            placement,
            ticket_id=ticket_row.ticket_id,
            bet_class=args.bet_class,
            boost_terms_json=args.boost_terms_json,
        )

        settlement = settle_placement(
            placement,
            result=args.result,
            settled_at=datetime.now(UTC),
            notes="paper_trade.py persist-smoke",
        )
        outcome_row = persist_settlement(session, settlement, bet_id=placed_row.bet_id)

        clv = compute_clv(
            ticket,
            placement,
            closing_american_odds=args.closing_odds,
            captured_at=datetime.now(UTC),
        )
        clv_row = persist_clv(session, clv, bet_id=placed_row.bet_id)
        attribution_row = record_attribution_for_bet_row(
            session,
            placed_row,
            ticket_row,
            candidate,
            outcome_row,
            flat_stake=args.flat_stake,
            created_at=datetime.now(UTC),
        )

        print(render_ticket(ticket))
        print("")
        print("Persisted rows:")
        print(f"candidate_id={candidate.candidate_id}")
        print(f"ticket_id={ticket_row.ticket_id}")
        print(f"bet_id={placed_row.bet_id}")
        print(f"outcome_id={outcome_row.outcome_id}")
        print(f"clv_id={clv_row.clv_id}")
        print(f"attribution_id={attribution_row.attribution_id}")


def run_create_smoke_ticket(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        ticket = _sample_ticket()
        candidate = _create_sample_candidate(session)
        ticket_row = persist_ticket(session, ticket, candidate_id=candidate.candidate_id)

        print(render_ticket(ticket))
        print("")
        print("Persisted rows:")
        print(f"candidate_id={candidate.candidate_id}")
        print(f"ticket_id={ticket_row.ticket_id}")


def run_create_smoke_candidate(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        candidate = _create_sample_candidate(session)
        print("Persisted rows:")
        print(f"candidate_id={candidate.candidate_id}")


def run_ticket_candidate(args: argparse.Namespace) -> None:
    settings = get_settings()
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        candidate = _require_row(session, BetCandidate, args.candidate_id, "candidate")
        primary_player = _require_row(session, Player, candidate.player_id_1, "player")
        opponent_player = (
            _require_row(session, Player, candidate.player_id_2, "player")
            if candidate.player_id_2 is not None
            else None
        )
        ticket = build_ticket_from_candidate(
            candidate,
            primary_player,
            opponent_player=opponent_player,
            book_american_odds=args.book_odds,
            total_bankroll=args.total_bankroll,
            reserve_fraction=settings.bankroll.reserve_fraction,
            active_core_fraction=settings.bankroll.active_core_fraction,
            convex_fraction=settings.bankroll.convex_fraction,
            kelly_multiplier=settings.sizing.kelly_fraction,
            convex_unit_fraction=settings.sizing.convex_unit_fraction,
            min_bet_dollars=settings.sizing.min_bet_dollars,
            max_bet_fraction=settings.sizing.max_bet_fraction,
            min_edge_core=settings.edge.min_edge_core,
            min_edge_convex=settings.edge.min_edge_convex,
            posterior_kelly_enabled=settings.sizing.posterior_kelly_enabled,
            fdr_enabled=settings.edge.fdr_enabled,
            created_at=datetime.now(UTC),
        )
        ticket_row = persist_ticket(session, ticket, candidate_id=candidate.candidate_id)

        print(render_ticket(ticket))
        print("")
        print("Persisted rows:")
        print(f"candidate_id={candidate.candidate_id}")
        print(f"ticket_id={ticket_row.ticket_id}")


def run_ticket_candidates(args: argparse.Namespace) -> None:
    settings = get_settings()
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        rows = ticket_unticketed_candidates(
            session,
            total_bankroll=args.total_bankroll,
            reserve_fraction=settings.bankroll.reserve_fraction,
            active_core_fraction=settings.bankroll.active_core_fraction,
            convex_fraction=settings.bankroll.convex_fraction,
            kelly_multiplier=settings.sizing.kelly_fraction,
            convex_unit_fraction=settings.sizing.convex_unit_fraction,
            min_bet_dollars=settings.sizing.min_bet_dollars,
            max_bet_fraction=settings.sizing.max_bet_fraction,
            min_edge_core=settings.edge.min_edge_core,
            min_edge_convex=settings.edge.min_edge_convex,
            posterior_kelly_enabled=settings.sizing.posterior_kelly_enabled,
            fdr_enabled=settings.edge.fdr_enabled,
            tournament_id=args.tournament_id,
            limit=args.limit,
            created_at=datetime.now(UTC),
        )
        if not rows:
            print("No unticketed candidates found.")
            return

        print(f"Created {len(rows)} ticket(s).")
        for row in rows:
            status = "approved" if row.approved else "rejected"
            print(
                f"ticket_id={row.ticket_id} candidate_id={row.candidate_id} "
                f"status={status} stake=${row.proposed_stake:.2f} odds={row.proposed_american_odds}"
            )


def run_list_candidates(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        query = session.query(BetCandidate).order_by(BetCandidate.candidate_id)
        if args.open_only:
            ticketed_candidate_ids = {
                row.candidate_id for row in session.query(BetTicket.candidate_id).all()
            }
            candidates = [
                candidate
                for candidate in query.all()
                if candidate.candidate_id not in ticketed_candidate_ids
            ]
        else:
            candidates = query.all()

        if not candidates:
            print("No candidates found.")
            return

        for candidate in candidates:
            stale = " stale" if candidate.staleness_flag else ""
            odds = candidate.book_american_odds if candidate.book_american_odds is not None else "missing"
            print(
                f"candidate_id={candidate.candidate_id} tournament_id={candidate.tournament_id} "
                f"market={candidate.market_type} side={candidate.side} book={candidate.book} "
                f"odds={odds} edge={candidate.edge_pct:.2%}{stale}"
            )


def run_list_tickets(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        placed_ticket_ids = {
            row.ticket_id for row in session.query(PlacedBet.ticket_id).all()
        }
        query = session.query(BetTicket).order_by(BetTicket.ticket_id)
        rows = [
            ticket
            for ticket in query.all()
            if not args.unplaced or ticket.ticket_id not in placed_ticket_ids
        ]
        if not rows:
            print("No tickets found.")
            return

        for ticket in rows:
            placed = "placed" if ticket.ticket_id in placed_ticket_ids else "open"
            print(
                f"ticket_id={ticket.ticket_id} candidate_id={ticket.candidate_id} "
                f"status={placed} approved={ticket.approved} "
                f"stake=${ticket.proposed_stake:.2f} odds={ticket.proposed_american_odds}"
            )


def run_show_ticket(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        print(render_ticket_detail(session, args.ticket_id))


def run_export_tickets(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        print(
            export_tickets_csv(
                session,
                unplaced_only=args.unplaced,
                approved_only=args.approved_only,
            ),
            end="",
        )


def run_place_ticket(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        ticket = _require_row(session, BetTicket, args.ticket_id, "ticket")
        candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
        placed = place_ticket_row(
            session,
            ticket,
            candidate,
            actual_american_odds=args.actual_odds,
            actual_stake=args.actual_stake,
            placed_at=datetime.now(UTC),
            notes=args.notes,
            bet_class=args.bet_class,
            boost_terms_json=args.boost_terms_json,
        )
        print(f"bet_id={placed.bet_id}")


def run_settle_bet(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        placed = _require_row(session, PlacedBet, args.bet_id, "bet")
        outcome = settle_bet_row(
            session,
            placed,
            result=args.result,
            settled_at=datetime.now(UTC),
            notes=args.notes,
        )
        print(f"outcome_id={outcome.outcome_id} profit_loss=${outcome.profit_loss:.2f}")


def run_record_clv(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        placed = _require_row(session, PlacedBet, args.bet_id, "bet")
        ticket = _require_row(session, BetTicket, placed.ticket_id, "ticket")
        candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
        clv = record_clv_for_bet_row(
            session,
            placed,
            ticket,
            candidate,
            closing_american_odds=args.closing_odds,
            captured_at=datetime.now(UTC),
        )
        print(f"clv_id={clv.clv_id} clv_raw={clv.clv_raw:.4f} clv_model={clv.clv_model:.4f}")


def run_record_attribution(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        placed = _require_row(session, PlacedBet, args.bet_id, "bet")
        ticket = _require_row(session, BetTicket, placed.ticket_id, "ticket")
        candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
        outcome = session.query(BetOutcome).filter_by(bet_id=placed.bet_id).one_or_none()
        if outcome is None:
            raise SystemExit(f"Bet {placed.bet_id} has no settlement.")
        attribution = record_attribution_for_bet_row(
            session,
            placed,
            ticket,
            candidate,
            outcome,
            flat_stake=args.flat_stake,
            created_at=datetime.now(UTC),
        )
        print(
            f"attribution_id={attribution.attribution_id} "
            f"model_alpha=${attribution.model_alpha:.2f} "
            f"execution_drift=${attribution.execution_drift:.2f} "
            f"sizing_alpha=${attribution.sizing_alpha:.2f} "
            f"variance=${attribution.variance:.2f}"
        )


def run_report(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        report = build_stored_paper_trade_report(session)
        rendered = (
            render_stored_report_json(report, code_version=args.code_version)
            if args.format == "json"
            else render_stored_report(report)
        )
        _write_output(args.output, rendered)
        print(rendered)


def run_readiness(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        readiness = build_phase3_readiness_report(
            session,
            required_tournaments=args.required_tournaments,
            required_settled_bets=args.required_settled_bets,
        )
        rendered = (
            render_phase3_readiness_json(readiness, code_version=args.code_version)
            if args.format == "json"
            else render_phase3_readiness_report(readiness)
        )
        _write_output(args.output, rendered)
        print(rendered)


def run_evidence_check(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        evidence = build_phase3_evidence_report(
            session,
            required_tournaments=args.required_tournaments,
            required_settled_bets=args.required_settled_bets,
        )
        rendered = (
            render_phase3_evidence_json(evidence, code_version=args.code_version)
            if args.format == "json"
            else render_phase3_evidence_report(evidence)
        )
        _write_output(args.output, rendered)
        print(rendered)


def run_open_actions(args: argparse.Namespace) -> None:
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        print(render_open_actions(session))


def _create_sample_candidate(session) -> BetCandidate:
    tournament = (
        session.query(Tournament)
        .filter_by(datagolf_event_id="paper_trade_smoke")
        .one_or_none()
    )
    if tournament is None:
        tournament = Tournament(
            name="Paper Trade Smoke",
            tour="pga",
            datagolf_event_id="paper_trade_smoke",
        )
        session.add(tournament)
        session.flush()

    player = _get_or_create_player(session, "scheffler", "Scottie Scheffler")
    opponent = _get_or_create_player(session, "mcIlroy", "Rory McIlroy")

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="matchup_2ball",
        side="scheffler",
        player_id_1=player.player_id,
        player_id_2=opponent.player_id,
        book="dk",
        fair_prob=0.56,
        book_prob=0.51,
        book_american_odds=-110,
        edge_pct=0.05,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash="paper-trade-smoke-candidate",
        created_at=datetime.now(UTC),
    )
    session.add(candidate)
    session.flush()
    return candidate


def _get_or_create_player(session, datagolf_id: str, name: str) -> Player:
    player = session.query(Player).filter_by(datagolf_player_id=datagolf_id).one_or_none()
    if player is not None:
        return player
    player = Player(datagolf_player_id=datagolf_id, name_canonical=name)
    session.add(player)
    session.flush()
    return player


def _require_row(session, model, row_id: int, label: str):
    row = session.get(model, row_id)
    if row is None:
        raise SystemExit(f"Unknown {label}_id={row_id}")
    return row


def _add_database_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", default=None)


def build_stored_report_artifact(report, *, code_version: str | None = None) -> dict:
    """Build a deterministic paper-trading report artifact."""
    report_payload = asdict(report)
    return {
        "artifact_type": "paper_trade_report",
        "report": report_payload,
        "artifact_hash": artifact_hash(
            artifact_type="paper_trade_report",
            inputs={"report": report_payload},
            config=None,
            code_version=code_version,
        ),
    }


def render_stored_report_json(report, *, code_version: str | None = None) -> str:
    """Render persisted paper-trading metrics as stable JSON."""
    return json.dumps(
        build_stored_report_artifact(report, code_version=code_version),
        sort_keys=True,
        indent=2,
    )


def build_phase3_readiness_artifact(
    readiness: Phase3ReadinessReport,
    *,
    code_version: str | None = None,
) -> dict:
    """Build a deterministic Phase 3 readiness artifact."""
    readiness_payload = asdict(readiness)
    return {
        "artifact_type": "phase3_readiness",
        "readiness": readiness_payload,
        "artifact_hash": artifact_hash(
            artifact_type="phase3_readiness",
            inputs={"readiness": readiness_payload},
            config=None,
            code_version=code_version,
        ),
    }


def render_phase3_readiness_json(
    readiness: Phase3ReadinessReport,
    *,
    code_version: str | None = None,
) -> str:
    """Render Phase 3 readiness as stable JSON."""
    return json.dumps(
        build_phase3_readiness_artifact(readiness, code_version=code_version),
        sort_keys=True,
        indent=2,
    )


def build_phase3_evidence_artifact(
    evidence: Phase3EvidenceReport,
    *,
    code_version: str | None = None,
) -> dict:
    """Build a deterministic Phase 3 evidence-check artifact."""
    evidence_payload = asdict(evidence)
    return {
        "artifact_type": "phase3_evidence_check",
        "evidence": evidence_payload,
        "artifact_hash": artifact_hash(
            artifact_type="phase3_evidence_check",
            inputs={"evidence": evidence_payload},
            config=None,
            code_version=code_version,
        ),
    }


def render_phase3_evidence_json(
    evidence: Phase3EvidenceReport,
    *,
    code_version: str | None = None,
) -> str:
    """Render Phase 3 evidence guardrails as stable JSON."""
    return json.dumps(
        build_phase3_evidence_artifact(evidence, code_version=code_version),
        sort_keys=True,
        indent=2,
    )


def _write_output(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper-trading ticket utilities.")
    subparsers = parser.add_subparsers(dest="command")

    smoke = subparsers.add_parser("smoke", help="Print a sample paper-trade ticket.")
    smoke.set_defaults(func=run_smoke)

    persist = subparsers.add_parser(
        "persist-smoke",
        help="Persist a full sample ticket/place/settle/CLV chain.",
    )
    _add_database_url(persist)
    persist.add_argument("--actual-odds", type=int, default=-105)
    persist.add_argument("--actual-stake", type=float, default=None)
    persist.add_argument("--result", choices=["win", "loss", "push", "void", "dead_heat"], default="win")
    persist.add_argument("--closing-odds", type=int, default=-125)
    persist.add_argument("--flat-stake", type=float, default=None)
    persist.add_argument("--bet-class", choices=["STANDARD", "BOOSTED_ODDS", "FREE_BET", "RISK_FREE"], default="STANDARD")
    persist.add_argument("--boost-terms-json", default=None)
    persist.set_defaults(func=run_persist_smoke)

    create_ticket = subparsers.add_parser(
        "create-smoke-ticket",
        help="Persist a sample candidate and ticket only.",
    )
    _add_database_url(create_ticket)
    create_ticket.set_defaults(func=run_create_smoke_ticket)

    create_candidate = subparsers.add_parser(
        "create-smoke-candidate",
        help="Persist a sample candidate without creating a ticket.",
    )
    _add_database_url(create_candidate)
    create_candidate.set_defaults(func=run_create_smoke_candidate)

    ticket_candidate = subparsers.add_parser(
        "ticket-candidate",
        help="Create a ticket from an existing persisted bet candidate.",
    )
    _add_database_url(ticket_candidate)
    ticket_candidate.add_argument("candidate_id", type=int)
    ticket_candidate.add_argument("--book-odds", type=int, default=None)
    ticket_candidate.add_argument("--total-bankroll", type=float, required=True)
    ticket_candidate.set_defaults(func=run_ticket_candidate)

    ticket_candidates = subparsers.add_parser(
        "ticket-candidates",
        help="Create tickets for all unticketed candidates.",
    )
    _add_database_url(ticket_candidates)
    ticket_candidates.add_argument("--total-bankroll", type=float, required=True)
    ticket_candidates.add_argument("--tournament-id", type=int, default=None)
    ticket_candidates.add_argument("--limit", type=int, default=None)
    ticket_candidates.set_defaults(func=run_ticket_candidates)

    list_candidates = subparsers.add_parser("list-candidates", help="List persisted bet candidates.")
    _add_database_url(list_candidates)
    list_candidates.add_argument("--open-only", action="store_true")
    list_candidates.set_defaults(func=run_list_candidates)

    list_tickets = subparsers.add_parser("list-tickets", help="List persisted bet tickets.")
    _add_database_url(list_tickets)
    list_tickets.add_argument("--unplaced", action="store_true")
    list_tickets.set_defaults(func=run_list_tickets)

    show_ticket = subparsers.add_parser("show-ticket", help="Show one persisted ticket as a bet slip.")
    _add_database_url(show_ticket)
    show_ticket.add_argument("ticket_id", type=int)
    show_ticket.set_defaults(func=run_show_ticket)

    export_tickets = subparsers.add_parser("export-tickets", help="Export persisted tickets as CSV.")
    _add_database_url(export_tickets)
    export_tickets.add_argument("--unplaced", action="store_true")
    export_tickets.add_argument("--approved-only", action="store_true")
    export_tickets.set_defaults(func=run_export_tickets)

    place = subparsers.add_parser("place-ticket", help="Mark a persisted ticket as placed.")
    _add_database_url(place)
    place.add_argument("ticket_id", type=int)
    place.add_argument("--actual-odds", type=int, default=None)
    place.add_argument("--actual-stake", type=float, default=None)
    place.add_argument("--notes", default=None)
    place.add_argument("--bet-class", choices=["STANDARD", "BOOSTED_ODDS", "FREE_BET", "RISK_FREE"], default="STANDARD")
    place.add_argument("--boost-terms-json", default=None)
    place.set_defaults(func=run_place_ticket)

    settle = subparsers.add_parser("settle-bet", help="Record settlement for a placed bet.")
    _add_database_url(settle)
    settle.add_argument("bet_id", type=int)
    settle.add_argument("result", choices=["win", "loss", "push", "void", "dead_heat"])
    settle.add_argument("--notes", default=None)
    settle.set_defaults(func=run_settle_bet)

    clv = subparsers.add_parser("record-clv", help="Record closing-line value for a placed bet.")
    _add_database_url(clv)
    clv.add_argument("bet_id", type=int)
    clv.add_argument("--closing-odds", type=int, required=True)
    clv.set_defaults(func=run_record_clv)

    attribution = subparsers.add_parser("record-attribution", help="Record P&L attribution for a settled bet.")
    _add_database_url(attribution)
    attribution.add_argument("bet_id", type=int)
    attribution.add_argument("--flat-stake", type=float, default=None)
    attribution.set_defaults(func=run_record_attribution)

    report = subparsers.add_parser("report", help="Print persisted paper-trading summary metrics.")
    _add_database_url(report)
    report.add_argument("--format", choices=["text", "json"], default="text")
    report.add_argument("--output", type=Path, help="Optional path to write the rendered report.")
    report.add_argument("--code-version", default=None)
    report.set_defaults(func=run_report)

    readiness = subparsers.add_parser(
        "readiness",
        help="Check whether the paper DB is ready for Phase 3 gate review.",
    )
    _add_database_url(readiness)
    readiness.add_argument("--required-tournaments", type=int, default=4)
    readiness.add_argument("--required-settled-bets", type=int, default=60)
    readiness.add_argument("--format", choices=["text", "json"], default="text")
    readiness.add_argument("--output", type=Path, help="Optional path to write the rendered result.")
    readiness.add_argument("--code-version", default=None)
    readiness.set_defaults(func=run_readiness)

    evidence = subparsers.add_parser(
        "evidence-check",
        help="Check that Phase 3 gate evidence is operator-entered paper data.",
    )
    _add_database_url(evidence)
    evidence.add_argument("--required-tournaments", type=int, default=4)
    evidence.add_argument("--required-settled-bets", type=int, default=60)
    evidence.add_argument("--format", choices=["text", "json"], default="text")
    evidence.add_argument("--output", type=Path, help="Optional path to write the rendered result.")
    evidence.add_argument("--code-version", default=None)
    evidence.set_defaults(func=run_evidence_check)

    open_actions = subparsers.add_parser("open-actions", help="Show unresolved paper-trading actions.")
    _add_database_url(open_actions)
    open_actions.set_defaults(func=run_open_actions)

    parser.set_defaults(func=run_smoke)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
