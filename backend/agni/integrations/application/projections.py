"""Read projections for UI-25: sanitised configuration (secret references only), health,
freshness, inbox summaries without payloads and conflict records with their safe detail."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.ordering import freshness
from ..models import (
    ConflictState,
    InboxState,
    Integration,
    IntegrationConflict,
    IntegrationInbox,
    PartnerEntityState,
)


def integration_body(integration: Integration, *, now: datetime) -> dict[str, Any]:
    from .commands import allowed_tests

    return {
        "integration_id": str(integration.pk),
        "key": integration.key,
        "display_name": integration.display_name,
        "mode": integration.mode,
        "provider_kind": integration.provider_kind,
        "state": integration.state,
        "capabilities": list(integration.capabilities),
        "system_of_record_fields": list(integration.system_of_record_fields),
        "endpoint_allowlist": list(integration.endpoint_allowlist),
        "credential_secret_ref": integration.credential_secret_ref or None,
        "credential_configured": bool(integration.credential_secret_ref),
        "owner_queue": integration.owner_queue.queue_key if integration.owner_queue else None,
        "freshness": freshness(
            integration.last_event_at, integration.freshness_budget_seconds, now
        ),
        "freshness_budget_seconds": integration.freshness_budget_seconds,
        "last_event_at": integration.last_event_at.isoformat()
        if integration.last_event_at
        else None,
        "last_health_status": integration.last_health_status,
        "last_health_at": integration.last_health_at.isoformat()
        if integration.last_health_at
        else None,
        "last_health_detail": integration.last_health_detail,
        "allowed_tests": list(allowed_tests(integration)),
        "open_conflicts": integration.conflicts.filter(state=ConflictState.OPEN).count(),
        "inbox_counts": {
            state: integration.inbox.filter(state=state).count() for state in InboxState.values
        },
        "notice": (
            "A Connected or OK badge is not evidence of an end-to-end regulatory integration; "
            "SIMULATED and SANDBOX modes never carry live legal effect."
        ),
        "version": integration.version,
        "etag": integration.etag,
    }


def inbox_body(row: IntegrationInbox) -> dict[str, Any]:
    return {
        "receipt_id": str(row.pk),
        "source_event_id": row.source_event_id,
        "source_entity_id": row.source_entity_id,
        "source_sequence": row.source_sequence,
        "event_type": row.event_type,
        "schema_version": row.schema_version,
        "occurred_at": row.occurred_at.isoformat(),
        "received_at": row.received_at.isoformat(),
        "state": row.state,
        "disposition": row.disposition,
        "error_code": row.error_code,
        "payload_sha256_prefix": row.payload_sha256[:12],
        "auth_scheme": row.auth_evidence.get("scheme"),
    }


def entity_state_body(state: PartnerEntityState) -> dict[str, Any]:
    return {
        "source_entity_id": state.source_entity_id,
        "applied_sequence": state.applied_sequence,
        "applied_source_version": state.applied_source_version or None,
        "applied_event_id": state.applied_event_id or None,
        "applied_occurred_at": state.applied_occurred_at.isoformat()
        if state.applied_occurred_at
        else None,
        "snapshot": dict(state.snapshot),
        "application_id": str(state.application_id) if state.application_id else None,
        "updated_at": state.updated_at.isoformat(),
    }


def conflict_body(conflict: IntegrationConflict) -> dict[str, Any]:
    return {
        "conflict_id": str(conflict.pk),
        "integration_id": str(conflict.integration_id),
        "integration_key": conflict.integration.key,
        "source_entity_id": conflict.source_entity_id,
        "reason_code": conflict.reason_code,
        "detail": dict(conflict.detail),
        "owner_queue": conflict.owner_queue.queue_key if conflict.owner_queue else None,
        "state": conflict.state,
        "outcome": conflict.outcome,
        "resolution_basis": conflict.resolution_basis,
        "resolved_by_id": str(conflict.resolved_by_id) if conflict.resolved_by_id else None,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        "inbox": inbox_body(conflict.inbox) if conflict.inbox else None,
        "created_at": conflict.created_at.isoformat(),
        "updated_at": conflict.updated_at.isoformat(),
        "version": conflict.version,
        "etag": conflict.etag,
        "allowed_outcomes": [
            "APPLY_VERIFIED_SOURCE",
            "IGNORE_DUPLICATE",
            "REQUEST_RESEND",
            "KEEP_QUARANTINED",
        ]
        if conflict.state == ConflictState.OPEN
        else [],
    }
