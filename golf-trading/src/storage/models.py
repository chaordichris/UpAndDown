"""
SQLAlchemy ORM models for UpAndDown.

All tables are append-only — rows are never updated or deleted.
New data creates new rows. Historical snapshots are preserved.

Table overview:
  tournaments       — PGA Tour events
  players           — canonical player registry
  player_aliases    — name variants per book/source
  raw_snapshots     — immutable API responses (DataGolf, books)
  normalized_odds   — transformed book lines in common format
  forecasts         — DataGolf probability forecasts per player/tournament
  fair_prices       — system-computed no-vig fair odds per market
  bet_candidates    — ranked edge opportunities output by edge detector
  bet_tickets       — risk-approved bet tickets (may not be placed)
  placed_bets       — bets actually placed with actual odds/stake
  bet_outcomes      — settlement results
  clv_snapshots     — closing line value calculations per placed bet
  bankroll_history  — daily bankroll state snapshot
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

class Tournament(Base):
    __tablename__ = "tournaments"

    tournament_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    course: Mapped[Optional[str]] = mapped_column(String(200))
    tour: Mapped[str] = mapped_column(String(50), nullable=False, default="pga")
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    purse_usd: Mapped[Optional[int]] = mapped_column(Integer)
    field_size: Mapped[Optional[int]] = mapped_column(Integer)
    datagolf_event_id: Mapped[Optional[str]] = mapped_column(String(100))
    # Status: scheduled, in_progress, completed, cancelled
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="tournament")
    raw_snapshots: Mapped[list["RawSnapshot"]] = relationship(back_populates="tournament")


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datagolf_player_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    name_canonical: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    aliases: Mapped[list["PlayerAlias"]] = relationship(back_populates="player")
    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="player")


class PlayerAlias(Base):
    """Maps book-specific player names to canonical player IDs."""
    __tablename__ = "player_aliases"
    __table_args__ = (UniqueConstraint("alias_name", "source", name="uq_alias_source"),)

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    # Source this alias came from: "dk", "fd", "datagolf", "manual"
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    alias_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    player: Mapped["Player"] = relationship(back_populates="aliases")


# ---------------------------------------------------------------------------
# Raw data (immutable, append-only)
# ---------------------------------------------------------------------------

class RawSnapshot(Base):
    """Complete, unmodified API response stored before any transformation."""
    __tablename__ = "raw_snapshots"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Source identifier: "datagolf", "dk", "fd"
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    # API endpoint or market type label
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    tournament_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("tournaments.tournament_id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Full JSON response as text
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    # False if response failed schema validation
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_errors: Mapped[Optional[str]] = mapped_column(Text)

    tournament: Mapped[Optional["Tournament"]] = relationship(back_populates="raw_snapshots")


# ---------------------------------------------------------------------------
# Normalized data
# ---------------------------------------------------------------------------

class NormalizedOdds(Base):
    """Book odds normalized to a common format with vig removed."""
    __tablename__ = "normalized_odds"

    odds_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, ForeignKey("raw_snapshots.snapshot_id"), nullable=False)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.tournament_id"), nullable=False)
    # Market type: matchup_2ball, matchup_3ball, make_cut, top_10, top_20, outright_win
    market_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Players involved (player_id_2 and _3 null for single-player markets)
    player_id_1: Mapped[int] = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    player_id_2: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player_id_3: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    # Which side of this market (player_1, player_2, player_3, tie)
    side: Mapped[str] = mapped_column(String(50), nullable=False)
    # Book identifier: "dk", "fd"
    book: Mapped[str] = mapped_column(String(50), nullable=False)
    american_odds: Mapped[Optional[int]] = mapped_column(Integer)
    decimal_odds: Mapped[Optional[float]] = mapped_column(Float)
    # Raw implied probability (includes vig)
    implied_prob: Mapped[float] = mapped_column(Float, nullable=False)
    # No-vig probability
    no_vig_prob: Mapped[Optional[float]] = mapped_column(Float)
    # Market hold as decimal (e.g., 0.05 = 5% hold)
    hold_pct: Mapped[Optional[float]] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Forecast(Base):
    """DataGolf probabilistic forecast for a player in a tournament."""
    __tablename__ = "forecasts"

    forecast_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, ForeignKey("raw_snapshots.snapshot_id"), nullable=False)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.tournament_id"), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    # Forecast type: win, top_5, top_10, top_20, make_cut
    forecast_type: Mapped[str] = mapped_column(String(50), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    datagolf_skill_rating: Mapped[Optional[float]] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    tournament: Mapped["Tournament"] = relationship(back_populates="forecasts")
    player: Mapped["Player"] = relationship(back_populates="forecasts")


# ---------------------------------------------------------------------------
# Pricing and edge detection
# ---------------------------------------------------------------------------

class FairPrice(Base):
    """System-computed no-vig fair odds for a market."""
    __tablename__ = "fair_prices"

    fair_price_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.tournament_id"), nullable=False)
    market_type: Mapped[str] = mapped_column(String(50), nullable=False)
    player_id_1: Mapped[int] = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    player_id_2: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player_id_3: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    side: Mapped[str] = mapped_column(String(50), nullable=False)
    fair_prob: Mapped[float] = mapped_column(Float, nullable=False)
    # Pricing method used: "datagolf_direct", "datagolf_derived"
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BetCandidate(Base):
    """A market with a detected edge — output of the edge detector."""
    __tablename__ = "bet_candidates"

    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.tournament_id"), nullable=False)
    market_type: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(50), nullable=False)
    player_id_1: Mapped[int] = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    player_id_2: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player_id_3: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    book: Mapped[str] = mapped_column(String(50), nullable=False)
    fair_prob: Mapped[float] = mapped_column(Float, nullable=False)
    # No-vig book probability
    book_prob: Mapped[float] = mapped_column(Float, nullable=False)
    # Edge = fair_prob - book_prob (positive = we have the edge)
    edge_pct: Mapped[float] = mapped_column(Float, nullable=False)
    # 0.0 to 1.0 confidence score from meta-model (Stage 3; initially just 1.0)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # True if data was older than staleness threshold
    staleness_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class BetTicket(Base):
    """Risk-approved bet ticket with sizing. May or may not be placed."""
    __tablename__ = "bet_tickets"

    ticket_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("bet_candidates.candidate_id"), nullable=False)
    # Sleeve: "core" or "convex"
    sleeve: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_stake: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_american_odds: Mapped[Optional[int]] = mapped_column(Integer)
    kelly_fraction_used: Mapped[Optional[float]] = mapped_column(Float)
    # Sizing method: "fractional_kelly", "fixed_unit"
    sizing_method: Mapped[str] = mapped_column(String(50), nullable=False)
    # True = passed all risk checks, False = blocked
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PlacedBet(Base):
    """A bet actually placed by the user (manual or automated)."""
    __tablename__ = "placed_bets"

    bet_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("bet_tickets.ticket_id"), nullable=False)
    book: Mapped[str] = mapped_column(String(50), nullable=False)
    actual_american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_stake: Mapped[float] = mapped_column(Float, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # "manual" for MVP; "automated" later
    placement_method: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")


class BetOutcome(Base):
    """Settlement result for a placed bet."""
    __tablename__ = "bet_outcomes"

    outcome_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bet_id: Mapped[int] = mapped_column(Integer, ForeignKey("placed_bets.bet_id"), nullable=False, unique=True)
    # Result: win, loss, push, void, dead_heat
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    # Gross payout (0 for a loss)
    payout: Mapped[float] = mapped_column(Float, nullable=False)
    # Net profit/loss (payout - stake)
    profit_loss: Mapped[float] = mapped_column(Float, nullable=False)
    settled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    settlement_notes: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Performance tracking
# ---------------------------------------------------------------------------

class CLVSnapshot(Base):
    """Closing Line Value calculation for a placed bet."""
    __tablename__ = "clv_snapshots"

    clv_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bet_id: Mapped[int] = mapped_column(Integer, ForeignKey("placed_bets.bet_id"), nullable=False, unique=True)
    # Closing odds (last available before event starts)
    closing_american_odds: Mapped[Optional[int]] = mapped_column(Integer)
    closing_implied_prob: Mapped[Optional[float]] = mapped_column(Float)
    # Implied prob at time of placement
    placement_implied_prob: Mapped[float] = mapped_column(Float, nullable=False)
    # Raw CLV: closing_implied_prob - placement_implied_prob (positive = beat the close)
    clv_raw: Mapped[Optional[float]] = mapped_column(Float)
    # Model CLV: our_fair_prob - closing_implied_prob
    clv_model: Mapped[Optional[float]] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BankrollHistory(Base):
    """Daily snapshot of bankroll state."""
    __tablename__ = "bankroll_history"

    entry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, unique=True)
    total_capital: Mapped[float] = mapped_column(Float, nullable=False)
    reserve: Mapped[float] = mapped_column(Float, nullable=False)
    active_core: Mapped[float] = mapped_column(Float, nullable=False)
    convex_sleeve: Mapped[float] = mapped_column(Float, nullable=False)
    # Peak active_core value (for drawdown calculation)
    active_core_peak: Mapped[float] = mapped_column(Float, nullable=False)
    # Drawdown from peak as positive decimal (e.g., 0.12 = 12% drawdown)
    drawdown_from_peak_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # State: normal, reduced, severe, paper_only, halted
    drawdown_state: Mapped[str] = mapped_column(String(50), nullable=False, default="normal")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
