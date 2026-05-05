"""Local Phase 3 paper-trading operator console."""

from __future__ import annotations

import argparse
import html
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from src.config import get_settings
from src.execution.candidates import ticket_unticketed_candidates
from src.execution.persistence import (
    place_ticket_row,
    record_clv_for_bet_row,
    settle_bet_row,
)
from src.monitoring.attribution import record_attribution_for_bet_row
from src.monitoring.reports import (
    build_phase3_evidence_report,
    build_phase3_readiness_report,
    build_stored_paper_trade_report,
    render_open_actions,
)
from src.storage.db import get_session, init_db
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


def build_dashboard_html(database_url: str | None, *, message: str | None = None) -> str:
    """Render the complete operator dashboard HTML."""
    init_db(database_url)
    with get_session(database_url) as session:
        report = build_stored_paper_trade_report(session)
        readiness = build_phase3_readiness_report(session)
        evidence = build_phase3_evidence_report(session)
        candidates = session.query(BetCandidate).order_by(BetCandidate.candidate_id).all()
        tickets = session.query(BetTicket).order_by(BetTicket.ticket_id).all()
        placed_bets = session.query(PlacedBet).order_by(PlacedBet.bet_id).all()
        placed_ticket_ids = {bet.ticket_id for bet in placed_bets}
        outcomes_by_bet = {
            outcome.bet_id: outcome
            for outcome in session.query(BetOutcome).order_by(BetOutcome.outcome_id).all()
        }
        clv_by_bet = {
            clv.bet_id: clv
            for clv in session.query(CLVSnapshot).order_by(CLVSnapshot.clv_id).all()
        }
        attribution_by_bet = {
            row.bet_id: row
            for row in session.query(BetAttribution).order_by(BetAttribution.attribution_id).all()
        }
        ticket_by_id = {ticket.ticket_id: ticket for ticket in tickets}
        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in candidates
        }
        tournament_by_id = {
            tournament.tournament_id: tournament
            for tournament in session.query(Tournament).order_by(Tournament.tournament_id).all()
        }
        player_by_id = {
            player.player_id: player
            for player in session.query(Player).order_by(Player.player_id).all()
        }
        actions = render_open_actions(session)

    return _page(
        title="UpAndDown Operator Console",
        body="\n".join(
            [
                _header(database_url, message=message),
                _summary_section(report, readiness, evidence),
                _action_section(),
                _candidate_section(candidates, tournament_by_id, player_by_id),
                _ticket_section(tickets, placed_ticket_ids, candidate_by_id, tournament_by_id, player_by_id),
                _bet_section(
                    placed_bets,
                    ticket_by_id,
                    candidate_by_id,
                    tournament_by_id,
                    player_by_id,
                    outcomes_by_bet,
                    clv_by_bet,
                    attribution_by_bet,
                ),
                _open_actions_section(actions),
            ]
        ),
    )


