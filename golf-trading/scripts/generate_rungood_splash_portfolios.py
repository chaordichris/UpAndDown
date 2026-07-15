"""Back-compat shim: rungood-named generator now delegates to the canonical script."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_splash_portfolios import (  # noqa: E402
    _eligible_mappings,
    _eligible_players_by_tier,
    _external_ownership_by_player_id,
    _hard_review_items,
    _ineligible_player_summary,
    main,
)

__all__ = [
    "main",
    "_hard_review_items",
    "_external_ownership_by_player_id",
    "_eligible_mappings",
    "_eligible_players_by_tier",
    "_ineligible_player_summary",
]

if __name__ == "__main__":
    main()
