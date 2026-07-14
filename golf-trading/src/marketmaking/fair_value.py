"""Bayesian fair value: DataGolf probability as a Beta posterior.

The DataGolf forecast probability is treated as the mean of a
Beta(p * ess, (1 - p) * ess) posterior, where ``ess`` (effective sample size)
encodes how much we trust the forecast for that market type. The credible
interval — not a constant — sets the minimum quotable spread downstream.
"""

from __future__ import annotations

import math

from .config import MMConfig
from .types import FairValueBand

# Normal quantiles for the two-sided credible intervals we support.
_Z_BY_CI = {0.50: 0.674, 0.80: 1.282, 0.90: 1.645, 0.95: 1.960}


def _z_for(ci: float) -> float:
    if ci not in _Z_BY_CI:
        supported = sorted(_Z_BY_CI)
        raise ValueError(f"credible_interval must be one of {supported}, got {ci}")
    return _Z_BY_CI[ci]


def fair_value_band(
    datagolf_prob: float,
    market_type: str,
    config: MMConfig,
) -> FairValueBand:
    """Posterior band around the DataGolf probability.

    Uses the normal approximation to the Beta posterior:
    sd = sqrt(p * (1 - p) / (ess + 1)).
    """
    if not 0.0 < datagolf_prob < 1.0:
        raise ValueError(f"datagolf_prob must be in (0, 1), got {datagolf_prob}")
    ess = config.ess_for(market_type)
    z = _z_for(config.credible_interval)
    sd = math.sqrt(datagolf_prob * (1.0 - datagolf_prob) / (ess + 1.0))
    return FairValueBand(
        mean=datagolf_prob,
        lo=max(0.0, datagolf_prob - z * sd),
        hi=min(1.0, datagolf_prob + z * sd),
        ess=ess,
    )
