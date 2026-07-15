from __future__ import annotations

import pytest

from scripts.build_rungood_splash_lineup_card import (
    build_lineup_card,
    render_lineup_card_text,
)


def test_build_lineup_card_combines_portfolio_and_sensitivity() -> None:
    card = build_lineup_card(
        portfolio_artifact=_portfolio_artifact(recommendation="play"),
        sensitivity_summary=_sensitivity_summary(),
        portfolio_artifact_path="portfolio.json",
        sensitivity_summary_path="sensitivity.json",
        portfolio_name="conservative",
    )

    assert card["contest"]["name"] == "RunGood"
    assert card["entry_plan"]["recommended_entries"] == 1
    assert card["entry_plan"]["total_stake_dollars"] == 25.0
    assert card["lineups"] == [
        {
            "entry_number": 1,
            "lineup_id": "lineup-1",
            "players": ["Alpha", "Bravo"],
            "player_ids": ["a", "b"],
            "expected_profit_cents": 500.0,
            "marginal_ev_cents": 450.0,
            "target_duplication_count": 2,
        }
    ]
    assert card["sensitivity"]["play_rate"] == 1.0
    assert card["provenance"]["portfolio_artifact"] == "portfolio.json"
    assert card["artifact_hash"]


def test_build_lineup_card_refuses_no_play_without_override() -> None:
    with pytest.raises(ValueError, match="not playable"):
        build_lineup_card(
            portfolio_artifact=_portfolio_artifact(recommendation="no play"),
            sensitivity_summary=_sensitivity_summary(),
            portfolio_artifact_path="portfolio.json",
            sensitivity_summary_path="sensitivity.json",
            portfolio_name="conservative",
        )


def test_render_lineup_card_text_includes_manual_entries_and_hashes() -> None:
    card = build_lineup_card(
        portfolio_artifact=_portfolio_artifact(recommendation="play"),
        sensitivity_summary=_sensitivity_summary(),
        portfolio_artifact_path="portfolio.json",
        sensitivity_summary_path="sensitivity.json",
        portfolio_name="conservative",
    )

    rendered = render_lineup_card_text(card)

    assert "Splash Final Lineup Card: conservative" in rendered
    assert "1. Alpha / Bravo" in rendered
    assert "Portfolio hash: portfolio-hash" in rendered
    assert "Card hash:" in rendered


def _portfolio_artifact(*, recommendation: str) -> dict:
    return {
        "artifact_hash": "portfolio-hash",
        "contest": {
            "name": "RunGood",
            "entry_fee_cents": 2500,
        },
        "input_fixtures": {"contest": "contest.json"},
        "local_data_summary": {"candidate_generation": "projected"},
        "reports": {
            "conservative": {
                "recommendation": recommendation,
                "no_play_reasons": [] if recommendation == "play" else ["too_uncertain"],
                "recommended_entries": 1 if recommendation == "play" else 0,
                "total_stake_cents": 2500 if recommendation == "play" else 0,
                "portfolio_ev_cents": 500.0,
                "portfolio_sd_cents": 1000.0,
                "ev_to_sd_ratio": 0.5,
                "ror_estimate": {"paper_only_probability": 0.0},
                "inputs_hash": "report-hash",
                "manual_lineups": [
                    {
                        "entry_number": 1,
                        "lineup_id": "lineup-1",
                        "players": ["Alpha", "Bravo"],
                        "player_ids": ["a", "b"],
                        "expected_profit_cents": 500.0,
                        "marginal_ev_cents": 450.0,
                    }
                ],
            }
        },
        "portfolios": {
            "conservative": {
                "inputs_hash": "portfolio-input-hash",
                "lineups": [
                    {
                        "lineup_id": "lineup-1",
                        "target_duplication_count": 2,
                    }
                ],
            }
        },
    }


def _sensitivity_summary() -> dict:
    return {
        "artifact_hash": "sensitivity-hash",
        "scenario_count": 2,
        "parameters": {"simulations": 100},
        "stability": {
            "conservative": {
                "scenario_count": 2,
                "play_count": 2,
                "play_rate": 1.0,
                "recommended_entries_min": 1,
                "recommended_entries_max": 1,
                "ev_to_sd_min": 0.4,
                "ev_to_sd_max": 0.6,
                "most_common_lineups": [
                    {"players": ["Alpha", "Bravo"], "scenario_count": 2}
                ],
            }
        },
    }