def make_handler(database_url: str | None) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one database URL."""

    class OperatorConsoleHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/index.html"}:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown route")
                return
            query = parse_qs(parsed.query)
            message = query.get("message", [None])[0]
            self._send_html(build_dashboard_html(database_url, message=message))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                message = _handle_post(parsed.path, form, database_url)
            except Exception as exc:  # noqa: BLE001
                message = f"Error: {exc}"
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/?{urlencode({'message': message})}")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return OperatorConsoleHandler


def _handle_post(path: str, form: dict[str, list[str]], database_url: str | None) -> str:
    init_db(database_url)
    with get_session(database_url) as session:
        if path == "/ticket-candidates":
            return _post_ticket_candidates(session, form)
        if path == "/place-ticket":
            return _post_place_ticket(session, form)
        if path == "/settle-bet":
            return _post_settle_bet(session, form)
        if path == "/record-clv":
            return _post_record_clv(session, form)
        if path == "/record-attribution":
            return _post_record_attribution(session, form)
    raise ValueError(f"Unknown action {path!r}")


def _post_ticket_candidates(session, form: dict[str, list[str]]) -> str:
    settings = get_settings()
    rows = ticket_unticketed_candidates(
        session,
        total_bankroll=_float_field(form, "total_bankroll"),
        reserve_fraction=settings.bankroll.reserve_fraction,
        active_core_fraction=settings.bankroll.active_core_fraction,
        convex_fraction=settings.bankroll.convex_fraction,
        kelly_multiplier=settings.sizing.kelly_fraction,
        convex_unit_fraction=settings.sizing.convex_unit_fraction,
        min_bet_dollars=settings.sizing.min_bet_dollars,
        max_bet_fraction=settings.sizing.max_bet_fraction,
        min_edge_core=settings.edge.min_edge_core,
        min_edge_convex=settings.edge.min_edge_convex,
        posterior_kelly_enabled=settings.sizing.posterior_kelly_enabled,
        fdr_enabled=settings.edge.fdr_enabled,
        tournament_id=_optional_int_field(form, "tournament_id"),
        limit=_optional_int_field(form, "limit"),
        created_at=datetime.now(UTC),
    )
    return f"Created {len(rows)} ticket(s)."


def _post_place_ticket(session, form: dict[str, list[str]]) -> str:
    ticket = _require_row(session, BetTicket, _int_field(form, "ticket_id"), "ticket")
    candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
    placed = place_ticket_row(
        session,
        ticket,
        candidate,
        actual_american_odds=_optional_int_field(form, "actual_odds"),
        actual_stake=_optional_float_field(form, "actual_stake"),
        placed_at=datetime.now(UTC),
        notes=_optional_text_field(form, "notes"),
        bet_class=_text_field(form, "bet_class", default="STANDARD"),
        boost_terms_json=_optional_text_field(form, "boost_terms_json"),
    )
    return f"Placed ticket {ticket.ticket_id} as bet {placed.bet_id}."


def _post_settle_bet(session, form: dict[str, list[str]]) -> str:
    placed = _require_row(session, PlacedBet, _int_field(form, "bet_id"), "bet")
    outcome = settle_bet_row(
        session,
        placed,
        result=_text_field(form, "result"),
        settled_at=datetime.now(UTC),
        notes=_optional_text_field(form, "notes"),
    )
    return f"Settled bet {placed.bet_id}: {outcome.result}, P&L ${outcome.profit_loss:.2f}."


def _post_record_clv(session, form: dict[str, list[str]]) -> str:
    placed = _require_row(session, PlacedBet, _int_field(form, "bet_id"), "bet")
    ticket = _require_row(session, BetTicket, placed.ticket_id, "ticket")
    candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
    clv = record_clv_for_bet_row(
        session,
        placed,
        ticket,
        candidate,
        closing_american_odds=_int_field(form, "closing_odds"),
        captured_at=datetime.now(UTC),
    )
    return f"Recorded CLV for bet {placed.bet_id}: raw {clv.clv_raw:.2%}."


def _post_record_attribution(session, form: dict[str, list[str]]) -> str:
    placed = _require_row(session, PlacedBet, _int_field(form, "bet_id"), "bet")
    ticket = _require_row(session, BetTicket, placed.ticket_id, "ticket")
    candidate = _require_row(session, BetCandidate, ticket.candidate_id, "candidate")
    outcome = session.query(BetOutcome).filter_by(bet_id=placed.bet_id).one_or_none()
    if outcome is None:
        raise ValueError(f"Bet {placed.bet_id} has no settlement.")
    attribution = record_attribution_for_bet_row(
        session,
        placed,
        ticket,
        candidate,
        outcome,
        flat_stake=_optional_float_field(form, "flat_stake"),
        created_at=datetime.now(UTC),
    )
    return f"Recorded attribution {attribution.attribution_id} for bet {placed.bet_id}."


def _page(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #202124;
      --muted: #667085;
      --line: #d0d5dd;
      --panel: #f7f8fa;
      --good: #067647;
      --bad: #b42318;
      --warn: #b54708;
      --focus: #155eef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: white;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: white;
      border-bottom: 1px solid var(--line);
      padding: 14px 22px;
    }}
    main {{ padding: 18px 22px 40px; }}
    h1 {{ font-size: 20px; margin: 0 0 4px; letter-spacing: 0; }}
    h2 {{ font-size: 15px; margin: 0 0 12px; letter-spacing: 0; }}
    .subtle {{ color: var(--muted); font-size: 13px; }}
    .message {{
      margin-top: 10px;
      padding: 9px 11px;
      border: 1px solid var(--line);
      background: var(--panel);
      font-size: 13px;
    }}
    section {{ margin-top: 18px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
    }}
    .metric {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 10px;
      min-height: 74px;
    }}
    .metric strong {{ display: block; font-size: 20px; margin-top: 4px; }}
    .status-good {{ color: var(--good); font-weight: 700; }}
    .status-bad {{ color: var(--bad); font-weight: 700; }}
    .status-warn {{ color: var(--warn); font-weight: 700; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--line);
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: var(--panel); font-weight: 650; }}
    tr:last-child td {{ border-bottom: 0; }}
    input, select {{
      width: 100%;
      min-width: 72px;
      border: 1px solid var(--line);
      padding: 6px;
      font: inherit;
      background: white;
    }}
    button {{
      border: 1px solid var(--focus);
      background: var(--focus);
      color: white;
      padding: 7px 9px;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }}
    button.secondary {{
      border-color: var(--line);
      color: var(--ink);
      background: white;
    }}
    form.inline {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      align-items: end;
    }}
    pre {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 10px;
      overflow: auto;
      font-size: 12px;
    }}
    .nowrap {{ white-space: nowrap; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _header(database_url: str | None, *, message: str | None) -> str:
    db_label = database_url or "DATABASE_URL / sqlite:///./data/db/golf_trading.db"
    rendered_message = f'<div class="message">{_e(message)}</div>' if message else ""
    return f"""<header>
  <h1>UpAndDown Operator Console</h1>
  <div class="subtle">DB: {_e(db_label)}</div>
  {rendered_message}
