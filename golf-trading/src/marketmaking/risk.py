"""Risk engine: hard vetoes over every quote. Cannot be overridden.

Mirrors the bankroll engine's veto power over bets. The quoting engine
proposes; this module disposes. All limits come from MMConfig.
"""

from __future__ import annotations

from .config import MMConfig
from .types import InventoryState, Quote, QuoteProposal, RiskDecision, Side


class RiskEngine:
    def __init__(self, config: MMConfig) -> None:
        self._config = config
        self._realized_loss_today = 0.0

    def record_pnl(self, pnl: float) -> None:
        """Track realized P&L; losses accumulate toward the kill switch."""
        self._realized_loss_today -= min(pnl, 0.0)

    @property
    def kill_switch_active(self) -> bool:
        return self._realized_loss_today >= self._config.daily_loss_kill_switch

    def review(
        self,
        proposal: QuoteProposal,
        inventory: InventoryState,
        tournament_notional: float,
    ) -> RiskDecision:
        """Approve or veto each proposed quote. Reasons are always recorded."""
        if self.kill_switch_active:
            return RiskDecision(
                approved=(),
                vetoed=tuple(
                    (q, f"kill switch: daily loss {self._realized_loss_today:.2f} "
                        f">= {self._config.daily_loss_kill_switch:.2f}")
                    for q in proposal.quotes
                ),
                kill_switch=True,
            )

        approved: list[Quote] = []
        vetoed: list[tuple[Quote, str]] = []
        for quote in proposal.quotes:
            sign = 1 if quote.side == Side.BID else -1
            projected = inventory.position + sign * quote.size
            if abs(projected) > self._config.max_position_per_market:
                vetoed.append(
                    (quote, f"position limit: |{projected}| > "
                            f"{self._config.max_position_per_market}")
                )
                continue
            worst_case = quote.price * quote.size if quote.side == Side.BID \
                else (1.0 - quote.price) * quote.size
            if tournament_notional + worst_case > self._config.max_notional_per_tournament:
                vetoed.append(
                    (quote, f"tournament notional limit: "
                            f"{tournament_notional + worst_case:.2f} > "
                            f"{self._config.max_notional_per_tournament:.2f}")
                )
                continue
            approved.append(quote)

        return RiskDecision(approved=tuple(approved), vetoed=tuple(vetoed))
