from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.execution.candidates import ticket_unticketed_candidates
from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import EdgeResult
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Base, Player, Tournament

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "fdr_posterior_ticketing.json"
)


def test_fdr_posterior_ticketing_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "raw_edges": 3,
        "annotated_edges": 3,
        "candidates": 3,
        "tickets": 3,
    }
    assert first["ticket_summary"]["approved"] == fixture["expected"]["approved_ticket_count"]
    assert first["ticket_summary"]["rejected"] == fixture["expected"]["rejected_ticket_count"]
    assert first["tickets"]["dg_strong_edge"]["proposed_stake"] == fixture["expected"][
        "strong_stake"
    ]
    assert first["tickets"]["dg_medium_edge"]["proposed_stake"] == fixture["expected"][
        "medium_stake"
    ]
    assert first["tickets"]["dg_noisy_edge"]["rejection_reason"] == fixture["expected"][
        "noisy_rejection_reason"
    ]
    assert {
        ticket["sizing_method"]
        for ticket in first["tickets"].values()
        if ticket["approved"]
    } == {fixture["expected"]["sizing_method"]}
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "edge_annotation_hash": manifest["edge_annotation_hash"],
        "candidate_batch_hash": manifest["candidate_batch_hash"],
        "ticket_batch_hash": manifest["ticket_batch_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    raw_edges = [_edge_from_fixture(payload) for payload in fixture["edges"]]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        tournament = Tournament(**fixture["tournament"])
        players = [Player(**player) for player in fixture["players"]]
        session.add_all([tournament, *players])
        session.flush()

        player_by_dg_id = {player.datagolf_player_id: player for player in players}
        candidates = build_bet_candidates_from_edges(
            raw_edges,
            tournament_id=tournament.tournament_id,
            player_id_by_datagolf_id={
                datagolf_id: player.player_id
                for datagolf_id, player in player_by_dg_id.items()
            },
            fdr_enabled=fixture["edge_config"]["fdr_enabled"],
            fdr_q_core=fixture["edge_config"]["fdr_q_core"],
            fdr_q_convex=fixture["edge_config"]["fdr_q_convex"],
            created_at=_dt(fixture["created_at"]),
            code_version=fixture["code_version"],
        )
        session.add_all(candidates)
        session.flush()

        ticket_rows = ticket_unticketed_candidates(
            session,
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
            created_at=_dt(fixture["created_at"]),
        )

        edge_payloads = [
            _rounded(
                {
                    "datagolf_id": candidate.side,
                    "edge_sd": candidate.edge_sd,
                    "p_value": candidate.p_value,
                    "passes_fdr": candidate.passes_fdr,
                }
            )
            for candidate in candidates
        ]
        candidate_payloads = {
            candidate.side: {
                "candidate_id": candidate.candidate_id,
                "edge_sd": candidate.edge_sd,
                "p_value": round(candidate.p_value, 6) if candidate.p_value is not None else None,
                "passes_fdr": candidate.passes_fdr,
                "inputs_hash": candidate.inputs_hash,
            }
            for candidate in candidates
        }
        candidate_side_by_id = {
            candidate.candidate_id: candidate.side
            for candidate in candidates
        }
        ticket_payloads = {
            candidate_side_by_id[ticket.candidate_id]: {
                "ticket_id": ticket.ticket_id,
                "approved": ticket.approved,
                "proposed_stake": ticket.proposed_stake,
                "rejection_reason": ticket.rejection_reason,
                "sizing_method": ticket.sizing_method,
                "kelly_fraction_used": round(ticket.kelly_fraction_used, 6),
                "inputs_hash": ticket.inputs_hash,
            }
            for ticket in ticket_rows
        }
        manifest = {
            "scenario": fixture["scenario"],
            "shape": {
                "raw_edges": len(raw_edges),
                "annotated_edges": len(candidates),
                "candidates": len(candidates),
                "tickets": len(ticket_rows),
            },
            "edges": edge_payloads,
            "candidates": candidate_payloads,
            "tickets": ticket_payloads,
            "ticket_summary": {
                "approved": sum(1 for ticket in ticket_rows if ticket.approved),
                "rejected": sum(1 for ticket in ticket_rows if not ticket.approved),
            },
            "edge_annotation_hash": artifact_hash(
                artifact_type="fdr_edge_annotation_batch",
                inputs=edge_payloads,
                config=fixture["edge_config"],
                code_version=fixture["code_version"],
            ),
            "candidate_batch_hash": stable_hash(candidate_payloads),
            "ticket_batch_hash": stable_hash(ticket_payloads),
        }
        return {**manifest, "manifest_hash": stable_hash(manifest)}
    finally:
        session.close()
        engine.dispose()


def _edge_from_fixture(payload: dict[str, Any]) -> EdgeResult:
    return EdgeResult(**payload)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded
