"""Seeded market-making episodes against the simulator venue.

One episode = one market quoted over N steps, then settled. The runner
tracks P&L attribution (spread capture / adverse selection / settlement)
per episode and in aggregate, and emits a provenance-hashed artifact.

The market maker's fair value tracks the true probability with a
configurable lag — the lag is exactly what adverse selection feeds on, so
it is a first-class parameter, not an accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.storage.hashing import stable_hash

from .config import MMConfig
from .fair_value import fair_value_band
from .inventory import PnLAttribution, apply_fill, attribute_pnl
from .quoting import generate_quotes
from .risk import RiskEngine
from .types import InventoryState, MarketDef, QuoteProposal
from .venues.base import VenueAdapter
from .venues.sim import SimParams, SimVenue


@dataclass(frozen=True)
class EpisodeResult:
    market_id: str
    seed: int
    fills: int
    final_position: int
    settlement: float
    pnl_total: float
    spread_capture: float
    adverse_selection: float
    inventory_settlement: float
    quotes_vetoed: int
    steps_stood_down: int


@dataclass(frozen=True)
class SimulationReport:
    episodes: int
    total_pnl: float
    spread_capture: float
    adverse_selection: float
    inventory_settlement: float
    adverse_to_spread_ratio: float | None
    episode_results: tuple[EpisodeResult, ...]


def submit_quotes(
    proposal: QuoteProposal,
    *,
    venue: VenueAdapter,
    risk: RiskEngine,
    inventory: InventoryState,
    fair_mean: float,
    timestep: int,
) -> tuple[int, list]:
    """Risk-review a proposal and post only the approved quotes to the venue.

    The one and only path from a QuoteProposal to a venue call — a future
    live-venue integration should call this rather than posting quotes
    directly, so risk review can't be accidentally skipped by copy-pasting
    the loop without the review step.
    """
    decision = risk.review(
        proposal, inventory, tournament_notional=inventory.notional_at_risk(fair_mean)
    )
    fills = venue.post_quotes(decision.approved, timestep) if decision.approved else []
    return len(decision.vetoed), fills


def run_episode(
    config: MMConfig,
    params: SimParams,
    risk: RiskEngine,
    fair_lag_steps: int | None = None,
) -> EpisodeResult:
    """Run one episode against a shared, caller-owned RiskEngine.

    ``fair_lag_steps`` defaults to ``config.fair_lag_steps`` (settings.yaml's
    ``marketmaking:`` block) — pass it explicitly only to override for a
    single call (e.g. a test probing a specific lag).

    The engine is shared (not created per episode) so the daily-loss kill
    switch actually accumulates across episodes within one run_simulation
    call — see run_simulation, which owns the engine's lifetime and treats
    one call as one trading day's risk budget.
    """
    market = MarketDef(
        market_id=f"sim-{params.seed}",
        description="simulated outright",
        tournament="sim",
        datagolf_id="sim",
        market_type="outright_win",
    )
    venue = SimVenue(market.market_id, params)
    inventory = InventoryState(market_id=market.market_id)
    lag = fair_lag_steps if fair_lag_steps is not None else config.fair_lag_steps

    fair_at_fill: dict[int, float] = {}
    vetoed = 0
    stood_down = 0
    last_fair = params.initial_true_prob

    for t in range(params.steps):
        venue.step_world()
        # Our fair value sees the truth with a lag — the adverse-selection tax.
        lagged_prob = venue.true_prob_path[max(0, len(venue.true_prob_path) - 1 - lag)]
        fair = fair_value_band(lagged_prob, market.market_type, config)
        last_fair = fair.mean

        proposal = generate_quotes(market, fair, inventory, config)
        if not proposal.quotes:
            stood_down += 1
            continue
        newly_vetoed, fills = submit_quotes(
            proposal,
            venue=venue,
            risk=risk,
            inventory=inventory,
            fair_mean=fair.mean,
            timestep=t,
        )
        vetoed += newly_vetoed

        for fill in fills:
            apply_fill(inventory, fill)
            fair_at_fill[fill.timestep] = fair.mean

    settlement = venue.settle(market.market_id)
    attribution = attribute_pnl(inventory, fair_at_fill, last_fair, settlement)
    # Realize this episode's P&L into the shared engine so the kill switch
    # sees it on the NEXT episode's quoting decisions (a still-open episode's
    # unrealized P&L can't retroactively veto its own already-posted quotes).
    risk.record_pnl(attribution.total)
    return EpisodeResult(
        market_id=market.market_id,
        seed=params.seed,
        fills=len(inventory.fills),
        final_position=inventory.position,
        settlement=settlement,
        pnl_total=round(attribution.total, 4),
        spread_capture=round(attribution.spread_capture, 4),
        adverse_selection=round(attribution.adverse_selection, 4),
        inventory_settlement=round(attribution.inventory_settlement, 4),
        quotes_vetoed=vetoed,
        steps_stood_down=stood_down,
    )


def run_simulation(
    config: MMConfig,
    episodes: int = 100,
    base_seed: int = 7,
    params: SimParams | None = None,
) -> SimulationReport:
    base = params or SimParams()
    base_kwargs = asdict(base)
    risk = RiskEngine(config)
    results = []
    for i in range(episodes):
        episode_params = SimParams(**{**base_kwargs, "seed": base_seed + i})
        results.append(run_episode(config, episode_params, risk))

    spread = sum(r.spread_capture for r in results)
    adverse = sum(r.adverse_selection for r in results)
    settle = sum(r.inventory_settlement for r in results)
    return SimulationReport(
        episodes=episodes,
        total_pnl=round(spread + adverse + settle, 4),
        spread_capture=round(spread, 4),
        adverse_selection=round(adverse, 4),
        inventory_settlement=round(settle, 4),
        adverse_to_spread_ratio=round(abs(adverse) / abs(spread), 4) if spread != 0 else None,
        episode_results=tuple(results),
    )


def report_artifact(report: SimulationReport, config: MMConfig) -> dict:
    """Serializable artifact with provenance hash, control-plane friendly."""
    payload = {
        "artifact_type": "mm_simulation_report",
        "config": asdict(config),
        "summary": {
            "episodes": report.episodes,
            "total_pnl": report.total_pnl,
            "spread_capture": report.spread_capture,
            "adverse_selection": report.adverse_selection,
            "inventory_settlement": report.inventory_settlement,
            "adverse_to_spread_ratio": report.adverse_to_spread_ratio,
        },
        "episodes": [asdict(r) for r in report.episode_results],
    }
    payload["inputs_hash"] = stable_hash(payload)
    return payload
