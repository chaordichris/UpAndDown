from __future__ import annotations

import pytest

from src.execution.promos import settlement_amounts


@pytest.mark.parametrize(
    ("bet_class", "terms", "result", "expected_raw", "expected_realized"),
    [
        ("STANDARD", None, "win", 95.24, 95.24),
        ("BOOSTED_ODDS", '{"profit_boost_multiplier": 1.5}', "win", 95.24, 142.86),
        ("FREE_BET", None, "win", 95.24, 95.24),
        ("FREE_BET", None, "loss", -100.0, 0.0),
        ("RISK_FREE", '{"refund_amount": 100}', "loss", -100.0, 0.0),
    ],
)
def test_settlement_amounts_separate_raw_and_realized_pnl(
    bet_class: str,
    terms: str | None,
    result: str,
    expected_raw: float,
    expected_realized: float,
) -> None:
    amounts = settlement_amounts(
        result=result,
        stake=100.0,
        american_odds=-105,
        bet_class=bet_class,
        boost_terms_json=terms,
    )

    assert amounts["profit_loss_raw"] == pytest.approx(expected_raw)
    assert amounts["profit_loss_realized"] == pytest.approx(expected_realized)


def test_settlement_amounts_rejects_unknown_bet_class() -> None:
    with pytest.raises(ValueError, match="Unknown bet_class"):
        settlement_amounts(
            result="win",
            stake=100.0,
            american_odds=-105,
            bet_class="PARLAY",
        )
