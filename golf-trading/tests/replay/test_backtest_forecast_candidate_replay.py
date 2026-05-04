from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backtest.leakage_guard import ModelVersionPublication
from src.backtest.replay import (
    BacktestBookLine,
    BacktestSettlementInput,
    replay_forecast_book_lines,
    settle_backtest_replay,
)
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Base, Forecast, Player, RawSnapshot, Tournament

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "backtest_forecast_candidate_replay.json"
)


def test_backtest_forecast_candidate_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "forecasts": 2,
        "fair_prices": 2,
        "edges": 2,
        "candidates": 2,
        "tickets": 2,
        "settled": 1,
        "clv": 1,
    }
    assert first["edges"]["dg_scottie_scheffler"]["edge"] == fixture["expected"][
        "scheffler_edge"
    ]
    assert first["tickets"]["dg_rory_mcilroy"]["rejection_reason"] == fixture["expected"][
        "rory_rejection_reason"
    ]
    assert first["ticket_summary"] == {
        "approved": fixture["expected"]["approved_ticket_count"],
        "rejected": fixture["expected"]["rejected_ticket_count"],
    }
    assert first["report"]["settled_count"] == fixture["expected"]["settled_count"]
    assert first["report"]["clv_count"] == fixture["expected"]["clv_count"]
    assert first["report"]["strategy_profit_loss"] == fixture["expected"]["strategy_profit_loss"]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "forecast_batch_hash": manifest["forecast_batch_hash"],
        "candidate_batch_hash": manifest["candidate_batch_hash"],
        "ticket_batch_hash": manifest["ticket_batch_hash"],
        "settlement_batch_hash": manifest["settlement_batch_hash"],
        "report_hash": manifest["report_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        tournament = Tournament(**fixture["tournament"])
        players = [Player(**player) for player in fixture["players"]]
        session.add_all([tournament, *players])
        session.flush()
        snapshot = _snapshot_from_fixture(fixture, tournament.tournament_id)
        session.add(snapshot)
        session.flush()
        forecast_rows = _forecast_rows_from_fixture(fixture, snapshot, tournament, players)
        session.add_all(forecast_rows)
        session.flush()

        result = replay_forecast_book_lines(
            session,
            tournament_id=tournament.tournament_id,
            decision_time=_dt(fixture["decision_time"]),
            model_versions=[
                ModelVersionPublication(
                    dg_model_version=version["dg_model_version"],
                    published_at=_dt(version["published_at"]),
                )
                for version in fixture["model_versions"]
            ],
            book_lines=[BacktestBookLine(**line) for line in fixture["book_lines"]],
            total_bankroll=fixture["bankroll"]["total"],
            reserve_fraction=fixture["bankroll"]["reserve_fraction"],
            active_core_fraction=fixture["bankroll"]["active_core_fraction"],
            convex_fraction=fixture["bankroll"]["convex_fraction"],
            kelly_multiplier=fixture["sizing"]["kelly_multiplier"],
            convex_unit_fraction=fixture["sizing"]["convex_unit_fraction"],
            min_bet_dollars=fixture["sizing"]["min_bet_dollars"],
            max_bet_fraction=fixture["sizing"]["max_bet_fraction"],
            min_edge_core=fixture["edge_config"]["min_edge_core"],
            min_edge_convex=fixture["edge_config"]["min_edge_convex"],
            posterior_kelly_enabled=fixture["sizing"]["posterior_kelly_enabled"],
            fdr_enabled=fixture["edge_config"]["fdr_enabled"],
            fdr_q_core=fixture["edge_config"]["fdr_q_core"],
            fdr_q_convex=fixture["edge_config"]["fdr_q_convex"],
            vig_method=fixture["edge_config"]["vig_method"],
            code_version=fixture["code_version"],
        )
        settlement = settle_backtest_replay(
            session,
            result,
            [BacktestSettlementInput(**row) for row in fixture["settlements"]],
            placed_at=_dt(fixture["decision_time"]),
            settled_at=_dt(fixture["settled_at"]),
            code_version=fixture["code_version"],
        )

        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in result.candidates
        }
        forecast_payloads = [
            {
                "forecast_id": row.forecast_id,
                "player_id": row.player_id,
                "forecast_type": row.forecast_type,
                "probability": row.probability,
                "dg_model_version": row.dg_model_version,
                "inputs_hash": row.inputs_hash,
            }
            for row in forecast_rows
        ]
        edge_payloads = {
            edge.datagolf_id: {
                "edge": round(edge.edge, 6),
                "fair_prob": edge.fair_prob,
                "book_no_vig_prob": round(edge.book_no_vig_prob, 6),
            }
            for edge in result.edges
        }
        candidate_payloads = {
            candidate.side: {
                "candidate_id": candidate.candidate_id,
                "edge_pct": round(candidate.edge_pct, 6),
                "inputs_hash": candidate.inputs_hash,
            }
            for candidate in result.candidates
        }
        ticket_payloads = {
            candidate_by_id[ticket.candidate_id].side: {
                "ticket_id": ticket.ticket_id,
                "market_type": candidate_by_id[ticket.candidate_id].market_type,
                "book_id": candidate_by_id[ticket.candidate_id].book,
                "approved": ticket.approved,
                "proposed_stake": ticket.proposed_stake,
                "rejection_reason": ticket.rejection_reason,
                "inputs_hash": ticket.inputs_hash,
            }
            for ticket in result.tickets
        }
        settlement_payloads = [
            {
                "bet_id": outcome.bet_id,
                "result": outcome.result,
                "profit_loss_raw": outcome.profit_loss_raw,
                "inputs_hash": outcome.inputs_hash,
            }
            for outcome in settlement.outcomes
        ]
        clv_payloads = [
            {
                "bet_id": clv.bet_id,
                "closing_american_odds": clv.closing_american_odds,
                "clv_raw": round(clv.clv_raw, 6),
                "clv_model": round(clv.clv_model, 6),
                "inputs_hash": clv.inputs_hash,
            }
            for clv in settlement.clv_snapshots
        ]
        report_payload = {
            "placed_count": settlement.report.placed_count,
            "settled_count": settlement.report.settled_count,
            "clv_count": settlement.report.clv_count,
            "strategy_profit_loss": settlement.report.strategy_profit_loss,
            "strategy_roi": settlement.report.strategy_roi,
            "average_clv_raw": round(settlement.report.average_clv_raw, 6),
        }
        manifest = {
            "artifact_type": "backtest_replay_manifest",
            "scenario": fixture["scenario"],
            "shape": {
                "forecasts": len(forecast_rows),
                "fair_prices": len(result.fair_prices),
                "edges": len(result.edges),
                "candidates": len(result.candidates),
                "tickets": len(result.tickets),
                "settled": len(settlement.outcomes),
                "clv": len(settlement.clv_snapshots),
            },
            "forecasts": forecast_payloads,
            "edges": edge_payloads,
            "candidates": candidate_payloads,
            "tickets": ticket_payloads,
            "settlements": settlement_payloads,
            "clv": clv_payloads,
            "report": report_payload,
            "ticket_summary": {
                "approved": sum(1 for ticket in result.tickets if ticket.approved),
                "rejected": sum(1 for ticket in result.tickets if not ticket.approved),
            },
            "forecast_batch_hash": stable_hash(forecast_payloads),
            "candidate_batch_hash": stable_hash(candidate_payloads),
            "ticket_batch_hash": stable_hash(ticket_payloads),
            "settlement_batch_hash": stable_hash(
                {
                    "outcomes": settlement_payloads,
                    "clv": clv_payloads,
                }
            ),
            "report_hash": stable_hash(report_payload),
        }
        return {**manifest, "manifest_hash": stable_hash(manifest)}
    finally:
        session.close()
        engine.dispose()


