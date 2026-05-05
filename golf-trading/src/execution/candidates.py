"""Convert persisted bet candidates into executable paper-trade tickets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.execution.persistence import persist_ticket
from src.execution.tickets import BetTicketDraft, generate_ticket
from src.risk.edge import EdgeResult
from src.risk.sizing import size_convex_bet, size_core_bet
from src.storage.models import BetCandidate, BetTicket, Player

_CONVEX_MARKETS = frozenset({"outright_win"})


def build_ticket_from_candidate(
    candidate: BetCandidate,
    primary_player: Player,
    *,
    book_american_odds: int | None = None,
    total_bankroll: float,
    reserve_fraction: float,
    active_core_fraction: float,
    convex_fraction: float,
    kelly_multiplier: float,
    convex_unit_fraction: float,
    min_bet_dollars: float,
    max_bet_fraction: float,
    min_edge_core: float,
    min_edge_convex: float,
    posterior_kelly_enabled: bool = False,
    fdr_enabled: bool = False,
    opponent_player: Player | None = None,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> BetTicketDraft:
    """Build a sized ticket from a stored candidate row.

    The raw candidate row intentionally stores fair/book probabilities, not the
    original book odds. The operator supplies the current/recommended American
    odds when turning the candidate into a manual paper-trade ticket.
    """
    if total_bankroll <= 0:
        raise ValueError("total_bankroll must be positive.")
    if min(reserve_fraction, active_core_fraction, convex_fraction) < 0:
        raise ValueError("bankroll fractions must be non-negative.")

    resolved_book_odds = book_american_odds or candidate.book_american_odds
    if resolved_book_odds is None:
        raise ValueError("book_american_odds is required when candidate has no stored odds.")

    active_bankroll = total_bankroll * active_core_fraction
    convex_bankroll = total_bankroll * convex_fraction
    sleeve = "convex" if candidate.market_type in _CONVEX_MARKETS else "core"
    threshold = min_edge_convex if sleeve == "convex" else min_edge_core

    edge = EdgeResult(
        datagolf_id=_player_key(primary_player),
        opponent_id=_player_key(opponent_player) if opponent_player is not None else None,
        market_type=candidate.market_type,
        book_id=candidate.book,
        fair_prob=candidate.fair_prob,
        book_no_vig_prob=candidate.book_prob,
        edge=candidate.edge_pct,
        sleeve=sleeve,
        passes_threshold=candidate.edge_pct >= threshold and not candidate.staleness_flag,
        book_american_odds=resolved_book_odds,
        edge_sd=candidate.edge_sd,
        p_value=candidate.p_value,
        passes_fdr=candidate.passes_fdr if fdr_enabled else True,
    )

    if sleeve == "convex":
        sizing = size_convex_bet(
            edge=edge,
            convex_bankroll=convex_bankroll,
            total_bankroll=total_bankroll,
            unit_fraction=convex_unit_fraction,
            min_bet_dollars=min_bet_dollars,
            max_bet_fraction=max_bet_fraction,
        )
    else:
        sizing = size_core_bet(
            edge=edge,
            active_bankroll=active_bankroll,
            total_bankroll=total_bankroll,
            kelly_multiplier=kelly_multiplier,
            min_bet_dollars=min_bet_dollars,
            max_bet_fraction=max_bet_fraction,
            posterior_kelly_enabled=posterior_kelly_enabled,
        )

    return generate_ticket(
        edge,
        sizing,
        tournament_id=str(candidate.tournament_id),
        side=candidate.side,
        sizing_method="posterior_kelly" if posterior_kelly_enabled and sleeve == "core" else None,
        created_at=created_at,
        code_version=code_version,
    )


def ticket_unticketed_candidates(
    session: Session,
    *,
    total_bankroll: float,
    reserve_fraction: float,
    active_core_fraction: float,
    convex_fraction: float,
    kelly_multiplier: float,
    convex_unit_fraction: float,
    min_bet_dollars: float,
    max_bet_fraction: float,
    min_edge_core: float,
    min_edge_convex: float,
    posterior_kelly_enabled: bool = False,
    fdr_enabled: bool = False,
    tournament_id: int | None = None,
    limit: int | None = None,
    created_at: datetime | None = None,
) -> list[BetTicket]:
    """Create tickets for persisted candidates that do not already have one."""
    ticketed_candidate_ids = {
        row.candidate_id for row in session.query(BetTicket.candidate_id).all()
    }
    query = session.query(BetCandidate).order_by(BetCandidate.candidate_id)
    if tournament_id is not None:
        query = query.filter(BetCandidate.tournament_id == tournament_id)

    rows: list[BetTicket] = []
    for candidate in query.all():
        if candidate.candidate_id in ticketed_candidate_ids:
            continue
        if limit is not None and len(rows) >= limit:
            break

        primary_player = session.get(Player, candidate.player_id_1)
        if primary_player is None:
            raise ValueError(f"Candidate {candidate.candidate_id} has unknown primary player.")
        opponent_player = (
            session.get(Player, candidate.player_id_2)
            if candidate.player_id_2 is not None
            else None
        )
        ticket = build_ticket_from_candidate(
            candidate,
            primary_player,
            opponent_player=opponent_player,
            total_bankroll=total_bankroll,
            reserve_fraction=reserve_fraction,
            active_core_fraction=active_core_fraction,
            convex_fraction=convex_fraction,
            kelly_multiplier=kelly_multiplier,
            convex_unit_fraction=convex_unit_fraction,
            min_bet_dollars=min_bet_dollars,
            max_bet_fraction=max_bet_fraction,
            min_edge_core=min_edge_core,
            min_edge_convex=min_edge_convex,
            posterior_kelly_enabled=posterior_kelly_enabled,
            fdr_enabled=fdr_enabled,
            created_at=created_at,
        )
        rows.append(persist_ticket(session, ticket, candidate_id=candidate.candidate_id))

    return rows


def _player_key(player: Player) -> str:
    return player.datagolf_player_id or player.name_canonical
