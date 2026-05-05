from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.storage.hashing import artifact_hash, canonical_payload, stable_hash


@dataclass(frozen=True)
class HashFixture:
    name: str
    as_of: datetime
    values: list[int]


def test_stable_hash_ignores_dict_order() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert canonical_payload(left) == canonical_payload(right)
    assert stable_hash(left) == stable_hash(right)


def test_artifact_hash_changes_with_code_version() -> None:
    inputs = HashFixture(
        name="ticket",
        as_of=datetime(2024, 3, 11, tzinfo=UTC),
        values=[1, 2, 3],
    )

    old_hash = artifact_hash(artifact_type="demo", inputs=inputs, code_version="abc")
    new_hash = artifact_hash(artifact_type="demo", inputs=inputs, code_version="def")

    assert old_hash != new_hash
    assert len(old_hash) == 64
