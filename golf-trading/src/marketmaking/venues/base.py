"""Abstract venue adapter. The quoting engine never sees venue specifics."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import Fill, Quote


class VenueAdapter(ABC):
    """One venue (or simulator). Post quotes, receive fills, learn settlement."""

    @abstractmethod
    def post_quotes(self, quotes: tuple[Quote, ...], timestep: int) -> list[Fill]:
        """Replace our resting quotes for the step; return any fills."""

    @abstractmethod
    def settle(self, market_id: str) -> float:
        """Return settlement value (0.0 or 1.0) for a resolved market."""
