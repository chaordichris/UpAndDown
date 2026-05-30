"""Shadow-live placement guardrails.

Shadow-live is the Phase 4 operational-learning mode: real money at minimum
stakes, manually placed at the book, recorded in the same DB as paper bets.
It is NOT a substitute for Phase 3 gate evidence — the paper-trade count and
CLV remain the formal gate metrics.

Placement flow
--------------
1. Operator selects SHADOW LIVE mode in the console place-ticket form.
2. Console calls ``check_shadow_live_placement`` before writing anything.
3. If all guardrails pass, ``place_ticket_row`` is called with
   ``placement_method=SHADOW_LIVE_METHOD``.
4. The paper report excludes shadow-live bets; the shadow-live summary shows
   them separately.

The guardrails are intentionally simple: three numeric caps that the operator
sets in ``config/settings.yaml``. No automation, no side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.storage.models import BetCandidate, BetTicket, PlacedBet

# Value stored in placed_bets.placement_method for real-money shadow-live bets.
SHADOW_LIVE_METHOD: str = "shadow_live"


@dataclass(frozen=True)
class ShadowLiveGuardrail:
    """Config-driven caps for shadow-live placement.

    Construct from ``settings.shadow_live``::

        guardrail = ShadowLiveGuardrail(
            enabled=settings.shadow_live.enabled,
            starting_bankroll_dollars=settings.shadow_live.starting_bankroll_dollars,
            per_bet_cap_dollars=settings.shadow_live.per_bet_cap_dollars,
            per_tournament_cap_dollars=settings.shadow_live.per_tournament_cap_dollars,
        )
    """

    enabled: bool
    starting_bankroll_dollars: float
    per_bet_cap_dollars: float
    per_tournament_cap_dollars: float


def check_shadow_live_placement(
    session: Session,
    guardrail: ShadowLiveGuardrail,
    proposed_stake: float,
    tournament_id: int,
) -> None:
    """Raise ``ValueError`` if a proposed shadow-live placement violates guardrails.

    Checks in order:
    1. Shadow-live mode is enabled in config.
    2. ``proposed_stake`` does not exceed ``per_bet_cap_dollars``.
    3. Tournament cumulative shadow-live stake after this bet does not exceed
       ``per_tournament_cap_dollars``.

    Does NOT write anything — pure guard. The caller is responsible for the
    actual ``place_ticket_row`` call if this function returns without raising.
    """
    if not guardrail.enabled:
        raise ValueError(
            "Shadow-live mode is disabled. Set shadow_live.enabled: true in "
            "config/settings.yaml to allow real-stake shadow-live bets."
        )
    if proposed_stake <= 0:
        raise ValueError(f"Proposed stake must be positive, got {proposed_stake:.2f}.")
    if proposed_stake > guardrail.per_bet_cap_dollars:
        raise ValueError(
            f"Proposed stake ${proposed_stake:.2f} exceeds per-bet cap "
            f"${guardrail.per_bet_cap_dollars:.2f}."
        )
    already_staked = get_tournament_shadow_live_staked(session, tournament_id)
    if already_staked + proposed_stake > guardrail.per_tournament_cap_dollars:
        raise ValueError(
            f"Tournament shadow-live stake would reach "
            f"${already_staked + proposed_stake:.2f}, exceeding per-tournament "
            f"cap ${guardrail.per_tournament_cap_dollars:.2f}. "
            f"Already placed: ${already_staked:.2f}."
        )


def get_tournament_shadow_live_staked(session: Session, tournament_id: int) -> float:
    """Return the total ``actual_stake`` for shadow-live bets in this tournament.

    Used by guardrails and by the console summary panel.
    """
    rows = (
        session.query(PlacedBet)
        .join(BetTicket, BetTicket.ticket_id == PlacedBet.ticket_id)
        .join(BetCandidate, BetCandidate.candidate_id == BetTicket.candidate_id)
        .filter(
            BetCandidate.tournament_id == tournament_id,
            PlacedBet.placement_method == SHADOW_LIVE_METHOD,
        )
        .all()
    )
    return sum(row.actual_stake for row in rows)
