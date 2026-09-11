"""Typed ports for partner sources (integrations s.2 `PartnerCaseSource`). Adapters implement
them; application code never talks to a provider directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class PartnerSourceUnavailable(Exception):
    """Transient: the approved source endpoint could not be reached."""


class PartnerSourceUnknown(Exception):
    """The source answered ambiguously; nothing may be inferred."""


class PartnerSourceNotFound(Exception):
    """The source has no such record."""


@dataclass(frozen=True)
class SourceRecord:
    source_entity_id: str
    source_version: str
    sequence: int | None
    payload: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    provider_request_id: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    status: str  # OK | FAIL | UNKNOWN
    detail: str
    provider_request_id: str | None = None


class PartnerCaseSource(Protocol):
    def lookup_case(self, source_entity_id: str) -> SourceRecord:
        """Authoritative current record from the approved reconciliation endpoint."""

    def test(self, test_case_key: str) -> ProbeResult:
        """Allowlisted non-destructive probe."""