</header>
<main>"""


def _summary_section(report, readiness, evidence) -> str:
    return f"""<section>
  <h2>Review State</h2>
  <div class="metrics">
    {_metric("Readiness", "READY" if readiness.passed else "NOT READY", readiness.passed)}
    {_metric("Evidence", "CLEAN" if evidence.evidence_clean else "CHECK", evidence.evidence_clean)}
    {_metric("Tickets", str(report.ticket_count))}
    {_metric("Approved", str(report.approved_count))}
    {_metric("Open", str(report.open_ticket_count), report.open_ticket_count == 0)}
    {_metric("Placed", str(report.placed_count))}
    {_metric("Settled", str(report.settled_count))}
    {_metric("Missing CLV", str(report.missing_clv_count), report.missing_clv_count == 0)}
    {_metric("Attribution", f"{report.attribution_count}/{report.settled_count}", report.attribution_count == report.settled_count)}
    {_metric("Strategy P&L", _money(report.strategy_profit_loss))}
    {_metric("Avg CLV", _pct_or_na(report.average_clv_raw))}
    {_metric("ROI", f"{report.strategy_roi:.2%}")}
  </div>
</section>"""


def _action_section() -> str:
    return """<section>
  <h2>Ticket Candidates</h2>
  <form class="inline" method="post" action="/ticket-candidates">
    <label>Total bankroll<input name="total_bankroll" value="25000"></label>
    <label>Tournament ID<input name="tournament_id" placeholder="optional"></label>
    <label>Limit<input name="limit" placeholder="optional"></label>
    <button type="submit">Create Tickets</button>
  </form>
