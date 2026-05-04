from __future__ import annotations

import pytest

from src.risk.fdr import FdrInput, apply_benjamini_hochberg, edge_p_value


def test_edge_p_value_shrinks_as_edge_sd_shrinks() -> None:
    high_uncertainty = edge_p_value(edge_mean=0.04, edge_sd=0.04)
    low_uncertainty = edge_p_value(edge_mean=0.04, edge_sd=0.01)

    assert low_uncertainty < high_uncertainty


def test_zero_sd_positive_edge_is_deterministic_pass_signal() -> None:
    assert edge_p_value(edge_mean=0.01, edge_sd=0.0) == 0.0


def test_zero_sd_non_positive_edge_is_deterministic_fail_signal() -> None:
    assert edge_p_value(edge_mean=0.0, edge_sd=0.0) == 1.0
    assert edge_p_value(edge_mean=-0.01, edge_sd=0.0) == 1.0


def test_bh_single_candidate_reduces_to_single_test() -> None:
    results = apply_benjamini_hochberg(
        [FdrInput(candidate_id="candidate_1", edge_mean=0.06, edge_sd=0.02)],
        q=0.05,
    )

    assert len(results) == 1
    assert results[0].candidate_id == "candidate_1"
    assert results[0].rank == 1
    assert results[0].bh_threshold == pytest.approx(0.05)
    assert results[0].passes_fdr


def test_bh_preserves_original_order() -> None:
    candidates = [
        FdrInput(candidate_id="weak", edge_mean=0.01, edge_sd=0.05),
        FdrInput(candidate_id="strong", edge_mean=0.08, edge_sd=0.01),
    ]
    results = apply_benjamini_hochberg(candidates, q=0.10)

    assert [result.candidate_id for result in results] == ["weak", "strong"]
    assert results[0].rank == 2
    assert results[1].rank == 1


def test_bh_pass_set_is_monotonic_as_q_increases() -> None:
    candidates = [
        FdrInput(candidate_id="a", edge_mean=0.07, edge_sd=0.02),
        FdrInput(candidate_id="b", edge_mean=0.05, edge_sd=0.02),
        FdrInput(candidate_id="c", edge_mean=0.02, edge_sd=0.02),
        FdrInput(candidate_id="d", edge_mean=0.00, edge_sd=0.02),
    ]

    strict_passes = {
        result.candidate_id
        for result in apply_benjamini_hochberg(candidates, q=0.05)
        if result.passes_fdr
    }
    loose_passes = {
        result.candidate_id
        for result in apply_benjamini_hochberg(candidates, q=0.20)
        if result.passes_fdr
    }

    assert strict_passes.issubset(loose_passes)
    assert loose_passes


def test_bh_returns_empty_list_for_no_candidates() -> None:
    assert apply_benjamini_hochberg([], q=0.10) == []


@pytest.mark.parametrize("q", [0.0, -0.1, 1.01])
def test_invalid_q_raises(q: float) -> None:
    with pytest.raises(ValueError, match="q"):
        apply_benjamini_hochberg([FdrInput("candidate_1", 0.05, 0.02)], q=q)


def test_negative_edge_sd_raises() -> None:
    with pytest.raises(ValueError, match="edge_sd"):
        edge_p_value(edge_mean=0.05, edge_sd=-0.01)
