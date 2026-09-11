"""Pure ordering rules for partner-owned records (integrations s.10). With a source sequence the
next event is exactly `applied + 1`; anything lower is older (or an exact duplicate), anything
higher is a gap. Without a sequence the partner's documented version wins: the same version is
a duplicate, an earlier occurrence time is older, otherwise it applies. Clocks alone never
decide when a sequence exists."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

APPLY = "APPLY"
DUPLICATE = "DUPLICATE"
SEQUENCE_GAP = "SEQUENCE_GAP"
OLDER_THAN_APPLIED = "OLDER_THAN_APPLIED"

SUPPORTED_EVENT_TYPES = frozenset({"partner.case.status_changed", "partner.case.snapshot"})
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
REQUIRED_PAYLOAD_FIELDS = ("source_version",)


@dataclass(frozen=True)
class Applied:
    sequence: int | None
    source_version: str
    occurred_at: datetime | None


def classify(
    applied: Applied | None,
    *,
    sequence: int | None,
    source_version: str,
    occurred_at: datetime,
) -> str:
    if sequence is not None:
        if applied is None or applied.sequence is None:
            # First contact must start the stream; a later first event is a gap that only a
            # verified source lookup can close.
            return APPLY if sequence == 1 else SEQUENCE_GAP
        if sequence <= applied.sequence:
            if sequence == applied.sequence and source_version == applied.source_version:
                return DUPLICATE
            return OLDER_THAN_APPLIED
        if sequence == applied.sequence + 1:
            return APPLY
        return SEQUENCE_GAP
    if applied is None:
        return APPLY
    if source_version == applied.source_version:
        return DUPLICATE
    if applied.occurred_at is not None and occurred_at < applied.occurred_at:
        return OLDER_THAN_APPLIED
    return APPLY


def owned_fields(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Only the fields the partner is the system of record for are ever reflected locally."""
    return {key: payload[key] for key in fields if key in payload}


def freshness(last_event_at: datetime | None, budget_seconds: int, now: datetime) -> str:
    if last_event_at is None:
        return "UNKNOWN"
    return "FRESH" if (now - last_event_at).total_seconds() <= budget_seconds else "STALE"