</section>"""


def _candidate_section(candidates, tournament_by_id, player_by_id) -> str:
    rows = []
    for candidate in candidates:
        tournament = tournament_by_id.get(candidate.tournament_id)
        primary = player_by_id.get(candidate.player_id_1)
        rows.append(
            "<tr>"
            f"<td>{candidate.candidate_id}</td>"
            f"<td>{_e(_tournament_name(tournament))}</td>"
            f"<td>{_e(candidate.market_type)}</td>"
            f"<td>{_e(candidate.book)}</td>"
            f"<td>{_e(_player_name(primary))}</td>"
            f"<td>{_e(candidate.side)}</td>"
            f"<td>{candidate.book_american_odds if candidate.book_american_odds is not None else ''}</td>"
            f"<td>{candidate.edge_pct:.2%}</td>"
            "</tr>"
        )
    return _table_section(
        "Candidates",
        ["ID", "Tournament", "Market", "Book", "Player", "Side", "Odds", "Edge"],
        rows,
    )


def _ticket_section(tickets, placed_ticket_ids, candidate_by_id, tournament_by_id, player_by_id) -> str:
    rows = []
    for ticket in tickets:
        candidate = candidate_by_id.get(ticket.candidate_id)
        tournament = tournament_by_id.get(candidate.tournament_id) if candidate else None
        primary = player_by_id.get(candidate.player_id_1) if candidate else None
        status = "placed" if ticket.ticket_id in placed_ticket_ids else "open"
        action = ""
        if ticket.approved and status == "open":
            action = f"""<form class="inline" method="post" action="/place-ticket">
              <input type="hidden" name="ticket_id" value="{ticket.ticket_id}">
              <input name="actual_odds" placeholder="odds" value="{ticket.proposed_american_odds or ''}">
              <input name="actual_stake" placeholder="stake" value="{ticket.proposed_stake:.2f}">
              <select name="bet_class">
                <option>STANDARD</option>
                <option>BOOSTED_ODDS</option>
                <option>FREE_BET</option>
                <option>RISK_FREE</option>
              </select>
              <input name="notes" placeholder="notes">
              <button type="submit">Place</button>
            </form>"""
        rows.append(
            "<tr>"
            f"<td>{ticket.ticket_id}</td>"
            f"<td>{_e(_tournament_name(tournament))}</td>"
            f"<td>{_e(candidate.market_type if candidate else '')}</td>"
            f"<td>{_e(candidate.book if candidate else '')}</td>"
            f"<td>{_e(_player_name(primary))}</td>"
            f"<td>{_status_text('approved' if ticket.approved else 'rejected', ticket.approved)}</td>"
            f"<td>{_e(status)}</td>"
            f"<td>{ticket.proposed_american_odds if ticket.proposed_american_odds is not None else ''}</td>"
            f"<td>{_money(ticket.proposed_stake)}</td>"
            f"<td>{_e(ticket.rejection_reason or '')}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    return _table_section(
        "Tickets",
        ["ID", "Tournament", "Market", "Book", "Player", "Decision", "Status", "Odds", "Stake", "Reason", "Action"],
        rows,
    )


def _bet_section(
    placed_bets,
    ticket_by_id,
    candidate_by_id,
    tournament_by_id,
    player_by_id,
    outcomes_by_bet,
    clv_by_bet,
    attribution_by_bet,
) -> str:
    rows = []
    for bet in placed_bets:
        ticket = ticket_by_id.get(bet.ticket_id)
        candidate = candidate_by_id.get(ticket.candidate_id) if ticket else None
        tournament = tournament_by_id.get(candidate.tournament_id) if candidate else None
        primary = player_by_id.get(candidate.player_id_1) if candidate else None
        outcome = outcomes_by_bet.get(bet.bet_id)
        clv = clv_by_bet.get(bet.bet_id)
        attribution = attribution_by_bet.get(bet.bet_id)
        settlement_action = ""
        if outcome is None:
            settlement_action = f"""<form class="inline" method="post" action="/settle-bet">
              <input type="hidden" name="bet_id" value="{bet.bet_id}">
              <select name="result">
                <option>win</option><option>loss</option><option>push</option><option>void</option><option>dead_heat</option>
              </select>
              <input name="notes" placeholder="notes">
              <button type="submit">Settle</button>
            </form>"""
        clv_action = ""
        if clv is None:
            clv_action = f"""<form class="inline" method="post" action="/record-clv">
              <input type="hidden" name="bet_id" value="{bet.bet_id}">
              <input name="closing_odds" placeholder="closing odds">
              <button type="submit">CLV</button>
            </form>"""
        attribution_action = ""
        if outcome is not None and attribution is None:
            attribution_action = f"""<form class="inline" method="post" action="/record-attribution">
              <input type="hidden" name="bet_id" value="{bet.bet_id}">
              <input name="flat_stake" placeholder="flat stake">
              <button type="submit">Attribute</button>
            </form>"""
        rows.append(
            "<tr>"
            f"<td>{bet.bet_id}</td>"
            f"<td>{_e(_tournament_name(tournament))}</td>"
            f"<td>{_e(candidate.market_type if candidate else '')}</td>"
            f"<td>{_e(_player_name(primary))}</td>"
            f"<td>{_e(bet.book)}</td>"
            f"<td>{bet.actual_american_odds}</td>"
            f"<td>{_money(bet.actual_stake)}</td>"
            f"<td>{_e(outcome.result if outcome else 'pending')}</td>"
            f"<td>{_money(outcome.profit_loss) if outcome else ''}</td>"
            f"<td>{_pct_or_na(clv.clv_raw if clv else None)}</td>"
            f"<td>{'yes' if attribution else 'no'}</td>"
            f"<td>{settlement_action}{clv_action}{attribution_action}</td>"
            "</tr>"
        )
    return _table_section(
        "Placed Bets",
        ["ID", "Tournament", "Market", "Player", "Book", "Odds", "Stake", "Result", "P&L", "CLV", "Attrib", "Action"],
        rows,
    )


def _open_actions_section(actions: str) -> str:
    return f"""<section>
  <h2>Open Actions</h2>
  <pre>{_e(actions)}</pre>
