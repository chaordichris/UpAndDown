from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pricing.fair_price import FairPriceResult
from src.risk.edge import EdgeResult, compute_two_way_edges
from src.risk.sizing import SizingResult, size_core_bet
from src.storage.hashing import artifact_hash, stable_hash

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "replay" / "risk_edge_sizing.json"


def test_risk_edge_sizing_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "fair_prices": 2,
        "edges": 2,
        "sizing_results": 2,
    }
    assert first["primary"]["edge"]["edge"] == fixture["expected"]["primary_edge"]
    assert first["primary"]["edge"]["passes_threshold"] is fixture["expected"][
        "primary_passes_threshold"
    ]
    assert first["primary"]["sizing"]["stake"] == fixture["expected"]["primary_stake"]
    assert first["primary"]["sizing"]["approved"] is fixture["expected"]["primary_approved"]
    assert first["secondary"]["edge"]["edge"] == fixture["expected"]["secondary_edge"]
    assert first["secondary"]["edge"]["passes_threshold"] is fixture["expected"][
        "secondary_passes_threshold"
    ]
    assert first["secondary"]["sizing"]["stake"] == fixture["expected"]["secondary_stake"]
    assert first["secondary"]["sizing"]["approved"] is fixture["expected"]["secondary_approved"]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "primary_edge_inputs_hash": manifest["primary"]["edge_inputs_hash"],
        "primary_sizing_inputs_hash": manifest["primary"]["sizing_inputs_hash"],
        "secondary_edge_inputs_hash": manifest["secondary"]["edge_inputs_hash"],
        "secondary_sizing_inputs_hash": manifest["secondary"]["sizing_inputs_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    fair_primary, fair_secondary = [
        _fair_price_from_fixture(fair, fixture["as_of"]) for fair in fixture["fair_prices"]
    ]
    edge_primary, edge_secondary = compute_two_way_edges(
        fair_primary,
        fair_secondary,
        book_odds_p1=fixture["book"]["odds"][0],
        book_odds_p2=fixture["book"]["odds"][1],
        book_id=fixture["book"]["book_id"],
        min_edge_core=fixture["edge_config"]["min_edge_core"],
        min_edge_convex=fixture["edge_config"]["min_edge_convex"],
        vig_method=fixture["edge_config"]["vig_method"],
    )
    sizing_primary = _size_core_fixture_bet(edge_primary, fixture)
    sizing_secondary = _size_core_fixture_bet(edge_secondary, fixture)

    primary_edge_hash = _edge_inputs_hash(fixture, fair_primary, 0)
    secondary_edge_hash = _edge_inputs_hash(fixture, fair_secondary, 1)
    primary_sizing_hash = _sizing_inputs_hash(fixture, edge_primary, primary_edge_hash)
    secondary_sizing_hash = _sizing_inputs_hash(fixture, edge_secondary, secondary_edge_hash)

    manifest = {
        "scenario": fixture["scenario"],
        "shape": {
            "fair_prices": 2,
            "edges": 2,
            "sizing_results": 2,
        },
        "primary": _contract_side(edge_primary, sizing_primary, primary_edge_hash, primary_sizing_hash),
        "secondary": _contract_side(
            edge_secondary,
            sizing_secondary,
            secondary_edge_hash,
            secondary_sizing_hash,
        ),
    }
    return {**manifest, "manifest_hash": stable_hash(manifest)}


def _fair_price_from_fixture(payload: dict[str, Any], as_of: str) -> FairPriceResult:
    return FairPriceResult(
        market_type=payload["market_type"],
        datagolf_id=payload["datagolf_id"],
        opponent_id=payload["opponent_id"],
        fair_prob=payload["fair_prob"],
        method=payload["method"],
        as_of=datetime.fromisoformat(as_of),
    )


def _size_core_fixture_bet(edge: EdgeResult, fixture: dict[str, Any]) -> SizingResult:
    return size_core_bet(
        edge=edge,
        active_bankroll=fixture["bankroll"]["active_bankroll"],
        total_bankroll=fixture["bankroll"]["total_bankroll"],
        kelly_multiplier=fixture["sizing_config"]["kelly_multiplier"],
        min_bet_dollars=fixture["sizing_config"]["min_bet_dollars"],
        max_bet_fraction=fixture["sizing_config"]["max_bet_fraction"],
    )


def _edge_inputs_hash(fixture: dict[str, Any], fair: FairPriceResult, side_index: int) -> str:
    return artifact_hash(
        artifact_type="risk_edge_result",
        inputs={
            "fair_price": asdict(fair),
            "book": fixture["book"],
            "side_index": side_index,
        },
        config=fixture["edge_config"],
        code_version=fixture["code_version"],
    )


def _sizing_inputs_hash(
    fixture: dict[str, Any],
    edge: EdgeResult,
    edge_inputs_hash: str,
) -> str:
    return artifact_hash(
        artifact_type="risk_sizing_result",
        inputs={
            "edge": asdict(edge),
            "edge_inputs_hash": edge_inputs_hash,
            "bankroll": fixture["bankroll"],
        },
        config=fixture["sizing_config"],
        code_version=fixture["code_version"],
    )


def _contract_side(
    edge: EdgeResult,
    sizing: SizingResult,
    edge_inputs_hash: str,
    sizing_inputs_hash: str,
) -> dict[str, Any]:
    return {
        "edge": _rounded(asdict(edge)),
        "sizing": _rounded(asdict(sizing)),
        "edge_inputs_hash": edge_inputs_hash,
        "sizing_inputs_hash": sizing_inputs_hash,
    }


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded
