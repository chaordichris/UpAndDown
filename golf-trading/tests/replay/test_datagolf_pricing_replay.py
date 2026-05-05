from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pricing.outrights import price_all_outrights
from src.pricing.top_n import price_all_top_n
from src.storage.hashing import artifact_hash, stable_hash

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "replay" / "datagolf_pricing.json"


def test_datagolf_pricing_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "forecast_players": 3,
        "outright_prices": fixture["expected"]["outright_count"],
        "top_n_prices": fixture["expected"]["top_n_count"],
        "fair_prices": fixture["expected"]["fair_price_count"],
    }
    assert first["summary"]["methods"] == fixture["expected"]["methods"]
    assert first["summary"]["markets"] == fixture["expected"]["markets"]
    assert first["fair_prices"]["dg_scottie_scheffler:outright_win"]["fair_prob"] == fixture[
        "expected"
    ]["scottie_outright_prob"]
    assert first["summary"]["partial_player_markets"] == fixture["expected"][
        "partial_player_markets"
    ]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "fair_price_batch_hash": manifest["fair_price_batch_hash"],
        "pricing_inputs_hash": manifest["pricing_inputs_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    as_of = datetime.fromisoformat(fixture["as_of"])
    forecast_response = fixture["forecast_response"]
    outright_prices = price_all_outrights(forecast_response, as_of=as_of)
    top_n_prices = [
        price
        for player in forecast_response["players"]
        for price in price_all_top_n(player, as_of=as_of)
    ]
    fair_prices = [*outright_prices, *top_n_prices]
    fair_price_payloads = {
        f"{price.datagolf_id}:{price.market_type}": _rounded(asdict(price))
        for price in sorted(
            fair_prices,
            key=lambda item: (item.datagolf_id, item.market_type),
        )
    }
    manifest = {
        "scenario": fixture["scenario"],
        "shape": {
            "forecast_players": len(forecast_response["players"]),
            "outright_prices": len(outright_prices),
            "top_n_prices": len(top_n_prices),
            "fair_prices": len(fair_prices),
        },
        "fair_prices": fair_price_payloads,
        "summary": {
            "methods": sorted({price.method for price in fair_prices}),
            "markets": sorted({price.market_type for price in fair_prices}),
            "partial_player_markets": sorted(
                price.market_type
                for price in fair_prices
                if price.datagolf_id == "dg_partial_player"
            ),
        },
        "pricing_inputs_hash": artifact_hash(
            artifact_type="datagolf_pricing_inputs",
            inputs={
                "forecast_response": forecast_response,
                "as_of": fixture["as_of"],
            },
            config=None,
            code_version=fixture["code_version"],
        ),
        "fair_price_batch_hash": artifact_hash(
            artifact_type="fair_price_batch",
            inputs=fair_price_payloads,
            config={"method": "datagolf_forecast"},
            code_version=fixture["code_version"],
        ),
    }
    return {**manifest, "manifest_hash": stable_hash(manifest)}


def _rounded(payload: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(payload)
    for key, value in rounded.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
    return rounded
