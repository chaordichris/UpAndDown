from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import run_pipeline as pipeline
from src.config import clear_config_cache
from src.storage.db import get_session
from src.storage.models import BetCandidate, Player, Tournament


@pytest.mark.parametrize("market", ["top_20", "top_10", "top_5", "make_cut"])
def test_run_pipeline_core_yes_market_persists_candidate_rows(
    tmp_path,
    monkeypatch,
    capsys,
    market,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"
    monkeypatch.setenv("DATAGOLF_API_KEY", "test-key")
    clear_config_cache()
    monkeypatch.setattr(pipeline, "DataGolfClient", _fake_client(_finish_payload(market), market))

    try:
        edges = pipeline.run_pipeline(
            database_url=database_url,
            tour="pga",
            books=["draftkings", "fanduel"],
            dry_run=False,
            market=market,
        )
    finally:
        clear_config_cache()

    captured = capsys.readouterr()
    assert f"Fetching {market} odds" in captured.out
    assert "Persisted 2 candidates" in captured.out
    assert len(edges) == 4

    with get_session(database_url) as session:
        tournament_name = session.query(Tournament).one().name
        player_names = [
            player.name_canonical
            for player in session.query(Player).order_by(Player.player_id).all()
        ]
        candidate_values = [
            {
                "market_type": candidate.market_type,
                "book": candidate.book,
                "side": candidate.side,
                "player_id_2": candidate.player_id_2,
                "fair_prob": candidate.fair_prob,
                "book_prob": candidate.book_prob,
                "edge_pct": candidate.edge_pct,
                "inputs_hash": candidate.inputs_hash,
            }
            for candidate in session.query(BetCandidate).order_by(BetCandidate.candidate_id).all()
        ]

    assert tournament_name == "Proof Market Open"
    assert player_names == ["Scottie Scheffler", "Rory McIlroy"]
    assert [candidate["market_type"] for candidate in candidate_values] == [market, market]
    assert [candidate["book"] for candidate in candidate_values] == ["draftkings", "fanduel"]
    assert {candidate["side"] for candidate in candidate_values} == {"scottie_scheffler"}
    assert candidate_values[0]["player_id_2"] is None
    assert candidate_values[0]["fair_prob"] == pytest.approx(1 / 3)
    assert candidate_values[0]["book_prob"] == pytest.approx(0.20)
    assert candidate_values[0]["edge_pct"] == pytest.approx(0.1333333333)
    assert candidate_values[0]["inputs_hash"]


@pytest.mark.parametrize("market", ["top_10", "make_cut"])
def test_run_pipeline_core_yes_market_writes_zero_edge_analysis_artifact(
    tmp_path,
    monkeypatch,
    capsys,
    market,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"
    analysis_path = tmp_path / "artifacts" / "daily-analysis.json"
    monkeypatch.setenv("DATAGOLF_API_KEY", "test-key")
    clear_config_cache()
    monkeypatch.setattr(pipeline, "DataGolfClient", _fake_client(_finish_payload(market, zero_edge=True), market))

    try:
        edges = pipeline.run_pipeline(
            database_url=database_url,
            tour="pga",
            books=["draftkings", "fanduel", "betmgm"],
            dry_run=False,
            market=market,
            analysis_output=analysis_path,
            near_miss_limit=2,
        )
    finally:
        clear_config_cache()

    captured = capsys.readouterr()
    artifact = json.loads(analysis_path.read_text())

    assert "No edges above threshold" in captured.out
    assert "Analysis artifact written" in captured.out
    assert len(edges) == 4
    assert artifact["artifact_type"] == "daily_analysis_run"
    assert artifact["event_name"] == "No Play Open"
    assert artifact["market"] == market
    assert artifact["requested_books"] == ["draftkings", "fanduel", "betmgm"]
    assert artifact["evaluated_books"] == ["draftkings", "fanduel"]
    assert artifact["missing_books"] == ["betmgm"]
    assert artifact["edges_computed"] == 4
    assert artifact["qualified_edges_count"] == 0
    assert artifact["qualified_edges"] == []
    assert len(artifact["near_misses"]) == 2
    assert artifact["near_misses"][0]["passes_threshold"] is False
    assert artifact["artifact_hash"]

    with get_session(database_url) as session:
        assert session.query(BetCandidate).count() == 0


def test_run_pipeline_outright_win_maps_to_datagolf_win_and_persists_candidates(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"
    monkeypatch.setenv("DATAGOLF_API_KEY", "test-key")
    clear_config_cache()
    monkeypatch.setattr(pipeline, "DataGolfClient", _fake_client(_outright_payload(), "win"))

    try:
        edges = pipeline.run_pipeline(
            database_url=database_url,
            tour="pga",
            books=["draftkings", "fanduel"],
            dry_run=False,
            market="outright_win",
        )
    finally:
        clear_config_cache()

    captured = capsys.readouterr()
    assert "Fetching outright_win odds from DataGolf (market=win" in captured.out
    assert "Persisted 2 candidates" in captured.out
    assert len(edges) == 4
    assert {edge.market_type for edge in edges} == {"outright_win"}
    assert {edge.sleeve for edge in edges} == {"convex"}

    with get_session(database_url) as session:
        candidate_values = [
            {
                "market_type": candidate.market_type,
                "book": candidate.book,
                "side": candidate.side,
                "fair_prob": candidate.fair_prob,
                "book_prob": candidate.book_prob,
                "edge_pct": candidate.edge_pct,
            }
            for candidate in session.query(BetCandidate).order_by(BetCandidate.candidate_id).all()
        ]

    assert [candidate["market_type"] for candidate in candidate_values] == [
        "outright_win",
        "outright_win",
    ]
    assert [candidate["book"] for candidate in candidate_values] == ["draftkings", "fanduel"]
    assert {candidate["side"] for candidate in candidate_values} == {"scottie_scheffler"}
    assert candidate_values[0]["fair_prob"] == pytest.approx(1 / 6)
    assert candidate_values[0]["book_prob"] == pytest.approx(1 / 26)
    assert candidate_values[0]["edge_pct"] == pytest.approx(0.1282051282)


def test_run_pipeline_outright_win_writes_zero_edge_analysis_artifact(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'paper.db'}"
    analysis_path = tmp_path / "artifacts" / "daily-analysis-outright.json"
    monkeypatch.setenv("DATAGOLF_API_KEY", "test-key")
    clear_config_cache()
    monkeypatch.setattr(pipeline, "DataGolfClient", _fake_client(_outright_payload(zero_edge=True), "win"))

    try:
        edges = pipeline.run_pipeline(
            database_url=database_url,
            tour="pga",
            books=["draftkings", "fanduel", "betmgm"],
            dry_run=False,
            market="outright_win",
            analysis_output=analysis_path,
            near_miss_limit=1,
        )
    finally:
        clear_config_cache()

    captured = capsys.readouterr()
    artifact = json.loads(analysis_path.read_text())

    assert "No edges above threshold" in captured.out
    assert len(edges) == 4
    assert artifact["event_name"] == "No Outright Play Open"
    assert artifact["market"] == "outright_win"
    assert artifact["evaluated_books"] == ["draftkings", "fanduel"]
    assert artifact["missing_books"] == ["betmgm"]
    assert artifact["qualified_edges_count"] == 0
    assert len(artifact["near_misses"]) == 1
    assert artifact["near_misses"][0]["market_type"] == "outright_win"
    assert artifact["near_misses"][0]["sleeve"] == "convex"

    with get_session(database_url) as session:
        assert session.query(BetCandidate).count() == 0


def _finish_payload(market: str, *, zero_edge: bool = False) -> dict:
    if zero_edge:
        return {
            "event_name": "No Play Open",
            "tour": "pga",
            "market": market,
            "last_updated": "2026-06-30 15:00:00",
            "player_list": [
                {
                    "player_name": "Scottie Scheffler",
                    "datagolf_id": "scottie_scheffler",
                    "draftkings": 150,
                    "fanduel": 140,
                    "datagolf_baseline_history_fit": 400,
                },
                {
                    "player_name": "Rory McIlroy",
                    "datagolf_id": "rory_mcilroy",
                    "draftkings": 250,
                    "fanduel": 240,
                    "datagolf_baseline_history_fit": 500,
                },
            ],
        }
    return {
        "event_name": "Proof Market Open",
        "tour": "pga",
        "market": market,
        "last_updated": "2026-06-30 14:00:00",
        "player_list": [
            {
                "player_name": "Scottie Scheffler",
                "datagolf_id": "scottie_scheffler",
                "draftkings": 400,
                "fanduel": 250,
                "datagolf_baseline_history_fit": 200,
            },
            {
                "player_name": "Rory McIlroy",
                "datagolf_id": "rory_mcilroy",
                "draftkings": 300,
                "fanduel": 275,
                "datagolf_baseline_history_fit": 300,
            },
        ],
    }


def _outright_payload(*, zero_edge: bool = False) -> dict:
    if zero_edge:
        return {
            "event_name": "No Outright Play Open",
            "tour": "pga",
            "market": "win",
            "last_updated": "2026-06-30 16:00:00",
            "player_list": [
                {
                    "player_name": "Scottie Scheffler",
                    "datagolf_id": "scottie_scheffler",
                    "draftkings": 800,
                    "fanduel": 750,
                    "datagolf_baseline_history_fit": 1200,
                },
                {
                    "player_name": "Rory McIlroy",
                    "datagolf_id": "rory_mcilroy",
                    "draftkings": 1000,
                    "fanduel": 900,
                    "datagolf_baseline_history_fit": 1400,
                },
            ],
        }
    return {
        "event_name": "Proof Outright Open",
        "tour": "pga",
        "market": "win",
        "last_updated": "2026-06-30 15:30:00",
        "player_list": [
            {
                "player_name": "Scottie Scheffler",
                "datagolf_id": "scottie_scheffler",
                "draftkings": 2500,
                "fanduel": 2200,
                "datagolf_baseline_history_fit": 500,
            },
            {
                "player_name": "Rory McIlroy",
                "datagolf_id": "rory_mcilroy",
                "draftkings": 1000,
                "fanduel": 1200,
                "datagolf_baseline_history_fit": 1500,
            },
        ],
    }


def _fake_client(payload: dict, expected_market: str):
    class FakeDataGolfClient:
        def __init__(self, api_key: str, session) -> None:
            self.api_key = api_key
            self.session = session

        def fetch_live_outrights(self, *, tour: str, market: str, odds_format: str):
            assert tour == "pga"
            assert market == expected_market
            assert odds_format == "american"
            return SimpleNamespace(data=payload)

    return FakeDataGolfClient
