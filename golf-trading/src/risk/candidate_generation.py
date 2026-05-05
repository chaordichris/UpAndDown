"""Build persisted bet-candidate rows from edge results."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from src.risk.edge import EdgeResult, apply_fdr_control
from src.storage.hashing import artifact_hash
from src.storage.models import BetCandidate


def build_bet_candidates_from_edges(
    edges: list[EdgeResult],
    *,
    tournament_id: int,
    player_id_by_datagolf_id: dict[str, int],
    fdr_enabled: bool,
    fdr_q_core: float,
    fdr_q_convex: float,
    staleness_flag: bool = False,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> list[BetCandidate]:
    """Convert edge results into auditable candidate rows.

    Disabled FDR mode preserves threshold-only candidate behavior while clearing
    stale p-values. Enabled mode annotates the full batch before rows are built,
    so Benjamini-Hochberg decisions are made against the same candidate family
    that will be handed to ticketing.
    """
    annotated_edges = apply_fdr_control(
        edges,
        enabled=fdr_enabled,
        q_core=fdr_q_core,
        q_convex=fdr_q_convex,
    )
    return [
        build_bet_candidate_from_edge(
            edge,
            tournament_id=tournament_id,
            player_id_by_datagolf_id=player_id_by_datagolf_id,
            fdr_enabled=fdr_enabled,
            fdr_q_core=fdr_q_core,
            fdr_q_convex=fdr_q_convex,
            staleness_flag=staleness_flag,
            created_at=created_at,
            code_version=code_version,
        )
        for edge in annotated_edges
    ]


def build_bet_candidate_from_edge(
    edge: EdgeResult,
    *,
    tournament_id: int,
    player_id_by_datagolf_id: dict[str, int],
    fdr_enabled: bool,
    fdr_q_core: float,
    fdr_q_convex: float,
    staleness_flag: bool = False,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> BetCandidate:
    """Build one `BetCandidate` row from an already annotated edge."""
    player_id_1 = _require_player_id(player_id_by_datagolf_id, edge.datagolf_id)
    player_id_2 = (
        _require_player_id(player_id_by_datagolf_id, edge.opponent_id)
        if edge.opponent_id is not None
        else None
    )
    inputs_hash = artifact_hash(
        artifact_type="bet_candidate",
        inputs={
            "edge": asdict(edge),
            "tournament_id": tournament_id,
            "player_id_1": player_id_1,
            "player_id_2": player_id_2,
            "staleness_flag": staleness_flag,
        },
        config={
            "fdr_enabled": fdr_enabled,
            "fdr_q_core": fdr_q_core,
            "fdr_q_convex": fdr_q_convex,
        },
        code_version=code_version,
    )

    row_kwargs = {
        "tournament_id": tournament_id,
        "market_type": edge.market_type,
        "side": edge.datagolf_id,
        "player_id_1": player_id_1,
        "player_id_2": player_id_2,
        "book": edge.book_id,
        "fair_prob": edge.fair_prob,
        "book_prob": edge.book_no_vig_prob,
        "book_american_odds": edge.book_american_odds,
        "edge_pct": edge.edge,
        "edge_sd": edge.edge_sd,
        "p_value": edge.p_value,
        "passes_fdr": edge.passes_fdr,
        "confidence_score": 1.0,
        "staleness_flag": staleness_flag,
        "inputs_hash": inputs_hash,
    }
    if created_at is not None:
        row_kwargs["created_at"] = created_at

    return BetCandidate(**row_kwargs)


def _require_player_id(player_id_by_datagolf_id: dict[str, int], datagolf_id: str) -> int:
    try:
        return player_id_by_datagolf_id[datagolf_id]
    except KeyError as exc:
        raise ValueError(f"Missing player_id for DataGolf id {datagolf_id!r}.") from exc