</section>
</main>"""


def _table_section(title: str, headers: list[str], rows: list[str]) -> str:
    rendered_rows = "\n".join(rows) if rows else f"<tr><td colspan=\"{len(headers)}\">No rows.</td></tr>"
    return f"""<section>
  <h2>{_e(title)}</h2>
  <table>
    <thead><tr>{"".join(f"<th>{_e(header)}</th>" for header in headers)}</tr></thead>
    <tbody>{rendered_rows}</tbody>
  </table>
</section>"""


def _metric(label: str, value: str, passed: bool | None = None) -> str:
    status_class = ""
    if passed is True:
        status_class = "status-good"
    elif passed is False:
        status_class = "status-bad"
    return f"""<div class="metric"><span class="subtle">{_e(label)}</span><strong class="{status_class}">{_e(value)}</strong></div>"""


def _status_text(label: str, passed: bool) -> str:
    return f'<span class="{"status-good" if passed else "status-bad"}">{_e(label)}</span>'


def _require_row(session, model, row_id: int, label: str):
    row = session.get(model, row_id)
    if row is None:
        raise ValueError(f"Unknown {label}_id={row_id}")
    return row


def _text_field(form: dict[str, list[str]], name: str, *, default: str | None = None) -> str:
    value = form.get(name, [default])[0]
    if value is None or value == "":
        raise ValueError(f"Missing {name}.")
    return value


def _optional_text_field(form: dict[str, list[str]], name: str) -> str | None:
    value = form.get(name, [""])[0].strip()
    return value or None


def _int_field(form: dict[str, list[str]], name: str) -> int:
    return int(_text_field(form, name))


def _optional_int_field(form: dict[str, list[str]], name: str) -> int | None:
    value = _optional_text_field(form, name)
    return None if value is None else int(value)


def _float_field(form: dict[str, list[str]], name: str) -> float:
    return float(_text_field(form, name))


def _optional_float_field(form: dict[str, list[str]], name: str) -> float | None:
    value = _optional_text_field(form, name)
    return None if value is None else float(value)


def _tournament_name(tournament: Tournament | None) -> str:
    return "unknown" if tournament is None else tournament.name


def _player_name(player: Player | None) -> str:
    return "unknown" if player is None else player.name_canonical


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct_or_na(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local paper-trading operator console.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init_db(args.database_url)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.database_url))
    print(f"Operator console: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
