"""Local Splash fantasy operator console."""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.hashing import stable_hash

LEDGER_FILENAME = "splash-results-ledger.json"


def build_splash_dashboard_html(
    artifact_dir: Path,
    *,
    message: str | None = None,
) -> str:
    """Render a local Splash workflow dashboard from JSON artifacts."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    evaluations = _load_artifacts(artifact_dir, "splash_lobby_evaluation")
    lineup_cards = _load_lineup_cards(artifact_dir)
    ledger = _load_ledger(artifact_dir)
    return _page(
        title="UpAndDown Splash Console",
        body="\n".join(
            [
                _header(artifact_dir, message),
                _summary_section(evaluations, lineup_cards, ledger),
                _artifact_section(artifact_dir, evaluations, lineup_cards),
                _contest_board_section(evaluations),
                _capital_plan_section(evaluations),
                _lineup_section(lineup_cards),
                _manual_lineup_entry_section(lineup_cards),
                _result_entry_section(evaluations, ledger),
                _pnl_section(ledger),
            ]
        ),
    )


def make_handler(artifact_dir: Path) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one Splash artifact directory."""

    class SplashOperatorConsoleHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path in {"/", "/index.html"}:
                self._send_html(build_splash_dashboard_html(artifact_dir, message=query.get("message", [None])[0]))
                return
            if parsed.path == "/artifacts/ledger.json":
                self._send_json(json.dumps(_load_ledger(artifact_dir), indent=2, sort_keys=True))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown route")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                message = _handle_post(parsed.path, form, artifact_dir)
            except Exception as exc:  # noqa: BLE001
                message = f"Error: {exc}"
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/?{urlencode({'message': message})}")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, body: str) -> None:
            self._send_bytes(body.encode("utf-8"), "text/html; charset=utf-8")

        def _send_json(self, body: str) -> None:
            self._send_bytes(body.encode("utf-8"), "application/json; charset=utf-8")

        def _send_bytes(self, payload: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return SplashOperatorConsoleHandler


def _handle_post(path: str, form: dict[str, list[str]], artifact_dir: Path) -> str:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if path == "/record-lineup-entry":
        return _post_record_lineup_entry(form, artifact_dir)
    if path == "/record-result":
        return _post_record_result(form, artifact_dir)
    raise ValueError(f"Unknown action {path!r}")


def _post_record_lineup_entry(form: dict[str, list[str]], artifact_dir: Path) -> str:
    ledger = _load_ledger(artifact_dir)
    entry = {
        "entry_id": f"entry-{len(ledger['lineup_entries']) + 1}",
        "contest_id": _text_field(form, "contest_id"),
        "contest_name": _text_field(form, "contest_name"),
        "lineup_id": _text_field(form, "lineup_id"),
        "entry_number": _optional_int_field(form, "entry_number"),
        "players": _players_field(form),
        "entry_fee_dollars": _float_field(form, "entry_fee_dollars"),
        "source_artifact_hash": _optional_text_field(form, "source_artifact_hash"),
        "notes": _optional_text_field(form, "notes"),
        "entered_at": datetime.now(UTC).isoformat(),
    }
    entry["inputs_hash"] = stable_hash(entry)
    ledger["lineup_entries"].append(entry)
    _write_ledger(artifact_dir, ledger)
    return f"Recorded Splash lineup entry {entry['entry_id']}."


def _post_record_result(form: dict[str, list[str]], artifact_dir: Path) -> str:
    ledger = _load_ledger(artifact_dir)
    entry_fee = _float_field(form, "entry_fee_dollars")
    entries_played = _int_field(form, "entries_played")
    payout = _float_field(form, "payout_dollars")
    result = {
        "result_id": f"result-{len(ledger['results']) + 1}",
        "contest_id": _text_field(form, "contest_id"),
        "contest_name": _text_field(form, "contest_name"),
        "entries_played": entries_played,
        "entry_fee_dollars": entry_fee,
        "total_stake_dollars": round(entries_played * entry_fee, 2),
        "payout_dollars": payout,
        "profit_loss_dollars": round(payout - entries_played * entry_fee, 2),
        "settled_at": datetime.now(UTC).isoformat(),
        "notes": _optional_text_field(form, "notes"),
    }
    result["inputs_hash"] = stable_hash(result)
    ledger["results"].append(result)
    _write_ledger(artifact_dir, ledger)
    return f"Recorded Splash result {result['result_id']}: P&L ${result['profit_loss_dollars']:.2f}."


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
    form.inline {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      align-items: end;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
      align-items: end;
    }}
    textarea {{
      width: 100%;
      border: 1px solid var(--line);
      padding: 6px;
      font: inherit;
      background: white;
      resize: vertical;
    }}
    .stack {{ display: grid; gap: 10px; }}
    .actions-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, max-content));
      gap: 8px;
    }}
    .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 7px 9px;
      border: 1px solid var(--focus);
      background: var(--focus);
      color: white;
      text-decoration: none;
      font: inherit;
    }}
    .nowrap {{ white-space: nowrap; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _header(artifact_dir: Path, message: str | None) -> str:
    rendered_message = f'<div class="message">{_e(message)}</div>' if message else ""
    return f"""<header>
  <h1>UpAndDown Splash Console</h1>
  <div class="subtle">Artifacts: {_e(str(artifact_dir))}</div>
  <div class="subtle">Read-only Splash workflow. Manual lineup/result tracking only.</div>
  {rendered_message}
</header>
<main>"""


def _summary_section(evaluations: list[dict], lineup_cards: list[dict], ledger: dict) -> str:
    latest = evaluations[0] if evaluations else None
    plan = latest.get("capital_plan") if latest else {}
    totals = _ledger_totals(ledger)
    return f"""<section>
  <h2>Splash Review State</h2>
  <div class="metrics">
    {_metric("Evaluations", str(len(evaluations)))}
    {_metric("Lobby Contests", str(latest.get("contest_count", 0) if latest else 0))}
    {_metric("Planned Entries", str(plan.get("planned_entries", 0)))}
    {_metric("Planned Spend", _money(plan.get("planned_spend_dollars", 0)))}
    {_metric("Lineup Cards", str(len(lineup_cards)))}
    {_metric("Entered Lineups", str(len(ledger["lineup_entries"])))}
    {_metric("Settled Results", str(len(ledger["results"])))}
    {_metric("Tracked P&L", _money(totals["profit_loss_dollars"]), totals["profit_loss_dollars"] >= 0)}
  </div>
</section>"""


def _artifact_section(artifact_dir: Path, evaluations: list[dict], lineup_cards: list[dict]) -> str:
    latest_eval = _artifact_path(evaluations[0], artifact_dir) if evaluations else None
    latest_card = _artifact_path(lineup_cards[0], artifact_dir) if lineup_cards else None
    links = ['<a class="button-link" href="/artifacts/ledger.json">ledger.json</a>']
    if latest_eval:
        links.append(f'<span class="subtle">Latest evaluation: {_e(str(latest_eval))}</span>')
    if latest_card:
        links.append(f'<span class="subtle">Latest lineup card: {_e(str(latest_card))}</span>')
    return f"""<section>
  <h2>Artifacts</h2>
  <div class="actions-grid">{"".join(links)}</div>
</section>"""


def _contest_board_section(evaluations: list[dict]) -> str:
    latest = evaluations[0] if evaluations else None
    rows = []
    for row in (latest or {}).get("contests", []):
        contest = row["contest"]
        field = row["field"]
        capital = row["capital"]
        recommendation = row["recommendation"]
        rows.append(
            "<tr>"
            f"<td>{_e(recommendation['action'])}</td>"
            f"<td>{row['opportunity_score']:.2f}</td>"
            f"<td>{_e(contest['name'])}<div class=\"subtle\">{_e(contest['id'])}</div></td>"
            f"<td>{_money(contest['entry_fee_dollars'])}</td>"
            f"<td>{_money(contest['prize_pool_dollars'])}</td>"
            f"<td>{_pct_or_na(field['fill_rate'])}</td>"
            f"<td>{field['filled_entries'] or ''}/{field['max_entries'] or ''}</td>"
            f"<td>{capital['recommended_entries']}</td>"
            f"<td>{_money(capital['recommended_spend_dollars'])}</td>"
            f"<td>{_e('; '.join(recommendation['reasons'][:3]))}</td>"
            "</tr>"
        )
    return _table_section(
        "Lobby Opportunity Board",
        ["Action", "Score", "Contest", "Entry", "Prize Pool", "Fill", "Entries", "Plan Entries", "Plan Spend", "Why"],
        rows,
    )


def _capital_plan_section(evaluations: list[dict]) -> str:
    latest = evaluations[0] if evaluations else None
    rows = []
    for row in (latest or {}).get("capital_plan", {}).get("planned_contests", []):
        rows.append(
            "<tr>"
            f"<td>{_e(row['action'])}</td>"
            f"<td>{_e(row['name'])}</td>"
            f"<td>{row['opportunity_score']:.2f}</td>"
            f"<td>{row['recommended_entries']}</td>"
            f"<td>{_money(row['recommended_spend_dollars'])}</td>"
            "</tr>"
        )
    return _table_section(
        "Capital Plan",
        ["Action", "Contest", "Score", "Entries", "Spend"],
        rows,
    )


def _lineup_section(lineup_cards: list[dict]) -> str:
    rows = []
    for card in lineup_cards:
        contest = card.get("contest") or {}
        for lineup in card.get("lineups", []):
            rows.append(
                "<tr>"
                f"<td>{_e(contest.get('name', ''))}<div class=\"subtle\">{_e(card.get('artifact_path', ''))}</div></td>"
                f"<td>{lineup.get('entry_number', '')}</td>"
                f"<td>{_e(lineup.get('lineup_id', ''))}</td>"
                f"<td>{_e(', '.join(lineup.get('players') or []))}</td>"
                f"<td>{_money((lineup.get('expected_profit_cents') or 0) / 100)}</td>"
                f"<td>{_money((lineup.get('marginal_ev_cents') or 0) / 100)}</td>"
                f"<td>{lineup.get('target_duplication_count', '')}</td>"
                "</tr>"
            )
    return _table_section(
        "Generated Lineups",
        ["Contest", "Entry #", "Lineup", "Players", "Expected Profit", "Marginal EV", "Dupes"],
        rows,
    )


def _manual_lineup_entry_section(lineup_cards: list[dict]) -> str:
    latest = lineup_cards[0] if lineup_cards else {}
    contest = latest.get("contest") or {}
    first_lineup = (latest.get("lineups") or [{}])[0]
    players = "\n".join(first_lineup.get("players") or [])
    return f"""<section>
  <h2>Record Manual Lineup Entry</h2>
  <form method="post" action="/record-lineup-entry">
    <div class="stack">
      <div class="form-grid">
        <label>Contest ID<input name="contest_id" value="{_e(contest.get('id', ''))}" placeholder="required"></label>
        <label>Contest Name<input name="contest_name" value="{_e(contest.get('name', ''))}" placeholder="required"></label>
        <label>Lineup ID<input name="lineup_id" value="{_e(first_lineup.get('lineup_id', ''))}" placeholder="required"></label>
        <label>Entry #<input name="entry_number" value="{_e(first_lineup.get('entry_number', ''))}" placeholder="optional"></label>
        <label>Entry Fee<input name="entry_fee_dollars" value="{_e((contest.get('entry_fee_cents') or 0) / 100 if contest else '')}" placeholder="25"></label>
        <label>Source Hash<input name="source_artifact_hash" value="{_e(latest.get('artifact_hash', ''))}" placeholder="optional"></label>
      </div>
      <label>Players<textarea name="players" rows="4">{_e(players)}</textarea></label>
      <label>Notes<input name="notes" placeholder="manual entry confirmation notes"></label>
      <div><button type="submit">Record Lineup Entry</button></div>
    </div>
  </form>
</section>"""


def _result_entry_section(evaluations: list[dict], ledger: dict) -> str:
    latest = evaluations[0] if evaluations else {}
    planned = (latest.get("capital_plan") or {}).get("planned_contests") or [{}]
    first = planned[0]
    contest_entries = _ledger_entry_counts(ledger)
    default_entries = contest_entries.get(first.get("contest_id"), first.get("recommended_entries", ""))
    return f"""<section>
  <h2>Record Contest Result</h2>
  <form class="inline" method="post" action="/record-result">
    <label>Contest ID<input name="contest_id" value="{_e(first.get('contest_id', ''))}" placeholder="required"></label>
    <label>Contest Name<input name="contest_name" value="{_e(first.get('name', ''))}" placeholder="required"></label>
    <label>Entries Played<input name="entries_played" value="{_e(default_entries)}" placeholder="required"></label>
    <label>Entry Fee<input name="entry_fee_dollars" placeholder="25"></label>
    <label>Payout<input name="payout_dollars" placeholder="0"></label>
    <label>Notes<input name="notes" placeholder="settlement notes"></label>
    <button type="submit">Record Result</button>
  </form>
</section>"""


def _pnl_section(ledger: dict) -> str:
    rows = []
    for row in ledger["results"]:
        rows.append(
            "<tr>"
            f"<td>{_e(row['contest_name'])}<div class=\"subtle\">{_e(row['contest_id'])}</div></td>"
            f"<td>{row['entries_played']}</td>"
            f"<td>{_money(row['total_stake_dollars'])}</td>"
            f"<td>{_money(row['payout_dollars'])}</td>"
            f"<td>{_money(row['profit_loss_dollars'])}</td>"
            f"<td>{_e(row.get('notes') or '')}</td>"
            "</tr>"
        )
    return _table_section("Results / P&L", ["Contest", "Entries", "Stake", "Payout", "P&L", "Notes"], rows)


def _table_section(title: str, headers: list[str], rows: list[str]) -> str:
    rendered_rows = "\n".join(rows) if rows else f"<tr><td colspan=\"{len(headers)}\">No rows.</td></tr>"
    return f"""<section>
  <h2>{_e(title)}</h2>
  <table>
    <thead><tr>{"".join(f"<th>{_e(header)}</th>" for header in headers)}</tr></thead>
    <tbody>{rendered_rows}</tbody>
  </table>
</section>"""


def _metric(label: str, value: str, good: bool | None = None) -> str:
    cls = ""
    if good is True:
        cls = " status-good"
    elif good is False:
        cls = " status-bad"
    return f'<div class="metric"><span class="subtle">{_e(label)}</span><strong class="{cls}">{_e(value)}</strong></div>'


def _load_artifacts(artifact_dir: Path, artifact_type: str) -> list[dict]:
    artifacts = []
    for path in sorted(artifact_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == LEDGER_FILENAME:
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("artifact_type") == artifact_type:
            artifacts.append({**payload, "artifact_path": str(path)})
    return artifacts


def _load_lineup_cards(artifact_dir: Path) -> list[dict]:
    cards = []
    for path in sorted(artifact_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == LEDGER_FILENAME:
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "lineups" in payload and "entry_plan" in payload:
            cards.append({**payload, "artifact_path": str(path)})
    return cards


def _load_ledger(artifact_dir: Path) -> dict:
    path = artifact_dir / LEDGER_FILENAME
    if not path.exists():
        return {"version": 1, "lineup_entries": [], "results": []}
    payload = json.loads(path.read_text())
    payload.setdefault("lineup_entries", [])
    payload.setdefault("results", [])
    payload.setdefault("version", 1)
    return payload


def _write_ledger(artifact_dir: Path, ledger: dict) -> None:
    ledger = {**ledger, "artifact_hash": stable_hash(ledger)}
    (artifact_dir / LEDGER_FILENAME).write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")


def _artifact_path(artifact: dict, artifact_dir: Path) -> Path | None:
    path = artifact.get("artifact_path")
    return Path(path) if path else artifact_dir


def _ledger_totals(ledger: dict) -> dict[str, float]:
    total_stake = sum(float(row["total_stake_dollars"]) for row in ledger["results"])
    payout = sum(float(row["payout_dollars"]) for row in ledger["results"])
    return {
        "total_stake_dollars": round(total_stake, 2),
        "payout_dollars": round(payout, 2),
        "profit_loss_dollars": round(payout - total_stake, 2),
    }


def _ledger_entry_counts(ledger: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in ledger["lineup_entries"]:
        contest_id = entry["contest_id"]
        counts[contest_id] = counts.get(contest_id, 0) + 1
    return counts


def _players_field(form: dict[str, list[str]]) -> list[str]:
    raw = _text_field(form, "players")
    return [line.strip() for line in raw.replace(",", "\n").splitlines() if line.strip()]


def _text_field(form: dict[str, list[str]], name: str) -> str:
    value = form.get(name, [""])[0].strip()
    if not value:
        raise ValueError(f"Missing {name}.")
    return value


def _optional_text_field(form: dict[str, list[str]], name: str) -> str | None:
    value = form.get(name, [""])[0].strip()
    return value or None


def _float_field(form: dict[str, list[str]], name: str) -> float:
    return float(_text_field(form, name))


def _int_field(form: dict[str, list[str]], name: str) -> int:
    return int(_text_field(form, name))


def _optional_int_field(form: dict[str, list[str]], name: str) -> int | None:
    value = _optional_text_field(form, name)
    return int(value) if value is not None else None


def _money(value: Any) -> str:
    return f"${float(value or 0):,.2f}"


def _pct_or_na(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2%}"


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Splash fantasy operator console.")
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/splash-capture"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.artifact_dir))
    print(f"Splash operator console: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
