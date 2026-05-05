"""False-discovery-rate controls for edge candidates."""

from __future__ import annotations

from dataclasses import dataclass
from math import erfc, sqrt


@dataclass(frozen=True)
class FdrInput:
    """One candidate-level hypothesis test for edge > 0."""

    candidate_id: str
    edge_mean: float
    edge_sd: float


@dataclass(frozen=True)
class FdrResult:
    """Benjamini-Hochberg decision for one candidate."""

    candidate_id: str
    p_value: float
    rank: int
    bh_threshold: float
    passes_fdr: bool


def edge_p_value(*, edge_mean: float, edge_sd: float) -> float:
    """Return one-sided Normal p-value for H0: edge <= 0.

    A zero standard deviation is treated as a deterministic estimate: positive
    edge has p=0, while non-positive edge has p=1.
    """
    if edge_sd < 0:
        raise ValueError("edge_sd must be non-negative.")
    if edge_sd == 0:
        return 0.0 if edge_mean > 0 else 1.0

    z_score = edge_mean / edge_sd
    return 0.5 * erfc(z_score / sqrt(2.0))


def apply_benjamini_hochberg(candidates: list[FdrInput], *, q: float) -> list[FdrResult]:
    """Apply Benjamini-Hochberg FDR control and preserve input order."""
    if not 0 < q <= 1:
        raise ValueError("q must be in (0, 1].")
    if not candidates:
        return []

    candidate_count = len(candidates)
    p_values = [
        (index, candidate, edge_p_value(edge_mean=candidate.edge_mean, edge_sd=candidate.edge_sd))
        for index, candidate in enumerate(candidates)
    ]
    ranked = sorted(p_values, key=lambda item: (item[2], item[0]))

    cutoff_p_value: float | None = None
    ranked_payloads: list[tuple[int, FdrInput, float, int, float]] = []
    for rank, (index, candidate, p_value) in enumerate(ranked, start=1):
        threshold = (rank / candidate_count) * q
        ranked_payloads.append((index, candidate, p_value, rank, threshold))
        if p_value <= threshold:
            cutoff_p_value = p_value

    results_by_index = {}
    for index, candidate, p_value, rank, threshold in ranked_payloads:
        results_by_index[index] = FdrResult(
            candidate_id=candidate.candidate_id,
            p_value=p_value,
            rank=rank,
            bh_threshold=threshold,
            passes_fdr=cutoff_p_value is not None and p_value <= cutoff_p_value,
        )

    return [results_by_index[index] for index in range(candidate_count)]
