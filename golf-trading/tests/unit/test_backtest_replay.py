from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backtest.leakage_guard import DataGolfLeakageError, ModelVersionPublication
from src.backtest.replay import (
    BacktestBookLine,
    BacktestSettlementInput,
    replay_forecast_book_lines,
    settle_backtest_replay,
)
from src.storage.models import BetCandidate, Forecast, Player, RawSnapshot, Tournament

DECISION_TIME = datetime(2026, 4, 30, 14, 0, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)


def test_replay_forecast_book_lines_creates_candidates_and_tickets(db_session) -> None:
    tournament, scheffler, rory = _seed_forecasts(db_session)

    result = replay_forecast_book_lines(
        db_session,
        tournament_id=tournament.tournament_id,
        decision_time=DECISION_TIME,
        model_versions=_model_versions(),
        book_lines=[
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=rory.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
        ],
        total_bankroll=25_000.0,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
        vig_method="multiplicative",
        code_version="test",
    )

    assert [fair.datagolf_id for fair in result.fair_prices] == [
        scheffler.datagolf_player_id,
        rory.datagolf_player_id,
    ]
    assert len(result.edges) == 2
    assert len(result.candidates) == 2
    assert len(result.tickets) == 2
    assert result.candidates[0].inputs_hash
    assert result.tickets[0].sizing_method == "fractional_kelly"
    assert any(ticket.approved for ticket in result.tickets)
    assert any(not ticket.approved for ticket in result.tickets)


def test_replay_forecast_book_lines_refuses_leaking_model_version(db_session) -> None:
    tournament, scheffler, _ = _seed_forecasts(
        db_session,
        dg_model_version="dg-2026-05-01",
    )

    with pytest.raises(DataGolfLeakageError, match="before it was published"):
        replay_forecast_book_lines(
            db_session,
            tournament_id=tournament.tournament_id,
            decision_time=DECISION_TIME,
            model_versions=[
                ModelVersionPublication(
                    dg_model_version="dg-2026-05-01",
                    published_at=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
                )
            ],
            book_lines=[
                BacktestBookLine(
                    datagolf_id=scheffler.datagolf_player_id,
                    market_type="make_cut",
                    book_id="draftkings",
                    american_odds=100,
                )
            ],
            total_bankroll=25_000.0,
            reserve_fraction=0.50,
            active_core_fraction=0.40,
            convex_fraction=0.10,
            kelly_multiplier=0.25,
            convex_unit_fraction=0.005,
            min_bet_dollars=5.0,
            max_bet_fraction=0.02,
            min_edge_core=0.03,
            min_edge_convex=0.08,
        )


def test_replay_forecast_book_lines_tickets_only_replay_candidates(db_session) -> None:
    tournament, scheffler, _ = _seed_forecasts(db_session)
    old_candidate = BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type="make_cut",
        side="old_candidate",
        player_id_1=scheffler.player_id,
        book="draftkings",
        fair_prob=0.91,
        book_prob=0.50,
        book_american_odds=100,
        edge_pct=0.41,
        inputs_hash="old-candidate",
    )
    db_session.add(old_candidate)
    db_session.flush()

    result = replay_forecast_book_lines(
        db_session,
        tournament_id=tournament.tournament_id,
        decision_time=DECISION_TIME,
        model_versions=_model_versions(),
        book_lines=[
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            )
        ],
        total_bankroll=25_000.0,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )

    assert len(result.tickets) == 1
    assert result.tickets[0].candidate_id != old_candidate.candidate_id


def test_settle_backtest_replay_records_outcomes_clv_and_report(db_session) -> None:
    tournament, scheffler, rory = _seed_forecasts(db_session)
    replay = replay_forecast_book_lines(
        db_session,
        tournament_id=tournament.tournament_id,
        decision_time=DECISION_TIME,
        model_versions=_model_versions(),
        book_lines=[
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=rory.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
        ],
        total_bankroll=25_000.0,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )

    settlement = settle_backtest_replay(
        db_session,
        replay,
        [
            BacktestSettlementInput(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                result="win",
                closing_american_odds=-120,
            ),
            BacktestSettlementInput(
                datagolf_id=rory.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                result="loss",
                closing_american_odds=110,
            ),
        ],
        placed_at=DECISION_TIME,
        settled_at=datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
        code_version="test",
    )

    assert len(settlement.placed_bets) == 1
    assert len(settlement.outcomes) == 1
    assert len(settlement.clv_snapshots) == 1
    assert settlement.outcomes[0].result == "win"
    assert settlement.report.placed_count == 1
    assert settlement.report.settled_count == 1
    assert settlement.report.clv_count == 1
    assert settlement.report.total_profit_loss > 0


