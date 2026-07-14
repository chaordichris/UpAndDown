"""Simulator venue: drifting true probability + two trader populations.

- The *true* probability follows a bounded random walk (information arrives).
- **Uninformed flow** arrives at random and crosses our quotes regardless of
  value — this is the spread-capture business.
- **Informed flow** sees the true probability and lifts only quotes that are
  mispriced against it — this is adverse selection.

Deterministic under a seed so simulator runs are replayable artifacts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..types import Fill, Quote, Side
from .base import VenueAdapter


@dataclass(frozen=True)
class SimParams:
    initial_true_prob: float = 0.30
    drift_sd: float = 0.01            # per-step random walk sd
    uninformed_arrival_prob: float = 0.30  # chance per step per side
    informed_arrival_prob: float = 0.10
    informed_min_edge: float = 0.01   # informed trade only if quote is off by this
    max_fill_size: int = 5
    steps: int = 200
    seed: int = 7


class SimVenue(VenueAdapter):
    def __init__(self, market_id: str, params: SimParams) -> None:
        self.market_id = market_id
        self.params = params
        self.rng = random.Random(params.seed)
        self.true_prob = params.initial_true_prob
        self.true_prob_path: list[float] = [params.initial_true_prob]

    def step_world(self) -> None:
        """Advance the true probability one step (information arrival)."""
        self.true_prob = min(
            0.99, max(0.01, self.true_prob + self.rng.gauss(0.0, self.params.drift_sd))
        )
        self.true_prob_path.append(self.true_prob)

    def post_quotes(self, quotes: tuple[Quote, ...], timestep: int) -> list[Fill]:
        fills: list[Fill] = []
        for quote in quotes:
            size = self.rng.randint(1, min(self.params.max_fill_size, quote.size))
            # Uninformed flow: crosses either side at random.
            if self.rng.random() < self.params.uninformed_arrival_prob:
                fills.append(Fill(self.market_id, quote.side, quote.price, size, timestep))
                continue
            # Informed flow: hits only mispriced quotes.
            if self.rng.random() < self.params.informed_arrival_prob:
                edge_vs_truth = (
                    quote.price - self.true_prob  # our bid too high → they sell to us
                    if quote.side == Side.BID
                    else self.true_prob - quote.price  # our ask too low → they buy
                )
                if edge_vs_truth > self.params.informed_min_edge:
                    fills.append(Fill(self.market_id, quote.side, quote.price, size, timestep))
        return fills

    def settle(self, market_id: str) -> float:
        return 1.0 if self.rng.random() < self.true_prob else 0.0