def _snapshot_from_fixture(fixture: dict[str, Any], tournament_id: int) -> RawSnapshot:
    payload = fixture["snapshot"]
    return RawSnapshot(
        source=payload["source"],
        endpoint=payload["endpoint"],
        tournament_id=tournament_id,
        fetched_at=_dt(fixture["captured_at"]),
        response_body="{}",
        dg_model_version=payload["dg_model_version"],
        inputs_hash=artifact_hash(
            artifact_type="backtest_raw_snapshot",
            inputs=payload,
            config=None,
            code_version=fixture["code_version"],
        ),
    )


def _forecast_rows_from_fixture(
    fixture: dict[str, Any],
    snapshot: RawSnapshot,
    tournament: Tournament,
    players: list[Player],
) -> list[Forecast]:
    player_by_dg_id = {player.datagolf_player_id: player for player in players}
    rows = []
    for payload in fixture["forecasts"]:
        player = player_by_dg_id[payload["datagolf_id"]]
        rows.append(
            Forecast(
                snapshot_id=snapshot.snapshot_id,
                tournament_id=tournament.tournament_id,
                player_id=player.player_id,
                forecast_type=payload["forecast_type"],
                probability=payload["probability"],
                datagolf_skill_rating=payload["datagolf_skill_rating"],
                dg_model_version=snapshot.dg_model_version,
                captured_at=snapshot.fetched_at,
                inputs_hash=artifact_hash(
                    artifact_type="backtest_forecast",
                    inputs=payload,
                    config=None,
                    code_version=fixture["code_version"],
                ),
            )
        )
    return rows


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
