from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.execution.candidates import ticket_unticketed_candidates
from src.pricing.fair_price import FairPriceResult
from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import compute_two_way_edges
from src.storage.hashing import artifact_hash, stable_hash
from src.storage.models import Base, Player, Tournament

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "risk_candidate_generation_default.json"
)


def test_risk_candidate_generation_default_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "fair_prices": 2,
        "edges": 2,
        "candidates": 2,
        "tickets": 2,
    }
    assert first["edges"]["dg_primary_edge"]["edge"] == fixture["expected"]["primary_edge"]
    assert first["edges"]["dg_negative_edge"]["edge"] == fixture["expected"]["negative_edge"]
    assert first["candidate_summary"] == {
        "with_p_values": 0,
        "passes_fdr": 2,
    }
    assert first["ticket_summary"]["approved"] == fixture["expected"]["approved_ticket_count"]
    assert first["ticket_summary"]["rejected"] == fixture["expected"]["rejected_ticket_count"]
    assert first["tickets"]["dg_primary_edge"]["proposed_stake"] == fixture["expected"][
        "primary_stake"
    ]
    assert first["tickets"]["dg_primary_edge"]["sizing_method"] == fixture["expected"][
        "primary_sizing_method"
    ]
    assert first["tickets"]["dg_negative_edge"]["rejection_reason"] == fixture["expected"][
        "negative_rejection_reason"
    ]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "edge_batch_hash": manifest["edge_batch_hash"],
        "candidate_batch_hash": manifest["candidate_batch_hash"],
        "ticket_batch_hash": manifest["ticket_batch_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    fair_primary, fair_secondary = [
        _fair_price_from_fixture(fair, fixture["as_of"]) for fair in fixture["fair_prices"]
    ]
    edges = list(
        compute_two_way_edges(
            fair_primary,
            fair_secondary,
            book_odds_p1=fixture["book"]["odds"][0],
            book_odds_p2=fixture["book"]["odds"][1],
            book_id=fixture["book"]["book_id"],
            min_edge_core=fixture["edge_config"]["min_edge_core"],
            min_edge_convex=fixture["edge_config"]["min_edge_convex"],
            vig_method=fixture["edge_config"]["vig_method"],
        )
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        tournament = Tournament(**fixture["tournament"])
        players = [Player(**player) for player in fixture["players"]]
        session.add_all([tournament, *players])
        session.flush()

        candidates = build_bet_candidates_from_edges(
            edges,
            tournament_id=tournament.tournament_id,
            player_id_by_datagolf_id={
                player.datagolf_player_id: player.player_id for player in players
            },
            fdr_enabled=fixture["edge_config"]["fdr_enabled"],
            fdr_q_core=fixture["edge_config"]["fdr_q_core"],
            fdr_q_convex=fixture["edge_config"]["fdr_q_convex"],
            created_at=_dt(fixture["created_at"]),
            code_version=fixture["code_version"],
        )
        session.add_all(candidates)
        session.flush()

        tickets = ticket_unticketed_candidates(
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

        candidate_side_by_id = {
            candidate.candidate_id: candidate.side
            for candidate in candidates
        }
        edge_payloads = {edge.datagolf_id: _rounded(asdict(edge)) for edge in edges}
        candidate_payloads = {
            candidate.side: {
                "candidate_id": candidate.candidate_id,
                "edge_pct": round(candidate.edge_pct, 6),
                "p_value": candidate.p_value,
                "passes_fdr": candidate.passes_fdr,
                "inputs_hash": candidate.inputs_hash,
            }
            for candidate in candidates
        }
        ticket_payloads = {
            candidate_side_by_id[ticket.candidate_id]: {
                "ticket_id": ticket.ticket_id,
                "approved": ticket.approved,
                "proposed_stake": ticket.proposed_stake,
                "rejection_reason": ticket.rejection_reason,
                "sizing_method": ticket.sizing_method,
                "inputs_hash": ticket.inputs_hash,
            }
            for ticket in tickets
        }
        manifest = {
            "scenario": fixture["scenario"],
            "shape": {
                "fair_prices": 2,
                "edges": len(edges),
                "candidates": len(candidates),
                "tickets": len(tickets),
            },
            "edges": edge_payloads,
            "candidates": candidate_payloads,
            "tickets": ticket_payloads,
            "candidate_summary": {
                "with_p_values": sum(1 for candidate in candidates if candidate.p_value is not None),
                "passes_fdr": sum(1 for candidate in candidates if candidate.passes_fdr),
            },
            "ticket_summary": {
                "approved": sum(1 for ticket in tickets if ticket.approved),
                "rejected": sum(1 for ticket in tickets if not ticket.approved),
            },
            "edge_batch_hash": artifact_hash(
                artifact_type="risk_edge_batch",
                inputs={
                    "fair_prices": [asdict(fair_primary), asdict(fair_secondary)],
                    "book": fixture["book"],
                },
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


def _fair_price_from_fixture(payload: dict[str, Any], as_of: str) -> FairPriceResult:
    return FairPriceResult(
        market_type=payload["market_type"],
        datagolf_id=payload["datagolf_id"],
        opponent_id=payload["opponent_id"],
        fair_prob=payload["fair_prob"],
        method=payload["method"],
        as_of=_dt(as_of),
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded
