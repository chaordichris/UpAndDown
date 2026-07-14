"""Contest-series presets for Splash portfolio generation.

Python-only presets for now; graduating these into config/settings.yaml is SP-4's job.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContestSeriesLegConfig:
    minimum_marginal_ev_cents: float
    max_golfer_exposure_count: int
    max_shared_players_between_lineups: int


@dataclass(frozen=True)
class ContestSeriesReportConfig:
    half_kelly_fraction: float = 0.5
    minimum_portfolio_ev_cents: float = 0.0
    minimum_ev_to_sd_ratio: float = 0.05
    max_ror_probability: float = 0.05
    ror_simulations: int = 2_000


@dataclass(frozen=True)
class ContestSeriesConfig:
    name: str
    conservative: ContestSeriesLegConfig
    convex: ContestSeriesLegConfig
    report: ContestSeriesReportConfig
    max_entries_cap: int = 33


RUNGOOD_SERIES = ContestSeriesConfig(
    name="rungood",
    conservative=ContestSeriesLegConfig(
        minimum_marginal_ev_cents=250.0,
        max_golfer_exposure_count=8,
        max_shared_players_between_lineups=3,
    ),
    convex=ContestSeriesLegConfig(
        minimum_marginal_ev_cents=0.0,
        max_golfer_exposure_count=14,
        max_shared_players_between_lineups=4,
    ),
    report=ContestSeriesReportConfig(),
    max_entries_cap=33,
)

SERIES_PRESETS: dict[str, ContestSeriesConfig] = {"rungood": RUNGOOD_SERIES}


def get_series(name: str) -> ContestSeriesConfig:
    try:
        return SERIES_PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown contest series: {name!r} (known: {sorted(SERIES_PRESETS)})") from None
