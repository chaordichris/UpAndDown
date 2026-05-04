from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.risk.candidate_generation import build_bet_candidates_from_edges
from src.risk.edge import EdgeResult

NOW = datetime(2024, 3, 11, 14, 0, tzinfo=UTC)


def test_candidate_generation_disabled_fdr_preserves_selection_defaults() -> None:
    edge = _edge(p_value=0.001, passes_fdr=False)

    candidates = build_bet_candidates_from_edges(
        [edge],
        tournament_id=12,
        player_id_by_datagolf_id={"scheffler": 1, "mcilroy": 2},
        fdr_enabled=False,
        fdr_q_core=0.20,
        fdr_q_convex=0.10,
        created_at=NOW,
        code_version="test",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.p_value is None
    assert candidate.passes_fdr is True
    assert candidate.edge_sd == 0.01
    assert candidate.book_american_odds == -110
    assert candidate.inputs_hash


def test_candidate_generation_applies_fdr_to_real_batch() -> None:
    strong = _edge(datagolf_id="strong", opponent_id="field", edge=0.08, edge_sd=0.01)
    noisy = _edge(datagolf_id="noisy", opponent_id="field", edge=0.01, edge_sd=0.05)

    candidates = build_bet_candidates_from_edges(
        [strong, noisy],
        tournament_id=12,
        player_id_by_datagolf_id={"strong": 1, "noisy": 2, "field": 3},
        fdr_enabled=True,
        fdr_q_core=0.20,
        fdr_q_convex=0.10,
        created_at=NOW,
        code_version="test",
    )

    assert [candidate.side for candidate in candidates] == ["strong", "noisy"]
    assert candidates[0].p_value is not None
    assert candidates[0].passes_fdr is True
    assert candidates[1].p_value is not None
    assert candidates[1].passes_fdr is False


def test_candidate_generation_requires_edge_sd_when_fdr_enabled() -> None:
    with pytest.raises(ValueError, match="edge_sd"):
        build_bet_candidates_from_edges(
            [_edge(edge_sd=None)],
            tournament_id=12,
            player_id_by_datagolf_id={"scheffler": 1, "mcilroy": 2},
            fdr_enabled=True,
            fdr_q_core=0.20,
            fdr_q_convex=0.10,
        )


def test_candidate_generation_requires_player_mapping() -> None:
    with pytest.raises(ValueError, match="Missing player_id"):
        build_bet_candidates_from_edges(
            [_edge()],
            tournament_id=12,
            player_id_by_datagolf_id={"scheffler": 1},
            fdr_enabled=False,
            fdr_q_core=0.20,
            fdr_q_convex=0.10,
        )


def _edge(
    *,
    datagolf_id: str = "scheffler",
    opponent_id: str | None = "mcilroy",
    edge: float = 0.05,
    edge_sd: float | None = 0.01,
    p_value: float | None = None,
    passes_fdr: bool = True,
) -> EdgeResult:
    return EdgeResult(
        datagolf_id=datagolf_id,
        opponent_id=opponent_id,
        market_type="matchup_2ball",
        book_id="dk",
        fair_prob=0.55,
        book_no_vig_prob=0.55 - edge,
        edge=edge,
        sleeve="core",
        passes_threshold=edge >= 0.03,
        book_american_odds=-110,
        edge_sd=edge_sd,
        p_value=p_value,
        passes_fdr=passes_fdr,
    )
