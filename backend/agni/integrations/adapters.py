"""Partner source adapters. The simulator implements the full semantic contract (records with
sequence and version, transient / unknown / not-found fixtures, probes). SANDBOX and LIVE modes
have no approved endpoint in this build and answer honestly with an unconfigured adapter - a
Connected badge is never fabricated (integrations s.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import uuid4

from .models import Integration, IntegrationMode
from .ports import (
    PartnerCaseSource,
    PartnerSourceNotFound,
    PartnerSourceUnavailable,
    PartnerSourceUnknown,
    ProbeResult,
    SourceRecord,
)

DEMO_ENTITY = "UPG-DEMO-2026-0001"


class SimulatedPartnerCaseSource:
    """In-process partner with a small owned dataset. Tests and the smoke drill set records."""

    records: ClassVar[dict[str, dict[str, Any]]] = {}
    force_unavailable: ClassVar[bool] = False
    force_unknown: ClassVar[bool] = False
    requests: ClassVar[list[str]] = []

    @classmethod
    def reset(cls) -> None:
        cls.records = {}
        cls.force_unavailable = False
        cls.force_unknown = False
        cls.requests = []

    @classmethod
    def set_record(
        cls,
        source_entity_id: str,
        *,
        source_version: str,
        sequence: int | None,
        payload: dict[str, Any],
    ) -> None:
        cls.records[source_entity_id] = {
            "source_version": source_version,
            "sequence": sequence,
            "payload": {**payload, "source_version": source_version},
        }

    @classmethod
    def ensure_demo_dataset(cls) -> None:
        if DEMO_ENTITY not in cls.records:
            cls.set_record(
                DEMO_ENTITY,
                source_version="v3",
                sequence=3,
                payload={
                    "source_status": "UNDER_REVIEW",
                    "source_reference": DEMO_ENTITY,
                    "source_updated_at": "2026-09-10T09:00:00+00:00",
                },
            )

    def lookup_case(self, source_entity_id: str) -> SourceRecord:
        request_id = f"sim-{uuid4().hex[:12]}"
        type(self).requests.append(request_id)
        if type(self).force_unavailable:
            raise PartnerSourceUnavailable("simulated partner endpoint unreachable")
        if type(self).force_unknown:
            raise PartnerSourceUnknown("simulated partner answered ambiguously")
        record = type(self).records.get(source_entity_id)
        if record is None:
            raise PartnerSourceNotFound(source_entity_id)
        return SourceRecord(
            source_entity_id=source_entity_id,
            source_version=str(record["source_version"]),
            sequence=record["sequence"],
            payload=dict(record["payload"]),
            fetched_at=datetime.now(UTC),
            provider_request_id=request_id,
        )

    def test(self, test_case_key: str) -> ProbeResult:
        request_id = f"sim-probe-{uuid4().hex[:8]}"
        if type(self).force_unavailable:
            return ProbeResult("FAIL", "simulated endpoint unreachable", request_id)
        if type(self).force_unknown:
            return ProbeResult("UNKNOWN", "simulated endpoint timed out", request_id)
        return ProbeResult(
            "OK",
            f"simulated {test_case_key} probe answered (no partner workflow proven)",
            request_id,
        )


class UnconfiguredPartnerSource:
    """SANDBOX / LIVE placeholder: no approved endpoint or credential exists in this build."""

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    def lookup_case(self, source_entity_id: str) -> SourceRecord:
        raise PartnerSourceUnavailable(
            f"no approved {self.integration.mode} endpoint is configured for {self.integration.key}"
        )

    def test(self, test_case_key: str) -> ProbeResult:
        return ProbeResult(
            "FAIL",
            f"{self.integration.mode} adapter not configured; approved endpoint, credentials "
            "and contract tests are required before enablement",
            None,
        )


def get_partner_source(integration: Integration) -> PartnerCaseSource:
    if integration.mode == IntegrationMode.SIMULATED:
        SimulatedPartnerCaseSource.ensure_demo_dataset()
        return SimulatedPartnerCaseSource()
    return UnconfiguredPartnerSource(integration)
