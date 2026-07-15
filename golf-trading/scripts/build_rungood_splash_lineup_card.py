"""Back-compat shim: rungood-named lineup card builder now delegates to the canonical script."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_splash_lineup_card import (  # noqa: E402
    build_lineup_card,
    main,
    render_lineup_card_text,
)

__all__ = ["main", "build_lineup_card", "render_lineup_card_text"]

if __name__ == "__main__":
    main()
