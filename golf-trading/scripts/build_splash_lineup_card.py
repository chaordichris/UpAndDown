"""Build a final manual lineup card from Splash portfolio artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.hashing import stable_hash  # noqa: E402

DEFAULT_CAVEATS = (
    "Manual-entry lineup card; this does not automate contest entry.",
    "DataGolf remains the model anchor. Score moments are an auditable SG-to-relative-strokes transform, not observed total-strokes distributions.",
    "Players missing positive Splash DataGolf rank or score anchors are excluded as insufficient data.",
    "Sensitivity checks are scenario tests, not a guarantee of realized ROI.",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an auditable Splash lineup card.")
    parser.add_argument("--portfolio-artifact", required=True)
    parser.add_argument("--sensitivity-summary", required=True)
    parser.add_argument("--portfolio-name", choices=("conservative", "convex"), default="conservative")
    parser.add_argument("--output", required=True)
    parser.add_argument("--text-output")
    parser.add_argument("--allow-no-play", action="store_true")
    args = parser.parse_args()

    portfolio_artifact_path = _fixture_path(PROJECT_ROOT, args.portfolio_artifact)
    sensitivity_summary_path = _fixture_path(PROJECT_ROOT, args.sensitivity_summary)
    card = build_lineup_card(
        portfolio_artifact=_load_json(portfolio_artifact_path),
        sensitivity_summary=_load_json(sensitivity_summary_path),
        portfolio_artifact_path=args.portfolio_artifact,
        sensitivity_summary_path=args.sensitivity_summary,
        portfolio_name=args.portfolio_name,
        allow_no_play=args.allow_no_play,
    )
    output_path = _fixture_path(PROJECT_ROOT, args.output)
    _write_json(output_path, card)
    if args.text_output:
        _write_text(_fixture_path(PROJECT_ROOT, args.text_output), render_lineup_card_text(card))
    print(output_path)


def build_lineup_card(
    *,
    portfolio_artifact: dict[str, Any],
    sensitivity_summary: dict[str, Any],
    portfolio_artifact_path: str,
    sensitivity_summary_path: str,
    portfolio_name: str,
    allow_no_play: bool = False,
) -> dict[str, Any]:
    reports = portfolio_artifact.get("reports", {})
    portfolios = portfolio_artifact.get("portfolios", {})
    if portfolio_name not in reports:
        raise ValueError(f"Missing report for portfolio: {portfolio_name}")
    if portfolio_name not in portfolios:
        raise ValueError(f"Missing portfolio detail for portfolio: {portfolio_name}")

    report = reports[portfolio_name]
    portfolio = portfolios[portfolio_name]
    if report.get("recommendation") != "play" and not allow_no_play:
        raise ValueError(f"{portfolio_name} report is not playable: {report.get('no_play_reasons', [])}")

    lineups = _manual_lineups(report, portfolio)
    card = {
        "card_type": "splash_final_lineup_card",
        "portfolio_name": portfolio_name,
        "recommendation": report.get("recommendation"),
        "contest": portfolio_artifact.get("contest", {}),
        "entry_plan": {
            "recommended_entries": report.get("recommended_entries", 0),
            "entry_fee_cents": portfolio_artifact.get("contest", {}).get("entry_fee_cents"),
            "total_stake_cents": report.get("total_stake_cents", 0),
            "total_stake_dollars": round(report.get("total_stake_cents", 0) / 100, 2),
            "portfolio_ev_cents": report.get("portfolio_ev_cents"),
            "portfolio_sd_cents": report.get("portfolio_sd_cents"),
            "ev_to_sd_ratio": report.get("ev_to_sd_ratio"),
            "ror_estimate": report.get("ror_estimate"),
        },
        "lineups": lineups,
        "sensitivity": _sensitivity_block(sensitivity_summary, portfolio_name),
        "data_summary": portfolio_artifact.get("local_data_summary", {}),
        "input_fixtures": portfolio_artifact.get("input_fixtures", {}),
        "provenance": {
            "portfolio_artifact": portfolio_artifact_path,
            "portfolio_artifact_hash": portfolio_artifact.get("artifact_hash"),
            "portfolio_report_inputs_hash": report.get("inputs_hash"),
            "portfolio_inputs_hash": portfolio.get("inputs_hash"),
            "sensitivity_summary": sensitivity_summary_path,
            "sensitivity_artifact_hash": sensitivity_summary.get("artifact_hash"),
        },
        "caveats": list(DEFAULT_CAVEATS),
    }
    card["artifact_hash"] = stable_hash(card)
    return card


def render_lineup_card_text(card: dict[str, Any]) -> str:
    contest = card["contest"]
    entry_plan = card["entry_plan"]
    lines = [
        f"Splash Final Lineup Card: {card['portfolio_name']}",
        f"Contest: {contest.get('name')}",
        f"Recommendation: {card['recommendation']}",
        (
            f"Entries: {entry_plan['recommended_entries']} | "
            f"Stake: ${entry_plan['total_stake_dollars']:.2f} | "
            f"EV/SD: {entry_plan['ev_to_sd_ratio']}"
        ),
        "",
        "Manual Lineups",
    ]
    for lineup in card["lineups"]:
        lines.append(f"{lineup['entry_number']}. " + " / ".join(lineup["players"]))
    lines.extend(
        [
            "",
            "Sensitivity",
            (
                f"Play rate: {card['sensitivity'].get('play_rate')} | "
                f"EV/SD range: {card['sensitivity'].get('ev_to_sd_min')} to "
                f"{card['sensitivity'].get('ev_to_sd_max')}"
            ),
            "",
            "Caveats",
        ]
    )
    lines.extend(f"- {caveat}" for caveat in card["caveats"])
    lines.extend(
        [
            "",
            "Provenance",
            f"Portfolio artifact: {card['provenance']['portfolio_artifact']}",
            f"Portfolio hash: {card['provenance']['portfolio_artifact_hash']}",
            f"Sensitivity artifact: {card['provenance']['sensitivity_summary']}",
            f"Sensitivity hash: {card['provenance']['sensitivity_artifact_hash']}",
            f"Card hash: {card['artifact_hash']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _manual_lineups(report: dict[str, Any], portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    detail_by_lineup_id = {
        lineup["lineup_id"]: lineup
        for lineup in portfolio.get("lineups", [])
    }
    return [
        {
            "entry_number": lineup["entry_number"],
            "lineup_id": lineup["lineup_id"],
            "players": lineup["players"],
            "player_ids": lineup["player_ids"],
            "expected_profit_cents": lineup.get("expected_profit_cents"),
            "marginal_ev_cents": lineup.get("marginal_ev_cents"),
            "target_duplication_count": detail_by_lineup_id.get(lineup["lineup_id"], {}).get(
                "target_duplication_count"
            ),
        }
        for lineup in report.get("manual_lineups", [])
    ]


def _sensitivity_block(
    sensitivity_summary: dict[str, Any],
    portfolio_name: str,
) -> dict[str, Any]:
    stability = sensitivity_summary.get("stability", {})
    if portfolio_name not in stability:
        raise ValueError(f"Missing sensitivity stability for portfolio: {portfolio_name}")
    return {
        "scenario_count": sensitivity_summary.get("scenario_count"),
        "parameters": sensitivity_summary.get("parameters", {}),
        **stability[portfolio_name],
    }


def _fixture_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    with path.open() as file:
        return json.load(file)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)


if __name__ == "__main__":
    main()
