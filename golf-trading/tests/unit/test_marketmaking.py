"""Unit tests for the market-making scaffold (WS-9, MM-0)."""

from __future__ import annotations

import pytest

from src.marketmaking.config import MMConfig
from src.marketmaking.fair_value import fair_value_band
from src.marketmaking.inventory import apply_fill, attribute_pnl
from src.marketmaking.quoting import generate_quotes
from src.marketmaking.risk import RiskEngine
from src.marketmaking.simulator import report_artifact, run_simulation
from src.marketmaking.types import (
    Fill,
    InventoryState,
    MarketDef,
    QuoteProposal,
    Side,
)

CONFIG = MMConfig()
MARKET = MarketDef(
    market_id="m1",
    description="test market",
    tournament="t1",
    datagolf_id="dg1",
    market_type="top_20",
)


def make_inventory(position: int = 0) -> InventoryState:
    return InventoryState(market_id="m1", position=position)


# ---------------------------------------------------------------------------
# fair_value
# ---------------------------------------------------------------------------

class TestFairValue:
    def test_band_centered_on_datagolf_prob(self) -> None:
        band = fair_value_band(0.4, "top_20", CONFIG)
        assert band.mean == 0.4
        assert band.lo < 0.4 < band.hi

    def test_band_narrows_with_higher_ess(self) -> None:
        low_trust = fair_value_band(0.4, "outright_win", CONFIG)   # ess 150
        high_trust = fair_value_band(0.4, "make_cut", CONFIG)      # ess 400
        assert high_trust.half_width < low_trust.half_width

    def test_band_clamped_to_unit_interval(self) -> None:
        band = fair_value_band(0.02, "outright_win", CONFIG)
        assert band.lo >= 0.0
        assert band.hi <= 1.0

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.1])
    def test_rejects_degenerate_probs(self, bad: float) -> None:
        with pytest.raises(ValueError):
            fair_value_band(bad, "top_20", CONFIG)


# ---------------------------------------------------------------------------
# quoting
# ---------------------------------------------------------------------------

class TestQuoting:
    def test_two_sided_quote_brackets_fair(self) -> None:
        fair = fair_value_band(0.4, "top_20", CONFIG)
        proposal = generate_quotes(MARKET, fair, make_inventory(), CONFIG)
        bid = next(q for q in proposal.quotes if q.side == Side.BID)
        ask = next(q for q in proposal.quotes if q.side == Side.ASK)
        assert bid.price < fair.mean < ask.price
        assert ask.price - bid.price >= 2 * CONFIG.min_half_spread - MARKET.tick

    def test_no_quote_when_uncertainty_too_wide(self) -> None:
        config = MMConfig(max_quotable_half_width=0.001)
        fair = fair_value_band(0.4, "outright_win", config)
        proposal = generate_quotes(MARKET, fair, make_inventory(), config)
        assert proposal.quotes == ()
        assert "no-quote default" in proposal.reasons[0]

    def test_long_inventory_skews_quotes_down(self) -> None:
        fair = fair_value_band(0.4, "top_20", CONFIG)
        flat = generate_quotes(MARKET, fair, make_inventory(0), CONFIG)
        long = generate_quotes(MARKET, fair, make_inventory(30), CONFIG)
        flat_bid = next(q for q in flat.quotes if q.side == Side.BID)
        long_bid = next(q for q in long.quotes if q.side == Side.BID)
        assert long_bid.price <= flat_bid.price

    def test_bid_size_shrinks_as_inventory_grows(self) -> None:
        fair = fair_value_band(0.4, "top_20", CONFIG)
        flat = generate_quotes(MARKET, fair, make_inventory(0), CONFIG)
        long = generate_quotes(MARKET, fair, make_inventory(40), CONFIG)
        flat_bid = next(q for q in flat.quotes if q.side == Side.BID)
        long_bid = next((q for q in long.quotes if q.side == Side.BID), None)
        assert long_bid is None or long_bid.size < flat_bid.size

    def test_bid_withheld_at_position_limit(self) -> None:
        fair = fair_value_band(0.4, "top_20", CONFIG)
        proposal = generate_quotes(
            MARKET, fair, make_inventory(CONFIG.max_position_per_market), CONFIG
        )
        assert all(q.side != Side.BID for q in proposal.quotes)
        assert any("bid withheld" in r for r in proposal.reasons)

    def test_prices_respect_tick_and_bounds(self) -> None:
        fair = fair_value_band(0.02, "make_cut", CONFIG)
        proposal = generate_quotes(MARKET, fair, make_inventory(), CONFIG)
        for quote in proposal.quotes:
            assert MARKET.min_price <= quote.price <= MARKET.max_price
            assert round(quote.price / MARKET.tick) == pytest.approx(
                quote.price / MARKET.tick
            )


# ---------------------------------------------------------------------------
# inventory + attribution
# ---------------------------------------------------------------------------

