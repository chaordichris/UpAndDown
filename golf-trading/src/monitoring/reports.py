"""Small reporting helpers for Phase 3 paper trading."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

from sqlalchemy.orm import Session

from src.execution.settlement import SettlementLog
from src.execution.tickets import BetTicketDraft
from src.monitoring.clv import CLVResult
from src.storage.models import (
    BetAttribution,
    BetCandidate,
    BetOutcome,
    BetTicket,
    CLVSnapshot,
    PlacedBet,
    Player,
    Tournament,
)

# placement_method values that are real-money but not paper-gate evidence.
# These are intentional operational placements, not synthetic contamination.
_SHADOW_LIVE_METHOD: str = "shadow_live"

# placement_method values that belong to paper-trade gate evidence.
_PAPER_METHODS: frozenset[str] = frozenset({"manual"})
# placement_method values that ARE contamination (synthetic / test data).
_CONTAMINATING_METHODS: frozenset[str] = frozenset({"backtest"})


@dataclass(frozen=True)
class PaperTradeReport:
    """Aggregate paper-trading metrics for a batch of settled tickets."""

    ticket_count: int
    approved_count: int
    settled_count: int
    total_staked: float
    total_profit_loss: float
    roi: float
    average_edge: float
    average_clv_raw: float | None
    positive_clv_rate: float | None


@dataclass(frozen=True)
class StoredPaperTradeReport:
    """Aggregate paper-trading metrics from persisted DB rows."""

    ticket_count: int
    approved_count: int
    open_ticket_count: int
    placed_count: int
    settled_count: int
    pending_settlement_count: int
    clv_count: int
    missing_clv_count: int
    total_staked: float
    open_approved_stake: float
    total_profit_loss: float
    strategy_profit_loss: float
    promo_profit_loss: float
    roi: float
    strategy_roi: float
    average_edge: float | None
    average_clv_raw: float | None
    positive_clv_rate: float | None
    attribution_count: int
    model_alpha: float
    execution_drift: float
    sizing_alpha: float
    variance: float


@dataclass(frozen=True)
class ReadinessCriterion:
    """One paper-trading readiness check for operator review."""

    name: str
    passed: bool
    observed: str
    required: str


@dataclass(frozen=True)
class Phase3ReadinessReport:
    """Operational readiness summary before running the Phase 3 gate."""

    passed: bool
    settled_tournament_count: int
    open_approved_ticket_count: int
    criteria: list[ReadinessCriterion]
    report: StoredPaperTradeReport


@dataclass(frozen=True)
class Phase3EvidenceReport:
    """Operator evidence guardrail before assembling Phase 3 gate artifacts."""

    passed: bool
    evidence_clean: bool
    contamination_count: int
    criteria: list[ReadinessCriterion]
    readiness: Phase3ReadinessReport


@dataclass(frozen=True)
class ShadowLiveSummary:
    """Aggregate metrics for shadow-live (real-stake) bets in the DB.

    Shadow-live bets are excluded from the paper-trade gate evidence metrics.
    This summary is informational only — not a gate criterion.
    """

    bet_count: int
    total_staked: float
    settled_count: int
    total_profit_loss: float
    roi: float


def build_paper_trade_report(
    tickets: list[BetTicketDraft],
    settlements: list[SettlementLog],
    clv_results: list[CLVResult] | None = None,
) -> PaperTradeReport:
    """Summarize tickets, settlement P&L, and optional CLV."""
    approved = [ticket for ticket in tickets if ticket.approved]
    total_staked = sum(s.stake for s in settlements)
    total_profit_loss = sum(s.profit_loss for s in settlements)
    clvs = clv_results or []

    return PaperTradeReport(
        ticket_count=len(tickets),
        approved_count=len(approved),
        settled_count=len(settlements),
        total_staked=round(total_staked, 2),
        total_profit_loss=round(total_profit_loss, 2),
        roi=0.0 if total_staked == 0 else total_profit_loss / total_staked,
        average_edge=0.0 if not tickets else sum(t.edge for t in tickets) / len(tickets),
        average_clv_raw=None if not clvs else sum(c.clv_raw for c in clvs) / len(clvs),
        positive_clv_rate=None if not clvs else sum(c.clv_raw > 0 for c in clvs) / len(clvs),
    )


def build_phase3_readiness_report(
    session: Session,
    *,
    required_tournaments: int = 4,
    required_settled_bets: int = 60,
) -> Phase3ReadinessReport:
    """Summarize whether the paper DB is ready for Phase 3 gate review."""
    report = build_stored_paper_trade_report(session)
    settled_tournament_count = _settled_tournament_count(session)
    open_approved_ticket_count = _open_approved_ticket_count(session)
    missing_attribution_count = report.settled_count - report.attribution_count
    criteria = [
        ReadinessCriterion(
            name="paper_tournaments",
            passed=settled_tournament_count >= required_tournaments,
            observed=str(settled_tournament_count),
            required=f">= {required_tournaments}",
        ),
        ReadinessCriterion(
            name="settled_bets",
            passed=report.settled_count >= required_settled_bets,
            observed=str(report.settled_count),
            required=f">= {required_settled_bets}",
        ),
        ReadinessCriterion(
            name="open_approved_tickets",
            passed=open_approved_ticket_count == 0,
            observed=str(open_approved_ticket_count),
            required="0",
        ),
        ReadinessCriterion(
            name="pending_settlements",
            passed=report.pending_settlement_count == 0,
            observed=str(report.pending_settlement_count),
            required="0",
        ),
        ReadinessCriterion(
            name="missing_clv",
            passed=report.missing_clv_count == 0,
            observed=str(report.missing_clv_count),
            required="0",
        ),
        ReadinessCriterion(
            name="missing_attribution",
            passed=missing_attribution_count == 0,
            observed=str(missing_attribution_count),
            required="0",
        ),
    ]
    return Phase3ReadinessReport(
        passed=all(criterion.passed for criterion in criteria),
        settled_tournament_count=settled_tournament_count,
        open_approved_ticket_count=open_approved_ticket_count,
        criteria=criteria,
        report=report,
    )


def build_phase3_evidence_report(
    session: Session,
    *,
    required_tournaments: int = 4,
    required_settled_bets: int = 60,
) -> Phase3EvidenceReport:
    """Check that Phase 3 review evidence is real operator-entered paper data."""
    readiness = build_phase3_readiness_report(
        session,
        required_tournaments=required_tournaments,
        required_settled_bets=required_settled_bets,
    )
    smoke_tournaments = _smoke_tournament_count(session)
    suspicious_hashes = _suspicious_inputs_hash_count(session)
    non_manual_placements = _non_manual_placement_count(session)
    suspicious_notes = _suspicious_note_count(session)
    contamination_count = (
        smoke_tournaments
        + suspicious_hashes
        + non_manual_placements
        + suspicious_notes
    )
    criteria = [
        ReadinessCriterion(
            name="phase3_readiness",
            passed=readiness.passed,
            observed="passed" if readiness.passed else "not_ready",
            required="passed",
        ),
        ReadinessCriterion(
            name="no_smoke_tournaments",
            passed=smoke_tournaments == 0,
            observed=str(smoke_tournaments),
            required="0",
        ),
        ReadinessCriterion(
            name="no_smoke_fixture_hashes",
            passed=suspicious_hashes == 0,
            observed=str(suspicious_hashes),
            required="0",
        ),
        ReadinessCriterion(
            name="manual_placements_only",
            passed=non_manual_placements == 0,
            observed=str(non_manual_placements),
            required="0",
        ),
        ReadinessCriterion(
            name="no_smoke_fixture_notes",
            passed=suspicious_notes == 0,
            observed=str(suspicious_notes),
            required="0",
        ),
    ]
    evidence_clean = contamination_count == 0
    return Phase3EvidenceReport(
        passed=evidence_clean and readiness.passed,
        evidence_clean=evidence_clean,
        contamination_count=contamination_count,
        criteria=criteria,
        readiness=readiness,
    )


def build_stored_paper_trade_report(
    session: Session,
    placement_methods: frozenset[str] = _PAPER_METHODS,
) -> StoredPaperTradeReport:
    """Summarize the persisted paper-trading database state.

    By default, only includes bets with a paper placement method (``manual``).
    Backtest callers can pass ``placement_methods=frozenset({"backtest"})`` to
    build replay reports without contaminating paper-gate evidence.
    """
    tickets = session.query(BetTicket).all()
    all_placed = session.query(PlacedBet).all()
    placed_bets = [b for b in all_placed if b.placement_method in placement_methods]
    paper_bet_ids = {b.bet_id for b in placed_bets}
    all_outcomes = session.query(BetOutcome).all()
    outcomes = [o for o in all_outcomes if o.bet_id in paper_bet_ids]
    all_clvs = session.query(CLVSnapshot).all()
    clvs = [c for c in all_clvs if c.bet_id in paper_bet_ids]
    all_attributions = session.query(BetAttribution).all()
    attributions = [a for a in all_attributions if a.bet_id in paper_bet_ids]

    placed_ticket_ids = {bet.ticket_id for bet in placed_bets}
    settled_bet_ids = {outcome.bet_id for outcome in outcomes}
    clv_bet_ids = {clv.bet_id for clv in clvs}
    candidate_ids = [ticket.candidate_id for ticket in tickets]
    candidates = (
        session.query(BetCandidate).filter(BetCandidate.candidate_id.in_(candidate_ids)).all()
        if candidate_ids
        else []
    )

    approved_tickets = [ticket for ticket in tickets if ticket.approved]
    open_tickets = [ticket for ticket in tickets if ticket.ticket_id not in placed_ticket_ids]
    total_staked = sum(bet.actual_stake for bet in placed_bets)
    total_profit_loss = sum(outcome.profit_loss for outcome in outcomes)
    strategy_profit_loss = sum(outcome.profit_loss_raw for outcome in outcomes)
    promo_profit_loss = total_profit_loss - strategy_profit_loss
    clv_values = [clv.clv_raw for clv in clvs if clv.clv_raw is not None]
    edge_values = [candidate.edge_pct for candidate in candidates]

    return StoredPaperTradeReport(
        ticket_count=len(tickets),
        approved_count=len(approved_tickets),
        open_ticket_count=len(open_tickets),
        placed_count=len(placed_bets),
        settled_count=len(outcomes),
        pending_settlement_count=sum(bet.bet_id not in settled_bet_ids for bet in placed_bets),
        clv_count=len(clvs),
        missing_clv_count=sum(bet.bet_id not in clv_bet_ids for bet in placed_bets),
        total_staked=round(total_staked, 2),
        open_approved_stake=round(sum(ticket.proposed_stake for ticket in open_tickets if ticket.approved), 2),
        total_profit_loss=round(total_profit_loss, 2),
        strategy_profit_loss=round(strategy_profit_loss, 2),
        promo_profit_loss=round(promo_profit_loss, 2),
        roi=0.0 if total_staked == 0 else total_profit_loss / total_staked,
        strategy_roi=0.0 if total_staked == 0 else strategy_profit_loss / total_staked,
        average_edge=None if not edge_values else sum(edge_values) / len(edge_values),
        average_clv_raw=None if not clv_values else sum(clv_values) / len(clv_values),
        positive_clv_rate=None if not clv_values else sum(value > 0 for value in clv_values) / len(clv_values),
        attribution_count=len(attributions),
        model_alpha=round(sum(row.model_alpha for row in attributions), 2),
        execution_drift=round(sum(row.execution_drift for row in attributions), 2),
        sizing_alpha=round(sum(row.sizing_alpha for row in attributions), 2),
        variance=round(sum(row.variance for row in attributions), 2),
    )


def build_shadow_live_summary(session: Session) -> ShadowLiveSummary:
    """Summarize shadow-live (real-stake) bets in the DB.

    Informational only — not included in Phase 3 gate metrics.
    """
    shadow_bets = [
        bet
        for bet in session.query(PlacedBet).all()
        if bet.placement_method == _SHADOW_LIVE_METHOD
    ]
    shadow_bet_ids = {bet.bet_id for bet in shadow_bets}
    outcomes = [
        outcome
        for outcome in session.query(BetOutcome).all()
        if outcome.bet_id in shadow_bet_ids
    ]
    total_staked = sum(bet.actual_stake for bet in shadow_bets)
    total_profit_loss = sum(o.profit_loss for o in outcomes)
    return ShadowLiveSummary(
        bet_count=len(shadow_bets),
        total_staked=round(total_staked, 2),
        settled_count=len(outcomes),
        total_profit_loss=round(total_profit_loss, 2),
        roi=0.0 if total_staked == 0 else total_profit_loss / total_staked,
    )


def render_phase3_readiness_report(readiness: Phase3ReadinessReport) -> str:
    """Render Phase 3 readiness for terminal operator review."""
    lines = [
        "Phase 3 Readiness",
        f"Status: {'READY' if readiness.passed else 'NOT READY'}",
        f"Settled tournaments: {readiness.settled_tournament_count}",
        f"Settled bets: {readiness.report.settled_count}",
    ]
    for criterion in readiness.criteria:
        status = "PASS" if criterion.passed else "FAIL"
        lines.append(
            f"{status} {criterion.name}: observed {criterion.observed}, required {criterion.required}"
        )
    return "\n".join(lines)


def render_phase3_evidence_report(evidence: Phase3EvidenceReport) -> str:
    """Render the Phase 3 evidence guardrail for terminal operator review."""
    lines = [
        "Phase 3 Evidence Check",
        f"Status: {'READY' if evidence.passed else 'NOT READY'}",
        f"Evidence clean: {'YES' if evidence.evidence_clean else 'NO'}",
        f"Contamination count: {evidence.contamination_count}",
        f"Settled tournaments: {evidence.readiness.settled_tournament_count}",
        f"Settled bets: {evidence.readiness.report.settled_count}",
    ]
    for criterion in evidence.criteria:
        status = "PASS" if criterion.passed else "FAIL"
        lines.append(
            f"{status} {criterion.name}: observed {criterion.observed}, required {criterion.required}"
        )
    return "\n".join(lines)


def render_stored_report(report: StoredPaperTradeReport) -> str:
    """Render persisted paper-trading metrics for terminal output."""
    return "\n".join(
        [
            "Paper Trade Report",
            f"Tickets: {report.ticket_count} total, {report.approved_count} approved, {report.open_ticket_count} open",
            (
                f"Bets: {report.placed_count} placed, {report.settled_count} settled, "
                f"{report.pending_settlement_count} pending settlement"
            ),
            f"CLV: {report.clv_count} recorded, {report.missing_clv_count} missing",
            f"Staked: ${report.total_staked:.2f}",
            f"Open approved stake: ${report.open_approved_stake:.2f}",
            f"Strategy P&L: ${report.strategy_profit_loss:.2f}",
            f"Promo P&L: ${report.promo_profit_loss:.2f}",
            f"Realized P&L: ${report.total_profit_loss:.2f}",
            f"Strategy ROI: {report.strategy_roi:.2%}",
            f"Realized ROI: {report.roi:.2%}",
            f"Average edge: {_format_optional_pct(report.average_edge)}",
            f"Average raw CLV: {_format_optional_pct(report.average_clv_raw)}",
            f"Positive CLV rate: {_format_optional_pct(report.positive_clv_rate)}",
            f"Attribution rows: {report.attribution_count}",
            f"Model alpha: ${report.model_alpha:.2f}",
            f"Execution drift: ${report.execution_drift:.2f}",
            f"Sizing alpha: ${report.sizing_alpha:.2f}",
            f"Variance: ${report.variance:.2f}",
        ]
    )


def _format_optional_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def render_ticket_detail(session: Session, ticket_id: int) -> str:
    """Render one persisted ticket as a manual bet slip."""
    ticket = _require(session, BetTicket, ticket_id, "ticket")
    candidate = _require(session, BetCandidate, ticket.candidate_id, "candidate")
    tournament = session.get(Tournament, candidate.tournament_id)
    primary = session.get(Player, candidate.player_id_1)
    opponent = session.get(Player, candidate.player_id_2) if candidate.player_id_2 else None
    placed = session.query(PlacedBet).filter_by(ticket_id=ticket.ticket_id).one_or_none()

    status = "placed" if placed is not None else "open"
    approved = "approved" if ticket.approved else "rejected"
    opponent_text = f" vs {_player_name(opponent)}" if opponent else ""

    lines = [
        f"Ticket {ticket.ticket_id} [{approved}, {status}]",
        f"Tournament: {_tournament_name(tournament)}",
        f"Market: {candidate.market_type} - {_player_name(primary)}{opponent_text}",
        f"Book: {candidate.book}",
        f"Side: {candidate.side} {ticket.proposed_american_odds:+d}",
        f"Stake: ${ticket.proposed_stake:.2f}",
        f"Fair probability: {candidate.fair_prob:.3f}",
        (
            f"Book no-vig probability: {candidate.book_prob:.3f}"
            if candidate.vig_removed
            else f"Book implied probability (vig NOT removed): {candidate.book_prob:.3f}"
        ),
        f"Edge: {candidate.edge_pct:.2%}",
        f"Sleeve: {ticket.sleeve}",
        f"Sizing: {ticket.sizing_method}",
    ]
    if ticket.kelly_fraction_used is not None:
        lines.append(f"Kelly fraction: {ticket.kelly_fraction_used:.4f}")
    if ticket.rejection_reason:
        lines.append(f"Rejection reason: {ticket.rejection_reason}")
    if placed:
        lines.append(f"Placed bet id: {placed.bet_id}")
    return "\n".join(lines)


def export_tickets_csv(
    session: Session,
    *,
    unplaced_only: bool = False,
    approved_only: bool = False,
) -> str:
    """Export persisted tickets as CSV for manual execution."""
    placed_ticket_ids = {row.ticket_id for row in session.query(PlacedBet.ticket_id).all()}
    tickets = session.query(BetTicket).order_by(BetTicket.ticket_id).all()

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "ticket_id",
            "candidate_id",
            "status",
            "approved",
            "tournament",
            "market_type",
            "book",
            "side",
            "american_odds",
            "stake",
            "fair_prob",
            "book_prob",
            "vig_removed",
            "edge_pct",
            "sleeve",
            "sizing_method",
            "rejection_reason",
        ],
    )
    writer.writeheader()
    for ticket in tickets:
        if unplaced_only and ticket.ticket_id in placed_ticket_ids:
            continue
        if approved_only and not ticket.approved:
            continue
        candidate = _require(session, BetCandidate, ticket.candidate_id, "candidate")
        tournament = session.get(Tournament, candidate.tournament_id)
        writer.writerow(
            {
                "ticket_id": ticket.ticket_id,
                "candidate_id": ticket.candidate_id,
                "status": "placed" if ticket.ticket_id in placed_ticket_ids else "open",
                "approved": ticket.approved,
                "tournament": _tournament_name(tournament),
                "market_type": candidate.market_type,
                "book": candidate.book,
                "side": candidate.side,
                "american_odds": ticket.proposed_american_odds,
                "stake": f"{ticket.proposed_stake:.2f}",
                "fair_prob": f"{candidate.fair_prob:.6f}",
                "book_prob": f"{candidate.book_prob:.6f}",
                "vig_removed": candidate.vig_removed,
                "edge_pct": f"{candidate.edge_pct:.6f}",
                "sleeve": ticket.sleeve,
                "sizing_method": ticket.sizing_method,
                "rejection_reason": ticket.rejection_reason or "",
            }
        )
    return output.getvalue()


def render_open_actions(session: Session) -> str:
    """Render unresolved operator actions for paper trading."""
    placed_bets = session.query(PlacedBet).all()
    placed_ticket_ids = {bet.ticket_id for bet in placed_bets}
    settled_bet_ids = {outcome.bet_id for outcome in session.query(BetOutcome).all()}
    clv_bet_ids = {clv.bet_id for clv in session.query(CLVSnapshot).all()}
    attribution_bet_ids = {row.bet_id for row in session.query(BetAttribution).all()}

    open_tickets = [
        ticket
        for ticket in session.query(BetTicket).order_by(BetTicket.ticket_id).all()
        if ticket.approved and ticket.ticket_id not in placed_ticket_ids
    ]
    rejected_tickets = [
        ticket
        for ticket in session.query(BetTicket).order_by(BetTicket.ticket_id).all()
        if not ticket.approved
    ]
    pending_settlement = [bet for bet in placed_bets if bet.bet_id not in settled_bet_ids]
    missing_clv = [bet for bet in placed_bets if bet.bet_id not in clv_bet_ids]
    missing_attribution = [
        bet
        for bet in placed_bets
        if bet.bet_id in settled_bet_ids and bet.bet_id not in attribution_bet_ids
    ]

    lines = ["Open Actions"]
    lines.append(f"Tickets to place: {len(open_tickets)}")
    for ticket in open_tickets:
        lines.append(f"  ticket_id={ticket.ticket_id} stake=${ticket.proposed_stake:.2f}")
    lines.append(f"Bets pending settlement: {len(pending_settlement)}")
    for bet in pending_settlement:
        lines.append(f"  bet_id={bet.bet_id} ticket_id={bet.ticket_id}")
    lines.append(f"Bets missing CLV: {len(missing_clv)}")
    for bet in missing_clv:
        lines.append(f"  bet_id={bet.bet_id} ticket_id={bet.ticket_id}")
    lines.append(f"Bets missing attribution: {len(missing_attribution)}")
    for bet in missing_attribution:
        lines.append(f"  bet_id={bet.bet_id} ticket_id={bet.ticket_id}")
    lines.append(f"Rejected tickets: {len(rejected_tickets)}")
    for ticket in rejected_tickets:
        reason = ticket.rejection_reason or "unknown"
        lines.append(f"  ticket_id={ticket.ticket_id} reason={reason}")
    return "\n".join(lines)


def _settled_tournament_count(session: Session) -> int:
    """Count distinct tournaments with at least one settled paper bet.

    Only paper placements (``manual``) count toward the Phase 3 gate evidence
    tournament tally. Shadow-live and backtest bets are excluded.
    """
    tournament_ids: set[int] = set()
    outcomes = session.query(BetOutcome).all()
    for outcome in outcomes:
        placed = session.get(PlacedBet, outcome.bet_id)
        if placed is None or placed.placement_method not in _PAPER_METHODS:
            continue
        ticket = session.get(BetTicket, placed.ticket_id)
        if ticket is None:
            continue
        candidate = session.get(BetCandidate, ticket.candidate_id)
        if candidate is not None:
            tournament_ids.add(candidate.tournament_id)
    return len(tournament_ids)


def _open_approved_ticket_count(session: Session) -> int:
    placed_ticket_ids = {row.ticket_id for row in session.query(PlacedBet.ticket_id).all()}
    return sum(
        ticket.approved and ticket.ticket_id not in placed_ticket_ids
        for ticket in session.query(BetTicket).all()
    )


def _smoke_tournament_count(session: Session) -> int:
    return sum(
        _contains_non_review_token(tournament.name)
        or _contains_non_review_token(tournament.datagolf_event_id)
        for tournament in session.query(Tournament).all()
    )


def _suspicious_inputs_hash_count(session: Session) -> int:
    rows = [
        *session.query(BetCandidate).all(),
        *session.query(BetTicket).all(),
        *session.query(PlacedBet).all(),
        *session.query(BetOutcome).all(),
        *session.query(CLVSnapshot).all(),
        *session.query(BetAttribution).all(),
    ]
    return sum(_contains_non_review_token(row.inputs_hash) for row in rows)


def _non_manual_placement_count(session: Session) -> int:
    """Count placed bets with contaminating placement methods.

    Shadow-live bets (``shadow_live``) are intentional real-money placements
    and are NOT contamination. Only synthetic/replay placements (``backtest``)
    are treated as contamination in the Phase 3 evidence guardrail.
    """
    return sum(
        bet.placement_method in _CONTAMINATING_METHODS
        for bet in session.query(PlacedBet).all()
    )


def _suspicious_note_count(session: Session) -> int:
    placed_bets = session.query(PlacedBet).all()
    outcomes = session.query(BetOutcome).all()
    return sum(_contains_non_review_token(bet.notes) for bet in placed_bets) + sum(
        _contains_non_review_token(outcome.settlement_notes)
        for outcome in outcomes
    )


def _contains_non_review_token(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    return any(token in lowered for token in ("smoke", "fixture", "backtest"))


def _require(session: Session, model, row_id: int, label: str):
    row = session.get(model, row_id)
    if row is None:
        raise ValueError(f"Unknown {label}_id={row_id}")
    return row


def _player_name(player: Player | None) -> str:
    return "unknown" if player is None else player.name_canonical


def _tournament_name(tournament: Tournament | None) -> str:
    return "unknown" if tournament is None else tournament.name
