"""Shared fixture-path/JSON I/O helpers for the Splash scripts.

Extracted because the same three tiny functions were copy-pasted verbatim
into ~7 scripts — a fix to one (e.g. the provenance-path fallback for
out-of-repo-root fixtures) had to be applied by hand to each copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def fixture_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