def test_settle_backtest_replay_keys_results_by_player_market_and_book(db_session) -> None:
    tournament, scheffler, rory = _seed_forecasts(db_session)
    replay = replay_forecast_book_lines(
        db_session,
        tournament_id=tournament.tournament_id,
        decision_time=DECISION_TIME,
        model_versions=_model_versions(),
        book_lines=[
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=rory.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="top_20",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=rory.datagolf_player_id,
                market_type="top_20",
                book_id="draftkings",
                american_odds=100,
            ),
        ],
        total_bankroll=25_000.0,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )

    settlement = settle_backtest_replay(
        db_session,
        replay,
        [
            BacktestSettlementInput(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                result="loss",
                closing_american_odds=-120,
            ),
            BacktestSettlementInput(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="top_20",
                book_id="draftkings",
                result="win",
                closing_american_odds=850,
            ),
        ],
        placed_at=DECISION_TIME,
        settled_at=datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
    )

    results_by_bet = {outcome.bet_id: outcome.result for outcome in settlement.outcomes}
    clv_by_bet = {
        clv.bet_id: clv.closing_american_odds for clv in settlement.clv_snapshots
    }

    assert len(settlement.outcomes) == 2
    assert list(results_by_bet.values()) == ["loss", "win"]
    assert list(clv_by_bet.values()) == [-120, 850]


def test_settle_backtest_replay_requires_result_for_approved_ticket(db_session) -> None:
    tournament, scheffler, rory = _seed_forecasts(db_session)
    replay = replay_forecast_book_lines(
        db_session,
        tournament_id=tournament.tournament_id,
        decision_time=DECISION_TIME,
        model_versions=_model_versions(),
        book_lines=[
            BacktestBookLine(
                datagolf_id=scheffler.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
            BacktestBookLine(
                datagolf_id=rory.datagolf_player_id,
                market_type="make_cut",
                book_id="draftkings",
                american_odds=100,
            ),
        ],
        total_bankroll=25_000.0,
        reserve_fraction=0.50,
        active_core_fraction=0.40,
        convex_fraction=0.10,
        kelly_multiplier=0.25,
        convex_unit_fraction=0.005,
        min_bet_dollars=5.0,
        max_bet_fraction=0.02,
        min_edge_core=0.03,
        min_edge_convex=0.08,
    )

    with pytest.raises(ValueError, match="Missing settlement input"):
        settle_backtest_replay(
            db_session,
            replay,
            [],
            placed_at=DECISION_TIME,
            settled_at=datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
        )


def test_replay_forecast_book_lines_requires_forecast_rows(db_session) -> None:
    tournament = Tournament(name="Backtest Replay Open", tour="pga")
    player = Player(datagolf_player_id="dg_missing", name_canonical="Missing Player")
    db_session.add_all([tournament, player])
    db_session.flush()

    with pytest.raises(ValueError, match="Missing forecast rows"):
        replay_forecast_book_lines(
            db_session,
            tournament_id=tournament.tournament_id,
            decision_time=DECISION_TIME,
            model_versions=_model_versions(),
            book_lines=[
                BacktestBookLine(
                    datagolf_id="dg_missing",
                    market_type="make_cut",
                    book_id="draftkings",
                    american_odds=100,
                )
            ],
            total_bankroll=25_000.0,
            reserve_fraction=0.50,
            active_core_fraction=0.40,
            convex_fraction=0.10,
            kelly_multiplier=0.25,
            convex_unit_fraction=0.005,
            min_bet_dollars=5.0,
            max_bet_fraction=0.02,
            min_edge_core=0.03,
            min_edge_convex=0.08,
        )


def _seed_forecasts(
    db_session,
    *,
    dg_model_version: str = "dg-2026-04-01",
) -> tuple[Tournament, Player, Player]:
    tournament = Tournament(name="Backtest Replay Open", tour="pga")
    scheffler = Player(
        datagolf_player_id="dg_scottie_scheffler",
        name_canonical="Scottie Scheffler",
    )
    rory = Player(datagolf_player_id="dg_rory_mcilroy", name_canonical="Rory McIlroy")
    db_session.add_all([tournament, scheffler, rory])
    db_session.flush()
    snapshot = RawSnapshot(
        source="datagolf",
        endpoint="pretournament_predictions",
        tournament_id=tournament.tournament_id,
        fetched_at=CAPTURED_AT,
        response_body="{}",
        dg_model_version=dg_model_version,
        inputs_hash="forecast-snapshot",
    )
    db_session.add(snapshot)
    db_session.flush()
    db_session.add_all(
        [
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=scheffler.player_id,
                forecast_type="win",
                probability=0.14,
                datagolf_skill_rating=2.8,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="scheffler-forecast",
            ),
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=scheffler.player_id,
                forecast_type="make_cut",
                probability=0.91,
                datagolf_skill_rating=2.8,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="scheffler-make-cut-forecast",
            ),
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=scheffler.player_id,
                forecast_type="top_20",
                probability=0.72,
                datagolf_skill_rating=2.8,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="scheffler-top-20-forecast",
            ),
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=rory.player_id,
                forecast_type="win",
                probability=0.04,
                datagolf_skill_rating=2.2,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="rory-forecast",
            ),
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=rory.player_id,
                forecast_type="make_cut",
                probability=0.45,
                datagolf_skill_rating=2.2,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="rory-make-cut-forecast",
            ),
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=rory.player_id,
                forecast_type="top_20",
                probability=0.40,
                datagolf_skill_rating=2.2,
                dg_model_version=dg_model_version,
                captured_at=CAPTURED_AT,
                inputs_hash="rory-top-20-forecast",
            ),
        ]
    )
    db_session.flush()
    return tournament, scheffler, rory


def _model_versions() -> list[ModelVersionPublication]:
    return [
        ModelVersionPublication(
            dg_model_version="dg-2026-04-01",
            published_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        )
    ]
