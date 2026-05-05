"""
Edge detection.

Compares a FairPriceResult against a book's no-vig implied probability
to compute edge and determine whether the bet is a candidate.

  edge = fair_prob − book_no_vig_prob

Positive edge means our fair price is higher than the book's no-vig price —
we believe the event is more likely than the market does.

Workflow:
  1. Take a FairPriceResult and a raw book odds value (American).
  2. Convert book odds → implied prob.
  3. Remove vig from the market (needs the full set of probs for that market).
  4. Compute edge.
  5. Check against the minimum threshold for the sleeve (core vs convex).
  6. Return an EdgeResult.

For two-way matchups (2-ball), vig removal requires both sides' implied probs.
For outrights/top-N, the book's single-player probability is used directly
against a vig-removed field — but since DG gives us our fair price already
in no-vig terms and the book's per-player probability is a standalone market,
we apply vig removal per-matchup (two-side) and per-outright-market (multi-side).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.normalization.odds import american_to_decimal, decimal_to_implied
from src.normalization.vig import remove_vig
from src.pricing.fair_price import FairPriceResult
from src.risk.fdr import FdrInput, apply_benjamini_hochberg

# Markets in the convex sleeve (outrights). Everything else is core.
_CONVEX_MARKETS = frozenset({"outright_win"})


@dataclass(frozen=True)
class EdgeResult:
    """Output of a single edge computation."""

    datagolf_id: str
    opponent_id: str | None
    market_type: str
    book_id: str
    fair_prob: float         # from FairPriceResult
    book_no_vig_prob: float  # after vig removal
    edge: float              # fair_prob - book_no_vig_prob
    sleeve: str              # "core" | "convex"
    passes_threshold: bool   # True if edge ≥ min threshold for this sleeve
    book_american_odds: int  # raw book odds (for display / bet placement)
    edge_sd: float | None = None  # uncertainty around edge estimate, once available
    p_value: float | None = None  # candidate-level edge p-value, once available
    passes_fdr: bool = True       # default preserves pre-FDR behavior


def compute_edge(
    fair: FairPriceResult,
    book_american_odds: int,
    market_implied_probs: list[float],
    book_id: str,
    min_edge_core: float,
    min_edge_convex: float,
    vig_method: str = "multiplicative",
) -> EdgeResult:
    """Compute edge for one side of one market.

    Args:
        fair: Fair price for this side (from pricing layer).
        book_american_odds: The book's raw American odds for this player/side.
        market_implied_probs: ALL implied probabilities in this market (needed
            for vig removal). E.g., for a 2-ball: [implied_p1, implied_p2].
            For an outright field: implied probs for every player in the market.
        book_id: Sportsbook identifier (e.g., "draftkings").
        min_edge_core: Minimum edge threshold for core (matchup) bets.
        min_edge_convex: Minimum edge threshold for convex (outright) bets.
        vig_method: "multiplicative" or "power".

    Returns:
        EdgeResult with computed edge and threshold check.

    Raises:
        ValueError: If market_implied_probs is empty or contains non-positive values.
    """
    sleeve = "convex" if fair.market_type in _CONVEX_MARKETS else "core"
    threshold = min_edge_convex if sleeve == "convex" else min_edge_core

    # The book's raw implied prob for this side
    book_implied = decimal_to_implied(american_to_decimal(book_american_odds))

    # Find the index of this side in the market_implied_probs list
    # (caller must pass them in the same order, with this side's prob at index 0
    # — or pass the full list and we use the first one as "this side")
    this_side_index = _find_closest_index(book_implied, market_implied_probs)

    # Remove vig from the full market
    vig_result = remove_vig(market_implied_probs, method=vig_method)
    book_no_vig_prob = vig_result.no_vig_probs[this_side_index]

    edge = fair.fair_prob - book_no_vig_prob

    return EdgeResult(
        datagolf_id=fair.datagolf_id,
        opponent_id=fair.opponent_id,
        market_type=fair.market_type,
        book_id=book_id,
        fair_prob=fair.fair_prob,
        book_no_vig_prob=book_no_vig_prob,
        edge=edge,
        sleeve=sleeve,
        passes_threshold=edge >= threshold,
        book_american_odds=book_american_odds,
    )


def compute_two_way_edges(
    fair_p1: FairPriceResult,
    fair_p2: FairPriceResult,
    book_odds_p1: int,
    book_odds_p2: int,
    book_id: str,
    min_edge_core: float,
    min_edge_convex: float,
    vig_method: str = "multiplicative",
) -> tuple[EdgeResult, EdgeResult]:
    """Convenience wrapper for a two-way matchup (2-ball).

    Computes vig removal once for the two-side market and returns
    EdgeResult for both sides.

    Args:
        fair_p1, fair_p2: Fair prices for each side.
        book_odds_p1, book_odds_p2: Raw American odds from the book.
        book_id: Sportsbook identifier.
        min_edge_core, min_edge_convex: Thresholds from config.
        vig_method: Vig removal method.

    Returns:
        (EdgeResult for p1, EdgeResult for p2)
    """
    imp_p1 = decimal_to_implied(american_to_decimal(book_odds_p1))
    imp_p2 = decimal_to_implied(american_to_decimal(book_odds_p2))
    market_probs = [imp_p1, imp_p2]

    vig_result = remove_vig(market_probs, method=vig_method)
    no_vig_p1, no_vig_p2 = vig_result.no_vig_probs

    sleeve = "convex" if fair_p1.market_type in _CONVEX_MARKETS else "core"
    threshold = min_edge_convex if sleeve == "convex" else min_edge_core

    edge_p1 = EdgeResult(
        datagolf_id=fair_p1.datagolf_id,
        opponent_id=fair_p1.opponent_id,
        market_type=fair_p1.market_type,
        book_id=book_id,
        fair_prob=fair_p1.fair_prob,
        book_no_vig_prob=no_vig_p1,
        edge=fair_p1.fair_prob - no_vig_p1,
        sleeve=sleeve,
        passes_threshold=(fair_p1.fair_prob - no_vig_p1) >= threshold,
        book_american_odds=book_odds_p1,
    )
    edge_p2 = EdgeResult(
        datagolf_id=fair_p2.datagolf_id,
        opponent_id=fair_p2.opponent_id,
        market_type=fair_p2.market_type,
        book_id=book_id,
        fair_prob=fair_p2.fair_prob,
        book_no_vig_prob=no_vig_p2,
        edge=fair_p2.fair_prob - no_vig_p2,
        sleeve=sleeve,
        passes_threshold=(fair_p2.fair_prob - no_vig_p2) >= threshold,
        book_american_odds=book_odds_p2,
    )
    return edge_p1, edge_p2


def apply_fdr_control(
    edges: list[EdgeResult],
    *,
    enabled: bool,
    q_core: float,
    q_convex: float,
) -> list[EdgeResult]:
    """Populate candidate-level p-values and FDR decisions when enabled.

    Disabled mode preserves the current threshold-only behavior exactly while
    still returning a fresh list for callers that build candidates in batches.
    """
    if not enabled:
        return [
            replace(edge, p_value=None, passes_fdr=True)
            for edge in edges
        ]

    results_by_sleeve: dict[str, list[tuple[int, EdgeResult]]] = {"core": [], "convex": []}
    for index, edge in enumerate(edges):
        if edge.edge_sd is None:
            raise ValueError("edge_sd is required when FDR control is enabled.")
        results_by_sleeve.setdefault(edge.sleeve, []).append((index, edge))

    annotated: list[EdgeResult | None] = [None] * len(edges)
    for sleeve, indexed_edges in results_by_sleeve.items():
        if not indexed_edges:
            continue
        q = q_convex if sleeve == "convex" else q_core
        fdr_results = apply_benjamini_hochberg(
            [
                FdrInput(
                    candidate_id=str(index),
                    edge_mean=edge.edge,
                    edge_sd=edge.edge_sd or 0.0,
                )
                for index, edge in indexed_edges
            ],
            q=q,
        )
        for (index, edge), fdr_result in zip(indexed_edges, fdr_results, strict=True):
            annotated[index] = replace(
                edge,
                p_value=fdr_result.p_value,
                passes_fdr=fdr_result.passes_fdr,
            )

    return [edge for edge in annotated if edge is not None]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _find_closest_index(target: float, probs: list[float]) -> int:
    """Return the index of the value in probs closest to target."""
    return min(range(len(probs)), key=lambda i: abs(probs[i] - target))
