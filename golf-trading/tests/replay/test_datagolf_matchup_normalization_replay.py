from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.ingestion.sportsbooks import parse_datagolf_matchups_response
from src.normalization.odds import normalize_american
from src.normalization.vig import remove_vig
from src.storage.hashing import artifact_hash, stable_hash

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "replay" / "datagolf_matchup_normalization.json"
)


def test_datagolf_matchup_normalization_replay_contract_is_stable() -> None:
    fixture = _load_fixture()

    first = _run_replay(fixture)
    second = _run_replay(fixture)

    assert first == second
    assert first["shape"] == {
        "matchups": fixture["expected"]["matchup_count"],
        "normalized_rows": fixture["expected"]["normalized_rows"],
    }
    assert first["matchups"][0]["vig"]["hold_pct"] == fixture["expected"][
        "first_matchup_hold_pct"
    ]
    assert first["matchups"][0]["vig"]["no_vig_probs"] == fixture["expected"][
        "first_matchup_no_vig_probs"
    ]
    assert first["matchups"][1]["vig"]["no_vig_probs"] == fixture["expected"][
        "second_matchup_no_vig_probs"
    ]
    assert _actual_hashes(first) == fixture["expected_hashes"]


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open() as file:
        return json.load(file)


def _actual_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "parsed_snapshot_hash": manifest["parsed_snapshot_hash"],
        "normalized_batch_hash": manifest["normalized_batch_hash"],
        "manifest_hash": manifest["manifest_hash"],
    }


def _run_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    snapshot = parse_datagolf_matchups_response(
        fixture["raw_response"],
        book_id=fixture["book_id"],
    )
    matchup_payloads = []
    normalized_rows = []
    for matchup in snapshot.matchups:
        normalized_odds = [
            normalize_american(player.american_odds)
            for player in matchup.players
        ]
        vig = remove_vig(
            [odds.implied_prob for odds in normalized_odds],
            method=fixture["vig_method"],
        )
        rows = [
            {
                "matchup_id": matchup.matchup_id,
                "book_id": matchup.book_id,
                "market_type": matchup.market_type,
                "captured_at": matchup.captured_at.isoformat(),
                "datagolf_id": player.datagolf_id,
                "american_odds": player.american_odds,
                "decimal_odds": round(odds.decimal, 6),
                "implied_prob": round(odds.implied_prob, 6),
                "no_vig_prob": round(vig.no_vig_probs[index], 6),
                "hold_pct": round(vig.hold_pct, 6),
                "vig_method": vig.method,
            }
            for index, (player, odds) in enumerate(zip(matchup.players, normalized_odds))
        ]
        normalized_rows.extend(rows)
        matchup_payloads.append(
            {
                "matchup": asdict(matchup),
                "vig": {
                    "hold_pct": round(vig.hold_pct, 6),
                    "method": vig.method,
                    "raw_probs": _rounded_sequence(vig.raw_probs),
                    "no_vig_probs": _rounded_sequence(vig.no_vig_probs),
                },
                "rows": rows,
            }
        )

    manifest = {
        "scenario": fixture["scenario"],
        "shape": {
            "matchups": len(snapshot.matchups),
            "normalized_rows": len(normalized_rows),
        },
        "matchups": matchup_payloads,
        "normalized_rows": normalized_rows,
        "parsed_snapshot_hash": artifact_hash(
            artifact_type="datagolf_matchup_book_snapshot",
            inputs={
                "book_id": fixture["book_id"],
                "raw_response": fixture["raw_response"],
            },
            config=None,
            code_version=fixture["code_version"],
        ),
        "normalized_batch_hash": artifact_hash(
            artifact_type="normalized_matchup_odds_batch",
            inputs=normalized_rows,
            config={"vig_method": fixture["vig_method"]},
            code_version=fixture["code_version"],
        ),
    }
    return {**manifest, "manifest_hash": stable_hash(manifest)}


def _rounded_sequence(values: tuple[float, ...]) -> list[float]:
    return [round(value, 6) for value in values]
