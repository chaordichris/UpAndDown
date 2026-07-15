"""Back-compat shim: rungood-named sensitivity runner now delegates to the canonical script."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_splash_sensitivity import main, run_sensitivity_matrix  # noqa: E402

__all__ = ["main", "run_sensitivity_matrix"]

if __name__ == "__main__":
    main()
