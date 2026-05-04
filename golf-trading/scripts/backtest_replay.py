"""Run one fixture-backed WS-7 backtest replay into an event database."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.backtest.leakage_guard import ModelVersionPublication
from src.backtest.replay import (
    BacktestBookLine,
    BacktestSettlementInput,
    replay_forecast_book_lines,
    settle_backtest_replay,
)
from src.storage.db import get_session, init_db
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import (
    BetCandidate,
    BetOutcome,
    BetTicket,
    CLVSnapshot,
    Forecast,
    PlacedBet,
    Player,
    RawSnapshot,
    Tournament,
)


def load_fixture(path: Path) -> dict[str, Any]:
    """Load one JSON backtest replay fixture."""
    with path.open() as file:
        return json.load(file)


def run_fixture_replay(
    fixture: dict[str, Any],
    *,
    database_url: str,
) -> dict[str, Any]:
    """Seed one fixture, run the leakage-checked replay, and return a manifest."""
    init_db(database_url)
    with get_session(database_url) as session:
        _assert_empty_event_db(session)
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

        replay = replay_forecast_book_lines(
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
            replay,
            [BacktestSettlementInput(**row) for row in fixture["settlements"]],
            placed_at=_dt(fixture["decision_time"]),
            settled_at=_dt(fixture["settled_at"]),
            code_version=fixture["code_version"],
        )
        return build_replay_manifest(
            fixture=fixture,
            forecast_rows=forecast_rows,
            replay=replay,
            settlement=settlement,
        )


def build_replay_manifest(
    *,
    fixture: dict[str, Any],
    forecast_rows: list[Forecast],
    replay: Any,
    settlement: Any,
) -> dict[str, Any]:
    """Build the stable replay manifest used by WS-7 contracts."""
    candidate_by_id = {
        candidate.candidate_id: candidate
        for candidate in replay.candidates
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
    edge_payloads = [
        {
            "label": _market_label(edge.datagolf_id, edge.market_type, edge.book_id),
            "datagolf_id": edge.datagolf_id,
            "market_type": edge.market_type,
            "book_id": edge.book_id,
            "edge": round(edge.edge, 6),
            "fair_prob": edge.fair_prob,
            "book_no_vig_prob": round(edge.book_no_vig_prob, 6),
        }
        for edge in replay.edges
    ]
    candidate_payloads = [
        {
            "label": _market_label(candidate.side, candidate.market_type, candidate.book),
            "side": candidate.side,
            "candidate_id": candidate.candidate_id,
            "market_type": candidate.market_type,
            "book_id": candidate.book,
            "edge_pct": round(candidate.edge_pct, 6),
            "inputs_hash": candidate.inputs_hash,
        }
        for candidate in replay.candidates
    ]
    ticket_payloads = [
        {
            "label": _market_label(
                candidate_by_id[ticket.candidate_id].side,
                candidate_by_id[ticket.candidate_id].market_type,
                candidate_by_id[ticket.candidate_id].book,
            ),
            "side": candidate_by_id[ticket.candidate_id].side,
            "ticket_id": ticket.ticket_id,
            "market_type": candidate_by_id[ticket.candidate_id].market_type,
            "book_id": candidate_by_id[ticket.candidate_id].book,
            "approved": ticket.approved,
            "proposed_stake": ticket.proposed_stake,
            "rejection_reason": ticket.rejection_reason,
            "inputs_hash": ticket.inputs_hash,
        }
        for ticket in replay.tickets
    ]
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
        "average_clv_raw": (
            None
            if settlement.report.average_clv_raw is None
            else round(settlement.report.average_clv_raw, 6)
        ),
    }
    manifest = {
        "artifact_type": "backtest_replay_manifest",
        "scenario": fixture["scenario"],
        "shape": {
            "forecasts": len(forecast_rows),
            "fair_prices": len(replay.fair_prices),
            "edges": len(replay.edges),
            "candidates": len(replay.candidates),
            "tickets": len(replay.tickets),
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
            "approved": sum(1 for ticket in replay.tickets if ticket.approved),
            "rejected": sum(1 for ticket in replay.tickets if not ticket.approved),
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


def render_replay_manifest_json(manifest: dict[str, Any]) -> str:
    """Render a replay manifest as stable JSON."""
    return json.dumps(manifest, sort_keys=True, indent=2)


def write_output(path: Path | None, content: str) -> None:
    """Write rendered output when an operator requests an artifact file."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _assert_empty_event_db(session: Any) -> None:
    populated_tables = [
        model.__tablename__
        for model in (
            Tournament,
            Player,
            RawSnapshot,
            Forecast,
            BetCandidate,
            BetTicket,
            PlacedBet,
            BetOutcome,
            CLVSnapshot,
        )
        if session.query(model).first() is not None
    ]
    if populated_tables:
        raise ValueError(
            "Backtest replay requires an empty event database; found rows in "
            f"{', '.join(populated_tables)}."
        )


def _market_label(datagolf_id: str, market_type: str, book_id: str) -> str:
    return f"{book_id}:{market_type}:{datagolf_id}"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one leakage-checked WS-7 backtest replay fixture."
    )
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument("--output", type=Path, help="Optional path to write the replay manifest.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    fixture = load_fixture(args.fixture)
    manifest = run_fixture_replay(fixture, database_url=args.database_url)
    rendered = render_replay_manifest_json(manifest)
    write_output(args.output, rendered)
    print(rendered)


if __name__ == "__main__":
    main()
