"""Pure partner-ordering rules and HMAC signing (FR-29; integrations s.10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agni.integrations import auth
from agni.integrations.domain.ordering import (
    APPLY,
    DUPLICATE,
    OLDER_THAN_APPLIED,
    SEQUENCE_GAP,
    Applied,
    classify,
    freshness,
    owned_fields,
)

T0 = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("applied", "sequence", "version", "expected"),
    [
        (None, 1, "v1", APPLY),
        (None, 2, "v2", SEQUENCE_GAP),  # first contact must start the stream
        (Applied(1, "v1", T0), 2, "v2", APPLY),
        (Applied(1, "v1", T0), 1, "v1", DUPLICATE),
        (Applied(3, "v3", T0), 2, "v2", OLDER_THAN_APPLIED),
        (Applied(3, "v3", T0), 3, "v3b", OLDER_THAN_APPLIED),  # same seq, other body
        (Applied(3, "v3", T0), 5, "v5", SEQUENCE_GAP),
    ],
)
def test_sequenced_events_follow_applied_plus_one(
    applied: Applied | None, sequence: int, version: str, expected: str
) -> None:
    assert classify(applied, sequence=sequence, source_version=version, occurred_at=T0) == expected


def test_unsequenced_events_use_version_then_time() -> None:
    later = T0 + timedelta(hours=1)
    assert classify(None, sequence=None, source_version="a", occurred_at=T0) == APPLY
    applied = Applied(None, "a", T0)
    assert classify(applied, sequence=None, source_version="a", occurred_at=later) == DUPLICATE
    assert (
        classify(applied, sequence=None, source_version="b", occurred_at=T0 - timedelta(hours=1))
        == OLDER_THAN_APPLIED
    )
    assert classify(applied, sequence=None, source_version="b", occurred_at=later) == APPLY


def test_only_owned_fields_are_reflected() -> None:
    payload = {"source_status": "OPEN", "secret_note": "x", "local_reference": "AS-1"}
    assert owned_fields(payload, ["source_status", "local_reference", "missing"]) == {
        "source_status": "OPEN",
        "local_reference": "AS-1",
    }


def test_freshness_against_budget() -> None:
    assert freshness(None, 60, T0) == "UNKNOWN"
    assert freshness(T0 - timedelta(seconds=30), 60, T0) == "FRESH"
    assert freshness(T0 - timedelta(seconds=61), 60, T0) == "STALE"


def test_signature_is_bound_to_timestamp_and_body() -> None:
    body = b'{"a":1}'
    signature = auth.sign("secret", "1757667600", body)
    assert signature.startswith("sha256=") and len(signature) == 7 + 64
    assert signature != auth.sign("secret", "1757667601", body)
    assert signature != auth.sign("secret", "1757667600", b'{"a":2}')
    assert signature != auth.sign("other", "1757667600", body)