class TestInventory:
    def test_apply_fill_updates_position_and_cash(self) -> None:
        inv = make_inventory()
        apply_fill(inv, Fill("m1", Side.BID, 0.38, 10, timestep=1))
        assert inv.position == 10
        assert inv.cash == pytest.approx(-3.8)
        apply_fill(inv, Fill("m1", Side.ASK, 0.42, 10, timestep=2))
        assert inv.position == 0
        assert inv.cash == pytest.approx(0.4)

    def test_attribution_sums_to_total_pnl(self) -> None:
        inv = make_inventory()
        apply_fill(inv, Fill("m1", Side.BID, 0.38, 10, timestep=1))
        apply_fill(inv, Fill("m1", Side.ASK, 0.45, 4, timestep=2))
        settlement = 1.0
        attribution = attribute_pnl(
            inv, {1: 0.40, 2: 0.42}, fair_final=0.43, settlement=settlement
        )
        total = inv.cash + inv.position * settlement
        assert attribution.total == pytest.approx(total)

    def test_round_trip_at_static_fair_is_pure_spread(self) -> None:
        inv = make_inventory()
        apply_fill(inv, Fill("m1", Side.BID, 0.38, 10, timestep=1))
        apply_fill(inv, Fill("m1", Side.ASK, 0.42, 10, timestep=2))
        attribution = attribute_pnl(inv, {1: 0.40, 2: 0.40}, 0.40, 1.0)
        assert attribution.spread_capture == pytest.approx(0.4)
        assert attribution.adverse_selection == pytest.approx(0.0)
        assert attribution.inventory_settlement == pytest.approx(0.0)

    def test_rejects_non_binary_settlement(self) -> None:
        with pytest.raises(ValueError):
            attribute_pnl(make_inventory(), {}, 0.5, 0.4)


# ---------------------------------------------------------------------------
# risk
# ---------------------------------------------------------------------------

class TestRisk:
    def _proposal(self, quotes) -> QuoteProposal:
        fair = fair_value_band(0.4, "top_20", CONFIG)
        return QuoteProposal(market_id="m1", quotes=tuple(quotes), fair=fair)

    def test_vetoes_position_limit_breach(self) -> None:
        from src.marketmaking.types import Quote

        engine = RiskEngine(CONFIG)
        quote = Quote("m1", Side.BID, 0.38, size=20)
        decision = engine.review(
            self._proposal([quote]),
            make_inventory(CONFIG.max_position_per_market - 5),
            tournament_notional=0.0,
        )
        assert decision.approved == ()
        assert "position limit" in decision.vetoed[0][1]

    def test_vetoes_tournament_notional_breach(self) -> None:
        from src.marketmaking.types import Quote

        engine = RiskEngine(CONFIG)
        quote = Quote("m1", Side.BID, 0.50, size=30)  # 15 dollars worst case
        decision = engine.review(
            self._proposal([quote]),
            make_inventory(),
            tournament_notional=CONFIG.max_notional_per_tournament - 1.0,
        )
        assert decision.approved == ()
        assert "tournament notional" in decision.vetoed[0][1]

    def test_kill_switch_vetoes_everything(self) -> None:
        from src.marketmaking.types import Quote

        engine = RiskEngine(CONFIG)
        engine.record_pnl(-CONFIG.daily_loss_kill_switch)
        decision = engine.review(
            self._proposal([Quote("m1", Side.BID, 0.38, size=1)]),
            make_inventory(),
            tournament_notional=0.0,
        )
        assert decision.kill_switch is True
        assert decision.approved == ()

    def test_approves_within_limits(self) -> None:
        from src.marketmaking.types import Quote

        engine = RiskEngine(CONFIG)
        quote = Quote("m1", Side.BID, 0.38, size=5)
        decision = engine.review(
            self._proposal([quote]), make_inventory(), tournament_notional=0.0
        )
        assert decision.approved == (quote,)


# ---------------------------------------------------------------------------
# simulator
# ---------------------------------------------------------------------------

class TestSimulator:
    def test_deterministic_under_seed(self) -> None:
        a = run_simulation(CONFIG, episodes=5, base_seed=11)
        b = run_simulation(CONFIG, episodes=5, base_seed=11)
        assert a == b

    def test_different_seeds_differ(self) -> None:
        a = run_simulation(CONFIG, episodes=5, base_seed=11)
        b = run_simulation(CONFIG, episodes=5, base_seed=99)
        assert a != b

    def test_attribution_streams_sum_to_total(self) -> None:
        report = run_simulation(CONFIG, episodes=10, base_seed=3)
        assert report.total_pnl == pytest.approx(
            report.spread_capture
            + report.adverse_selection
            + report.inventory_settlement,
            abs=1e-6,
        )

    def test_positions_respect_hard_limit(self) -> None:
        report = run_simulation(CONFIG, episodes=20, base_seed=5)
        for episode in report.episode_results:
            assert abs(episode.final_position) <= CONFIG.max_position_per_market

    def test_artifact_carries_inputs_hash(self) -> None:
        report = run_simulation(CONFIG, episodes=2, base_seed=1)
        artifact = report_artifact(report, CONFIG)
        assert artifact["artifact_type"] == "mm_simulation_report"
        assert len(artifact["inputs_hash"]) == 64
