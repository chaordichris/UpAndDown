"""Market-making configuration.

Self-contained (stdlib + optional PyYAML) so the pod and its tests run
without the full app dependency stack. Reads the ``marketmaking:`` block of
``config/settings.yaml`` when present; every value has a safe default and the
pod ships disabled. Fold into ``src/config.py`` when MM-2 gate passes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class MMConfig:
    enabled: bool = False

    # Fair value posterior
    ess_by_market_type: tuple[tuple[str, float], ...] = (
        ("make_cut", 400.0),
        ("top_20", 300.0),
        ("top_10", 250.0),
        ("top_5", 200.0),
        ("outright_win", 150.0),
    )
    credible_interval: float = 0.80  # width of the posterior band
    fair_lag_steps: int = 3  # ticks our fair value lags the truth — the adverse-selection tax

    # Quoting
    min_half_spread: float = 0.02          # never quote tighter than 2c half-spread
    uncertainty_spread_mult: float = 1.0   # half-spread >= mult * posterior half-width
    max_quotable_half_width: float = 0.06  # no-quote default: stand down when too uncertain
    inventory_skew_intensity: float = 1.0  # mid shift per unit of inventory utilization
    base_quote_size: int = 10              # contracts per side at zero inventory

    # Risk (hard vetoes)
    max_position_per_market: int = 50      # contracts, absolute
    max_notional_per_tournament: float = 200.0  # dollars at risk
    daily_loss_kill_switch: float = 100.0  # dollars; flatten + stop quoting

    # Venue economics
    fee_per_contract: float = 0.0          # set from venue schedule at MM-1

    def ess_for(self, market_type: str) -> float:
        for name, ess in self.ess_by_market_type:
            if name == market_type:
                return ess
        return min(ess for _, ess in self.ess_by_market_type)


def load_mm_config(settings_path: Path = _SETTINGS_PATH) -> MMConfig:
    """Load the ``marketmaking:`` section if present, else defaults."""
    raw: dict[str, Any] = {}
    if settings_path.exists():
        try:
            import yaml  # optional dependency

            data = yaml.safe_load(settings_path.read_text()) or {}
            raw = data.get("marketmaking") or {}
        except ImportError:
            logger.warning(
                "PyYAML not installed; falling back to MMConfig defaults instead of "
                "%s's marketmaking: block. Settings.yaml overrides (including risk "
                "limits) will be silently ignored until PyYAML is available.",
                settings_path,
            )
    known = {f for f in MMConfig.__dataclass_fields__ if f != "ess_by_market_type"}
    kwargs = {k: v for k, v in raw.items() if k in known}
    if "ess_by_market_type" in raw:
        kwargs["ess_by_market_type"] = tuple(
            (str(k), float(v)) for k, v in raw["ess_by_market_type"].items()
        )
    return MMConfig(**kwargs)
