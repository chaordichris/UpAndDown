"""Execution layer for manual paper trading."""

from src.execution.candidates import build_ticket_from_candidate
from src.execution.persistence import (
    persist_clv,
    persist_placement,
    persist_settlement,
    persist_ticket,
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.execution.placement import PlacementLog, log_placement
from src.execution.settlement import SettlementLog, settle_placement
from src.execution.tickets import BetTicketDraft, generate_ticket, render_ticket

__all__ = [
    "BetTicketDraft",
    "PlacementLog",
    "SettlementLog",
    "build_ticket_from_candidate",
    "generate_ticket",
    "log_placement",
    "place_ticket_row",
    "persist_clv",
    "persist_placement",
    "persist_settlement",
    "persist_ticket",
    "record_clv_for_bet_row",
    "render_ticket",
    "settle_bet_row",
    "settle_placement",
]
