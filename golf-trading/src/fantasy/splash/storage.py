"""Storage helpers for immutable Splash API captures."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.storage.hashing import canonical_payload, stable_hash
from src.storage.models import SplashRawSnapshot


def persist_raw_snapshot(
    session: Session,
    *,
    endpoint: str,
    method: str,
    response_body: dict[str, Any],
    response_status: int | str,
    captured_at: datetime,
    url: str | None = None,
    request_body: dict[str, Any] | None = None,
    request_headers: dict[str, Any] | None = None,
    response_headers: dict[str, Any] | None = None,
) -> SplashRawSnapshot:
    """Append one Splash raw API response with deterministic provenance."""
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    status_code = _status_code(response_status)
    hash_inputs = {
        "endpoint": endpoint,
        "method": method.upper(),
        "url": url,
        "request_body": request_body,
        "response_body": response_body,
        "response_status": status_code,
        "captured_at": captured_at,
    }
    snapshot = SplashRawSnapshot(
        endpoint=endpoint,
        method=method.upper(),
        url=url,
        request_body=canonical_payload(request_body) if request_body is not None else None,
        request_headers=canonical_payload(request_headers) if request_headers is not None else None,
        response_body=json.dumps(response_body, sort_keys=True, separators=(",", ":")),
        response_headers=canonical_payload(response_headers) if response_headers is not None else None,
        response_status=status_code,
        captured_at=captured_at,
        inputs_hash=stable_hash(hash_inputs),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _status_code(value: int | str) -> int:
    if isinstance(value, int):
        return value
    match = re.search(r"\d{3}", value)
    if match is None:
        raise ValueError(f"Could not parse Splash response status: {value}")
    return int(match.group(0))
