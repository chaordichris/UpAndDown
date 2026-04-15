"""
Exposure and concentration control.

Enforces three per-bet limits before a bet is approved:

  1. Per-golfer: total stake on any single player (across all markets) must
     not exceed max_golfer_fraction × active_bankroll.

  2. Per-tournament: total stake in any single tournament must not exceed
     max_tournament_fraction × total_bankroll.

  3. Per-book: total stake at any single sportsbook must not exceed
     max_book_fraction × total_bankroll.

The check is purely functional — it receives summaries of the current open
book (pre-aggregated by the caller from the DB) and the proposed bet, and
returns an approval decision. No DB access here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenBookSummary:
    """Caller-supplied summary of current open bet exposure.

    Callers query the DB and aggregate these totals before calling
    check_exposure().
    """

    golfer_stakes: dict[str, float]      # datagolf_id → total $ staked
    tournament_stakes: dict[str, float]  # tournament_id → total $ staked
    book_stakes: dict[str, float]        # book_id → total $ staked


@dataclass(frozen=True)
class ExposureDecision:
    """Result of an exposure check for one proposed bet."""

    approved: bool
    reason: str   # always populated; explains approval or rejection


def check_exposure(
    datagolf_id: str,
    tournament_id: str,
    book_id: str,
    proposed_stake: float,
    open_book: OpenBookSummary,
    active_bankroll: float,
    total_bankroll: float,
    max_golfer_fraction: float,
    max_tournament_fraction: float,
    max_book_fraction: float,
) -> ExposureDecision:
    """Check whether a proposed bet breaches any exposure limit.

    Args:
        datagolf_id: The primary player this bet is on.
        tournament_id: Tournament identifier (string, for aggregation).
        book_id: Sportsbook identifier.
        proposed_stake: Dollar amount of the proposed bet.
        open_book: Current exposure summary (from DB queries).
        active_bankroll: Current active-core bankroll.
        total_bankroll: Total bankroll.
        max_golfer_fraction: Limit per player as fraction of active_bankroll.
        max_tournament_fraction: Limit per tournament as fraction of total_bankroll.
        max_book_fraction: Limit per book as fraction of total_bankroll.

    Returns:
        ExposureDecision. If rejected, reason names the breached limit.
    """
    # 1. Per-golfer check
    current_golfer = open_book.golfer_stakes.get(datagolf_id, 0.0)
    golfer_limit = max_golfer_fraction * active_bankroll
    if current_golfer + proposed_stake > golfer_limit:
        return ExposureDecision(
            approved=False,
            reason=(
                f"Golfer limit breach: {datagolf_id!r} would reach "
                f"${current_golfer + proposed_stake:.2f} "
                f"(limit ${golfer_limit:.2f} = "
                f"{max_golfer_fraction*100:.0f}% × ${active_bankroll:.0f})."
            ),
        )

    # 2. Per-tournament check
    current_tournament = open_book.tournament_stakes.get(tournament_id, 0.0)
    tournament_limit = max_tournament_fraction * total_bankroll
    if current_tournament + proposed_stake > tournament_limit:
        return ExposureDecision(
            approved=False,
            reason=(
                f"Tournament limit breach: {tournament_id!r} would reach "
                f"${current_tournament + proposed_stake:.2f} "
                f"(limit ${tournament_limit:.2f})."
            ),
        )

    # 3. Per-book check
    current_book = open_book.book_stakes.get(book_id, 0.0)
    book_limit = max_book_fraction * total_bankroll
    if current_book + proposed_stake > book_limit:
        return ExposureDecision(
            approved=False,
            reason=(
                f"Book limit breach: {book_id!r} would reach "
                f"${current_book + proposed_stake:.2f} "
                f"(limit ${book_limit:.2f})."
            ),
        )

    return ExposureDecision(
        approved=True,
        reason=(
            f"Approved. Golfer ${current_golfer + proposed_stake:.2f}/{golfer_limit:.2f}, "
            f"tournament ${current_tournament + proposed_stake:.2f}/{tournament_limit:.2f}, "
            f"book ${current_book + proposed_stake:.2f}/{book_limit:.2f}."
        ),
    )
