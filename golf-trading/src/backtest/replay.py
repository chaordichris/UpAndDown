"""Replay historical DataGolf forecasts through the candidate/ticket path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from src.backtest.leakage_guard import (
    ModelVersionPublication,
    assert_forecasts_backtest_safe,
    forecast_record_from_orm,
)
from src.execution.candidates import build_ticket_from_candidate
from src.execution.persistence import (
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.monitoring.reports import StoredPaperTradeReport, build_stored_paper_trade_report
from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.pricing.fair_price import METHOD_DATAGOLF_FORECAST, FairPriceResult
from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import EdgeResult, compute_edge
from src.storage.models import (
    BetCandidate,
    BetOutcome,
    BetTicket,
    CLVSnapshot,
    Forecast,
    PlacedBet,
    Player,
)

_FORECAST_MARKET_TYPES = {
    "win": "outright_win",
    "top_5": "top_5",
    "top_10": "top_10",
    "top_20": "top_20",
    "make_cut": "make_cut",
}


@dataclass(frozen=True)
class BacktestBookLine:
    """Historical book line for one forecast-backed player market."""

    datagolf_id: str
    market_type: str
    book_id: str
    american_odds: int


@dataclass(frozen=True)
class BacktestReplayResult:
    """Rows created by one leakage-checked replay pass."""

    fair_prices: list[FairPriceResult]
    edges: list[EdgeResult]
    candidates: list[BetCandidate]
    tickets: list[BetTicket]


@dataclass(frozen=True)
class BacktestSettlementInput:
    """Historical outcome and closing line for one replayed side."""

    datagolf_id: str
    market_type: str
    book_id: str
    result: str
    closing_american_odds: int | None = None
    actual_american_odds: int | None = None
    actual_stake: float | None = None


@dataclass(frozen=True)
class BacktestSettlementResult:
    """Settlement artifacts and stored report for one replay pass."""

    placed_bets: list[PlacedBet]
    outcomes: list[BetOutcome]
    clv_snapshots: list[CLVSnapshot]
    report: StoredPaperTradeReport


def replay_forecast_book_lines(
    session: Session,
    *,
    tournament_id: int,
    decision_time: datetime,
    model_versions: list[ModelVersionPublication],
    book_lines: list[BacktestBookLine],
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
    fdr_q_core: float = 0.20,
    fdr_q_convex: float = 0.10,
    vig_method: str = "multiplicative",
    code_version: str | None = None,
) -> BacktestReplayResult:
    """Replay historical book lines against persisted DataGolf forecasts.

    This is intentionally a narrow WS-7 spine: persisted DataGolf probabilities
    are used directly as fair prices, then the normal edge, candidate, and
    paper-ticket modules do the rest.
    """
    if not book_lines:
        return BacktestReplayResult(fair_prices=[], edges=[], candidates=[], tickets=[])

    forecast_rows = _forecast_rows_for_lines(
        session,
        tournament_id=tournament_id,
        book_lines=book_lines,
    )
    assert_forecasts_backtest_safe(
        [forecast_record_from_orm(row) for row in forecast_rows],
        decision_time=decision_time,
        model_versions=model_versions,
    )

    fair_prices = _fair_prices_for_lines(
        book_lines=book_lines,
        forecast_by_key=_forecast_by_key(forecast_rows),
        as_of=decision_time,
    )
    edges = _edges_for_lines(
        fair_prices=fair_prices,
        book_lines=book_lines,
        min_edge_core=min_edge_core,
        min_edge_convex=min_edge_convex,
        vig_method=vig_method,
    )
    candidates = build_bet_candidates_from_edges(
        edges,
        tournament_id=tournament_id,
        player_id_by_datagolf_id=_player_id_by_datagolf_id(session),
        fdr_enabled=fdr_enabled,
        fdr_q_core=fdr_q_core,
        fdr_q_convex=fdr_q_convex,
        created_at=decision_time,
        code_version=code_version,
    )
    session.add_all(candidates)
    session.flush()
    tickets = [
        persist_ticket(
            session,
            build_ticket_from_candidate(
                candidate,
                _require_player(session, candidate.player_id_1),
                opponent_player=(
                    _require_player(session, candidate.player_id_2)
                    if candidate.player_id_2 is not None
                    else None
                ),
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
                created_at=decision_time,
            ),
            candidate_id=candidate.candidate_id,
        )
        for candidate in candidates
    ]
    return BacktestReplayResult(
        fair_prices=fair_prices,
        edges=edges,
        candidates=candidates,
        tickets=tickets,
    )


def settle_backtest_replay(
    session: Session,
    replay: BacktestReplayResult,
    settlements: list[BacktestSettlementInput],
    *,
    placed_at: datetime,
    settled_at: datetime,
    code_version: str | None = None,
) -> BacktestSettlementResult:
    """Place and settle approved replay tickets using historical outcomes."""
    settlement_by_key = {_settlement_key(settlement): settlement for settlement in settlements}
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in replay.candidates
    }

    placed_bets: list[PlacedBet] = []
    outcomes: list[BetOutcome] = []
    clv_snapshots: list[CLVSnapshot] = []
    for ticket in replay.tickets:
        if not ticket.approved:
            continue
        candidate = candidates_by_id[ticket.candidate_id]
        settlement = settlement_by_key.get(_candidate_key(candidate))
        if settlement is None:
            raise ValueError(
                "Missing settlement input for approved ticket "
                f"side={candidate.side!r} market_type={candidate.market_type!r} "
                f"book_id={candidate.book!r}."
            )

        placed_bet = place_ticket_row(
            session,
            ticket,
            candidate,
            actual_american_odds=settlement.actual_american_odds,
            actual_stake=settlement.actual_stake,
            placed_at=placed_at,
            placement_method="backtest",
            code_version=code_version,
        )
        outcome = settle_bet_row(
            session,
            placed_bet,
            result=settlement.result,
            settled_at=settled_at,
            code_version=code_version,
        )
        placed_bets.append(placed_bet)
        outcomes.append(outcome)

        if settlement.closing_american_odds is not None:
            clv_snapshots.append(
                record_clv_for_bet_row(
                    session,
                    placed_bet,
                    ticket,
                    candidate,
                    closing_american_odds=settlement.closing_american_odds,
                    captured_at=settled_at,
                    code_version=code_version,
                )
            )

    return BacktestSettlementResult(
        placed_bets=placed_bets,
        outcomes=outcomes,
        clv_snapshots=clv_snapshots,
        report=build_stored_paper_trade_report(session),
    )


def _settlement_key(settlement: BacktestSettlementInput) -> tuple[str, str, str]:
    return (settlement.datagolf_id, settlement.market_type, settlement.book_id)


def _candidate_key(candidate: BetCandidate) -> tuple[str, str, str]:
    return (candidate.side, candidate.market_type, candidate.book)


def _forecast_rows_for_lines(
    session: Session,
    *,
    tournament_id: int,
    book_lines: list[BacktestBookLine],
) -> list[Forecast]:
    needed = [
        (line.datagolf_id, _forecast_type_for_market(line.market_type))
        for line in book_lines
    ]
    player_ids = {
        player.datagolf_player_id: player.player_id
        for player in session.query(Player).all()
        if player.datagolf_player_id is not None
    }
    rows = (
        session.query(Forecast)
        .filter(Forecast.tournament_id == tournament_id)
        .order_by(Forecast.forecast_id)
        .all()
    )
    rows_by_key = {
        (datagolf_id, row.forecast_type): row
        for row in rows
        for datagolf_id, player_id in player_ids.items()
        if row.player_id == player_id
    }
    missing = [key for key in needed if key not in rows_by_key]
    if missing:
        raise ValueError(f"Missing forecast rows for backtest lines: {missing!r}.")
    return [rows_by_key[key] for key in needed]


def _fair_prices_for_lines(
    *,
    book_lines: list[BacktestBookLine],
    forecast_by_key: dict[tuple[str, str], Forecast],
    as_of: datetime,
) -> list[FairPriceResult]:
    return [
        FairPriceResult(
            market_type=line.market_type,
            datagolf_id=line.datagolf_id,
            opponent_id=None,
            fair_prob=forecast_by_key[
                (line.datagolf_id, _forecast_type_for_market(line.market_type))
            ].probability,
            method=METHOD_DATAGOLF_FORECAST,
            as_of=as_of,
        )
        for line in book_lines
    ]


def _edges_for_lines(
    *,
    fair_prices: list[FairPriceResult],
    book_lines: list[BacktestBookLine],
    min_edge_core: float,
    min_edge_convex: float,
    vig_method: str,
) -> list[EdgeResult]:
    implied_probs_by_market: dict[tuple[str, str], list[float]] = {}
    for line in book_lines:
        implied_probs_by_market.setdefault((line.book_id, line.market_type), []).append(
            decimal_to_implied(american_to_decimal(line.american_odds))
        )

    return [
        compute_edge(
            fair=fair,
            book_american_odds=line.american_odds,
            market_implied_probs=implied_probs_by_market[(line.book_id, line.market_type)],
            book_id=line.book_id,
            min_edge_core=min_edge_core,
            min_edge_convex=min_edge_convex,
            vig_method=vig_method,
        )
        for fair, line in zip(fair_prices, book_lines, strict=True)
    ]


def _forecast_by_key(forecasts: list[Forecast]) -> dict[tuple[str, str], Forecast]:
    return {
        (forecast.player.datagolf_player_id, forecast.forecast_type): forecast
        for forecast in forecasts
        if forecast.player.datagolf_player_id is not None
    }


def _player_id_by_datagolf_id(session: Session) -> dict[str, int]:
    return {
        player.datagolf_player_id: player.player_id
        for player in session.query(Player).all()
        if player.datagolf_player_id is not None
    }


def _require_player(session: Session, player_id: int) -> Player:
    player = session.get(Player, player_id)
    if player is None:
        raise ValueError(f"Missing player row {player_id}.")
    return player


def _forecast_type_for_market(market_type: str) -> str:
    for forecast_type, mapped_market_type in _FORECAST_MARKET_TYPES.items():
        if market_type == mapped_market_type:
            return forecast_type
    raise ValueError(f"Unsupported forecast-backed market_type {market_type!r}.")
