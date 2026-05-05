"""Deterministic artifact hashing for replayable workstreams."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def canonical_payload(value: Any) -> str:
    """Serialize a value in a stable, JSON-compatible form."""
    return json.dumps(
        _to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def stable_hash(value: Any) -> str:
    """Return a SHA-256 hash for a deterministic serialization of value."""
    return hashlib.sha256(canonical_payload(value).encode("utf-8")).hexdigest()


def artifact_hash(
    *,
    artifact_type: str,
    inputs: Any,
    config: Any | None = None,
    code_version: str | None = None,
) -> str:
    """Hash the replay contract for a derived artifact.

    The caller supplies only the config slice relevant to the artifact. The
    optional code_version is usually a git SHA once orchestration provides it.
    """
    return stable_hash(
        {
            "artifact_type": artifact_type,
            "inputs": inputs,
            "config": config,
            "code_version": code_version,
        }
    )


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, set):
        return sorted(_to_jsonable(v) for v in value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)
