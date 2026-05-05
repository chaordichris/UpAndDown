from __future__ import annotations

from datetime import UTC, datetime

from scripts.operator_console import _handle_post, build_dashboard_html, make_handler
from src.execution.persistence import persist_ticket
from src.execution.tickets import generate_ticket
from src.risk.edge import EdgeResult
from src.risk.sizing import size_core_bet
from src.storage.db import get_session, init_db
from src.storage.models import BetCandidate, PlacedBet, Player, Tournament

NOW = datetime(2026, 5, 5, tzinfo=UTC)


def test_operator_console_renders_empty_dashboard(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"

    rendered = build_dashboard_html(database_url)

    assert "UpAndDown Operator Console" in rendered
    assert "Review State" in rendered
    assert "Candidates" in rendered
    assert "Tickets" in rendered
    assert "Placed Bets" in rendered
    assert "No rows." in rendered


def test_operator_console_place_ticket_action(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"
    init_db(database_url)
    with get_session(database_url) as session:
        candidate = _candidate(session)
        ticket = persist_ticket(
            session,
            _ticket(candidate),
            candidate_id=candidate.candidate_id,
        )
        ticket_id = ticket.ticket_id

    message = _handle_post(
        "/place-ticket",
        {
            "ticket_id": [str(ticket_id)],
            "actual_odds": ["-105"],
            "actual_stake": ["50.00"],
            "bet_class": ["STANDARD"],
            "notes": ["operator-entered paper placement"],
        },
        database_url,
    )

    with get_session(database_url) as session:
        placed = session.query(PlacedBet).one()
        bet_id = placed.bet_id
        actual_american_odds = placed.actual_american_odds
        actual_stake = placed.actual_stake
        notes = placed.notes

    assert message == f"Placed ticket {ticket_id} as bet {bet_id}."
    assert actual_american_odds == -105
    assert actual_stake == 50.0
    assert notes == "operator-entered paper placement"


def test_operator_console_handler_factory() -> None:
    handler = make_handler("sqlite:///./data/db/test.db")

    assert handler.__name__ == "OperatorConsoleHandler"


def _candidate(session) -> BetCandidate:
    tournament = Tournament(name="This Week Open", tour="pga")
    player = Player(datagolf_player_id="dg_player", name_canonical="Player One")
    opponent = Player(datagolf_player_id="dg_opponent", name_canonical="Player Two")
    session.add_all([tournament, player, opponent])
    session.flush()

    candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="matchup_2ball",
        side=player.datagolf_player_id,
        player_id_1=player.player_id,
        player_id_2=opponent.player_id,
        book="draftkings",
        fair_prob=0.56,
        book_prob=0.51,
        book_american_odds=-110,
        edge_pct=0.05,
        confidence_score=1.0,
        staleness_flag=False,
        inputs_hash="operator-console-candidate",
        created_at=NOW,
    )
    session.add(candidate)
    session.flush()
    return candidate


def _ticket(candidate: BetCandidate):
    edge = EdgeResult(
        datagolf_id=candidate.side,
        opponent_id="dg_opponent",
        market_type=candidate.market_type,
        book_id=candidate.book,
        fair_prob=candidate.fair_prob,
        book_no_vig_prob=candidate.book_prob,
        edge=candidate.edge_pct,
        sleeve="core",
        passes_threshold=True,
        book_american_odds=candidate.book_american_odds,
    )
    sizing = size_core_bet(
        edge=edge,
        active_bankroll=10_000,
        total_bankroll=25_000,
        kelly_multiplier=0.25,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
    )
    return generate_ticket(edge, sizing, tournament_id="this_week_open", created_at=NOW)
