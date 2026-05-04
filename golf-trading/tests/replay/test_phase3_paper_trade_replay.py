from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.execution.candidates import build_ticket_from_candidate
from src.execution.persistence import (
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.monitoring.attribution import record_attribution_for_bet_row
from src.monitoring.reports import build_stored_paper_trade_report, render_stored_report
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Base, BetCandidate, Player, Tournament

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "replay" / "phase3_paper_trade.json"


def test_phase3_paper_trade_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "candidates": 1,
        "tickets": 1,
        "placed_bets": 1,
        "outcomes": 1,
        "clv_snapshots": 1,
        "bet_attribution": 1,
    }
    assert first["ticket"]["approved"] is True
    assert first["ticket"]["proposed_stake"] == 137.5
    assert first["outcome"]["profit_loss"] == 95.24
    assert first["report"]["ticket_count"] == 1
    assert first["report"]["positive_clv_rate"] == 1.0
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "candidate_inputs_hash": manifest["candidate"]["inputs_hash"],
        "ticket_inputs_hash": manifest["ticket"]["inputs_hash"],
        "placed_inputs_hash": manifest["placed"]["inputs_hash"],
        "outcome_inputs_hash": manifest["outcome"]["inputs_hash"],
        "clv_inputs_hash": manifest["clv"]["inputs_hash"],
        "attribution_inputs_hash": manifest["attribution"]["inputs_hash"],
        "rendered_report_hash": manifest["rendered_report_hash"],
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

        player_by_dg_id = {player.datagolf_player_id: player for player in players}
        primary = player_by_dg_id[fixture["candidate"]["side"]]
        opponent = next(player for player in players if player is not primary)
        candidate = _candidate_from_fixture(fixture, tournament, primary, opponent)
        session.add(candidate)
        session.flush()

        ticket_draft = build_ticket_from_candidate(
            candidate,
            primary,
            opponent_player=opponent,
            total_bankroll=fixture["bankroll"]["total"],
            reserve_fraction=fixture["bankroll"]["reserve_fraction"],
            active_core_fraction=fixture["bankroll"]["active_core_fraction"],
            convex_fraction=fixture["bankroll"]["convex_fraction"],
            kelly_multiplier=fixture["sizing"]["kelly_multiplier"],
            convex_unit_fraction=fixture["sizing"]["convex_unit_fraction"],
            min_bet_dollars=fixture["sizing"]["min_bet_dollars"],
            max_bet_fraction=fixture["sizing"]["max_bet_fraction"],
            min_edge_core=fixture["edge"]["min_edge_core"],
            min_edge_convex=fixture["edge"]["min_edge_convex"],
            created_at=_dt(fixture["created_at"]),
            code_version=fixture["code_version"],
        )
        ticket = persist_ticket(session, ticket_draft, candidate_id=candidate.candidate_id)

        placed = place_ticket_row(
            session,
            ticket,
            candidate,
            actual_american_odds=fixture["placement"]["actual_american_odds"],
            actual_stake=fixture["placement"]["actual_stake"],
            placed_at=_dt(fixture["placed_at"]),
            notes=fixture["placement"]["notes"],
            placement_method=fixture["placement"]["placement_method"],
            code_version=fixture["code_version"],
        )
        outcome = settle_bet_row(
            session,
            placed,
            result=fixture["settlement"]["result"],
            settled_at=_dt(fixture["settled_at"]),
            notes=fixture["settlement"]["notes"],
            code_version=fixture["code_version"],
        )
        attribution = record_attribution_for_bet_row(
            session,
            placed,
            ticket,
            candidate,
            outcome,
            flat_stake=fixture["attribution"]["flat_stake"],
            created_at=_dt(fixture["attribution_created_at"]),
            code_version=fixture["code_version"],
        )
        clv = record_clv_for_bet_row(
            session,
            placed,
            ticket,
            candidate,
            closing_american_odds=fixture["clv"]["closing_american_odds"],
            captured_at=_dt(fixture["clv_captured_at"]),
            code_version=fixture["code_version"],
        )
        report = build_stored_paper_trade_report(session)
        rendered_report = render_stored_report(report)

        manifest = {
            "scenario": fixture["scenario"],
            "shape": {
                "candidates": 1,
                "tickets": 1,
                "placed_bets": 1,
                "outcomes": 1,
                "clv_snapshots": 1,
                "bet_attribution": 1,
            },
            "candidate": {
                "candidate_id": candidate.candidate_id,
                "inputs_hash": candidate.inputs_hash,
            },
            "ticket": {
                "ticket_id": ticket.ticket_id,
                "approved": ticket.approved,
                "proposed_stake": ticket.proposed_stake,
                "inputs_hash": ticket.inputs_hash,
            },
            "placed": {
                "bet_id": placed.bet_id,
                "actual_american_odds": placed.actual_american_odds,
                "actual_stake": placed.actual_stake,
                "inputs_hash": placed.inputs_hash,
            },
            "outcome": {
                "outcome_id": outcome.outcome_id,
                "result": outcome.result,
                "profit_loss": outcome.profit_loss,
                "inputs_hash": outcome.inputs_hash,
            },
            "clv": {
                "clv_id": clv.clv_id,
                "clv_raw": clv.clv_raw,
                "clv_model": clv.clv_model,
                "inputs_hash": clv.inputs_hash,
            },
            "attribution": {
                "attribution_id": attribution.attribution_id,
                "model_alpha": attribution.model_alpha,
                "execution_drift": attribution.execution_drift,
                "sizing_alpha": attribution.sizing_alpha,
                "variance": attribution.variance,
                "inputs_hash": attribution.inputs_hash,
            },
            "report": asdict(report),
            "rendered_report_hash": stable_hash(rendered_report),
        }
        return {**manifest, "manifest_hash": stable_hash(manifest)}
    finally:
        session.close()
        engine.dispose()


def _candidate_from_fixture(
    fixture: dict[str, Any],
    tournament: Tournament,
    primary: Player,
    opponent: Player,
) -> BetCandidate:
    payload = fixture["candidate"]
    inputs_hash = artifact_hash(
        artifact_type="bet_candidate",
        inputs={
            "scenario": fixture["scenario"],
            "tournament": fixture["tournament"],
            "players": fixture["players"],
            "candidate": payload,
        },
        config={"edge": fixture["edge"]},
        code_version=fixture["code_version"],
    )
    return BetCandidate(
        tournament_id=tournament.tournament_id,
        market_type=payload["market_type"],
        side=payload["side"],
        player_id_1=primary.player_id,
        player_id_2=opponent.player_id,
        book=payload["book"],
        fair_prob=payload["fair_prob"],
        book_prob=payload["book_prob"],
        book_american_odds=payload["book_american_odds"],
        edge_pct=payload["edge_pct"],
        confidence_score=payload["confidence_score"],
        staleness_flag=payload["staleness_flag"],
        inputs_hash=inputs_hash,
        created_at=_dt(fixture["created_at"]),
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
