"""Authenticated partner inbox (API-109) and ordered asynchronous application (FR-29;
integrations s.10). Intake persists the authenticated event and answers 202 PROCESSING; the
durable `integration.apply` job classifies it against the entity's applied sequence / version
and either reflects the partner-owned fields, ignores an exact duplicate, or opens an owned
conflict. An older event never overwrites a newer reflection; a gap waits for its predecessor
or for a verified source lookup."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils.dateparse import parse_datetime

from agni.cases.models import Application
from agni.platform import audit, jobs, outbox
from agni.platform.canonical import canonical_sha256
from agni.platform.errors import (
    IdempotencyConflict,
    MalformedRequest,
    ServiceDisabled,
    ValidationFailed,
    Violation,
)
from agni.platform.jobs import JobResult, register
from agni.platform.models import AttemptOutcome, LogicalJob

from .. import auth
from ..domain.ordering import (
    APPLY,
    DUPLICATE,
    REQUIRED_PAYLOAD_FIELDS,
    SEQUENCE_GAP,
    SUPPORTED_EVENT_TYPES,
    SUPPORTED_SCHEMA_VERSIONS,
    Applied,
    classify,
    owned_fields,
)
from ..models import (
    ConflictReason,
    ConflictState,
    InboxState,
    Integration,
    IntegrationConflict,
    IntegrationInbox,
    IntegrationState,
    PartnerEntityState,
    ResolutionOutcome,
)

APPLY_JOB_KIND = "integration.apply"
MAX_BODY_BYTES = 256 * 1024
SYSTEM_REQUEST_NAMESPACE = UUID("6f1b2f3c-4d5e-4f60-8a71-92b3c4d5e6f7")

RECEIPT_STATE = {
    InboxState.RECEIVED: "PROCESSING",
    InboxState.PROCESSED: "PROCESSED",
    InboxState.QUARANTINED: "QUARANTINED",
    InboxState.CONFLICT: "CONFLICT",
}


def receipt(inbox: IntegrationInbox, *, duplicate: bool) -> dict[str, Any]:
    return {
        "receipt_id": str(inbox.pk),
        "source_event_id": inbox.source_event_id,
        "source_entity_id": inbox.source_entity_id,
        "state": RECEIPT_STATE[InboxState(inbox.state)],
        "disposition": inbox.disposition,
        "duplicate": duplicate,
        "received_at": inbox.received_at.isoformat(),
        "notice": (
            "Receipt means the authenticated event is stored; PROCESSING is not applied success."
        ),
    }


def parse_partner_event(raw: bytes) -> dict[str, Any]:
    """PartnerEvent (docs/24): structural validation only; business ordering happens later."""
    if len(raw) > MAX_BODY_BYTES:
        raise MalformedRequest("Partner event body exceeds the accepted size")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedRequest("Partner event body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise MalformedRequest("Partner event body must be a JSON object")
    violations: list[Violation] = []
    allowed = {
        "source_event_id",
        "source_entity_id",
        "source_sequence",
        "occurred_at",
        "schema_version",
        "event_type",
        "payload",
    }
    violations.extend(
        Violation(f"/{k}", "unknown_field", "unknown field") for k in sorted(set(data) - allowed)
    )
    for key in ("source_event_id", "source_entity_id"):
        value = data.get(key)
        if not isinstance(value, str) or not (1 <= len(value) <= 160):
            violations.append(Violation(f"/{key}", "length", "1 to 160 characters"))
    sequence = data.get("source_sequence")
    if sequence is not None and (
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
    ):
        violations.append(Violation("/source_sequence", "invalid", "positive integer"))
    occurred = parse_datetime(str(data.get("occurred_at") or ""))
    if occurred is None or occurred.tzinfo is None:
        violations.append(Violation("/occurred_at", "format", "ISO 8601 UTC timestamp"))
    if str(data.get("schema_version")) not in SUPPORTED_SCHEMA_VERSIONS:
        violations.append(
            Violation(
                "/schema_version",
                "unsupported",
                f"approved versions: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}",
            )
        )
    if str(data.get("event_type")) not in SUPPORTED_EVENT_TYPES:
        violations.append(Violation("/event_type", "unsupported", "not an approved event type"))
    payload = data.get("payload")
    if not isinstance(payload, dict):
        violations.append(Violation("/payload", "invalid", "must be an object"))
    else:
        for key in REQUIRED_PAYLOAD_FIELDS:
            if not isinstance(payload.get(key), str) or not payload[key]:
                violations.append(Violation(f"/payload/{key}", "required", "required string"))
    if violations:
        raise ValidationFailed(violations=violations)
    return data


def _system_request_id(inbox_id: UUID) -> UUID:
    from uuid import uuid5

    return uuid5(SYSTEM_REQUEST_NAMESPACE, str(inbox_id))


def _open_conflict(
    inbox: IntegrationInbox | None,
    integration: Integration,
    *,
    entity: str,
    reason: str,
    detail: dict[str, Any],
    now: datetime,
) -> IntegrationConflict:
    existing = None
    if inbox is not None:
        existing = IntegrationConflict.objects.filter(
            inbox=inbox, reason_code=reason, state=ConflictState.OPEN
        ).first()
    if existing is not None:
        return existing
    conflict = IntegrationConflict.objects.create(
        inbox=inbox,
        integration=integration,
        source_entity_id=entity,
        reason_code=reason,
        owner_queue=integration.owner_queue,
        detail=detail,
    )
    audit.record_audit(
        entity_type="integration_conflict",
        entity_id=conflict.pk,
        action="integration.conflict_detected",
        actor_id=None,
        request_id=_system_request_id(inbox.pk if inbox else conflict.pk),
        at=now,
        summary={
            "integration": integration.key,
            "reason_code": reason,
            "source_entity_id": entity,
            **{k: v for k, v in detail.items() if k != "payload"},
        },
    )
    outbox.enqueue_intent(
        event_type="integration.conflict_detected.v1",
        aggregate_type="integration_conflict",
        aggregate_id=conflict.pk,
        payload={
            "conflict_id": str(conflict.pk),
            "integration": integration.key,
            "reason_code": reason,
            "source_entity_id": entity,
            "owner_queue_id": str(integration.owner_queue_id)
            if integration.owner_queue_id
            else None,
        },
        available_at=now,
    )
    return conflict


def receive_event(
    integration: Integration, raw: bytes, headers: Mapping[str, str], *, now: datetime
) -> tuple[int, dict[str, Any]]:
    """API-109: authenticate on raw bytes, validate structure, persist once, answer 202."""
    if integration.state == IntegrationState.DISABLED:
        raise ServiceDisabled("This integration is disabled; events are not accepted")
    evidence = auth.verify(integration, headers, raw, now=now)
    event = parse_partner_event(raw)
    digest = canonical_sha256(event)
    occurred_at = parse_datetime(str(event["occurred_at"]))
    if occurred_at is None:  # pragma: no cover - parse_partner_event already validated it
        raise MalformedRequest("occurred_at is not a timestamp")
    mismatch: IntegrationConflict | None = None
    with transaction.atomic():
        existing = (
            IntegrationInbox.objects.select_for_update()
            .filter(integration=integration, source_event_id=event["source_event_id"])
            .first()
        )
        if existing is not None:
            if existing.payload_sha256 == digest:
                return 202, receipt(existing, duplicate=True)
            # The conflict row must survive the 409, so it is committed with this block and
            # the error is raised after it.
            mismatch = _open_conflict(
                existing,
                integration,
                entity=existing.source_entity_id,
                reason=ConflictReason.PAYLOAD_MISMATCH,
                detail={
                    "stored_sha256": existing.payload_sha256,
                    "received_sha256": digest,
                    "source_event_id": existing.source_event_id,
                },
                now=now,
            )
    if mismatch is not None and existing is not None:
        raise IdempotencyConflict(
            "This source event id was already received with a different body",
            extensions={"receipt_id": str(existing.pk), "conflict_id": str(mismatch.pk)},
        )
    with transaction.atomic():
        inbox = IntegrationInbox.objects.create(
            integration=integration,
            source_event_id=event["source_event_id"],
            source_entity_id=event["source_entity_id"],
            source_sequence=event.get("source_sequence"),
            event_type=event["event_type"],
            schema_version=str(event["schema_version"]),
            occurred_at=occurred_at,
            received_at=now,
            payload=event["payload"],
            payload_sha256=digest,
            auth_evidence=evidence,
        )
        Integration.objects.filter(pk=integration.pk).update(last_event_at=now)
        jobs.enqueue_job(
            kind=APPLY_JOB_KIND,
            aggregate_ref={"inbox_id": str(inbox.pk)},
            run_at=now,
            logical_action_id=inbox.pk,
            owner_queue_id=integration.owner_queue_id,
        )
        audit.record_audit(
            entity_type="integration_inbox",
            entity_id=inbox.pk,
            action="integration.event_received",
            actor_id=None,
            request_id=_system_request_id(inbox.pk),
            at=now,
            summary={
                "integration": integration.key,
                "event_type": inbox.event_type,
                "source_entity_id": inbox.source_entity_id,
                "source_sequence": inbox.source_sequence,
                "sha256_prefix": digest[:12],
                "auth": evidence["scheme"],
            },
        )
    return 202, receipt(inbox, duplicate=False)


def apply_snapshot(
    state: PartnerEntityState,
    integration: Integration,
    *,
    sequence: int | None,
    source_version: str,
    occurred_at: datetime | None,
    event_id: str,
    payload: Mapping[str, Any],
) -> None:
    state.snapshot = {
        **state.snapshot,
        **owned_fields(payload, integration.system_of_record_fields),
    }
    state.applied_sequence = sequence
    state.applied_source_version = source_version
    state.applied_event_id = event_id
    state.applied_occurred_at = occurred_at
    local_reference = payload.get("local_reference")
    if isinstance(local_reference, str) and local_reference:
        state.application = Application.objects.filter(public_reference=local_reference).first()
    state.version += 1
    state.save()


def _entity_state(integration: Integration, entity: str) -> PartnerEntityState:
    state, _ = PartnerEntityState.objects.select_for_update().get_or_create(
        integration=integration, source_entity_id=entity
    )
    return state


def _applied(state: PartnerEntityState) -> Applied | None:
    if state.applied_sequence is None and not state.applied_source_version:
        return None
    return Applied(state.applied_sequence, state.applied_source_version, state.applied_occurred_at)


def release_successors(integration: Integration, state: PartnerEntityState, now: datetime) -> int:
    """After an application, the next-in-sequence events waiting in CONFLICT (gap) or RECEIVED
    become processable: reopen them and enqueue a fresh apply job."""
    if state.applied_sequence is None:
        return 0
    waiting = IntegrationInbox.objects.select_for_update().filter(
        integration=integration,
        source_entity_id=state.source_entity_id,
        source_sequence=state.applied_sequence + 1,
        state__in=[InboxState.CONFLICT, InboxState.RECEIVED],
    )
    released = 0
    for row in waiting:
        IntegrationConflict.objects.filter(
            inbox=row, reason_code=ConflictReason.SEQUENCE_GAP, state=ConflictState.OPEN
        ).update(
            state=ConflictState.RESOLVED,
            outcome=ResolutionOutcome.PREDECESSOR_ARRIVED,
            resolved_at=now,
            resolution_basis={
                "outcome": "PREDECESSOR_ARRIVED",
                "applied_sequence": state.applied_sequence,
            },
        )
        row.state = InboxState.RECEIVED
        row.error_code = None
        row.save(update_fields=["state", "error_code"])
        jobs.enqueue_job(
            kind=APPLY_JOB_KIND,
            aggregate_ref={"inbox_id": str(row.pk)},
            run_at=now,
            logical_action_id=uuid4(),
            owner_queue_id=integration.owner_queue_id,
        )
        released += 1
    return released


@register(APPLY_JOB_KIND)
def apply_inbox_event(job: LogicalJob) -> JobResult:
    inbox_id = UUID(str(job.aggregate_ref.get("inbox_id")))
    now = jobs.current_clock().now()
    with transaction.atomic():
        inbox = (
            IntegrationInbox.objects.select_for_update()
            .select_related("integration")
            .filter(pk=inbox_id)
            .first()
        )
        if inbox is None:
            return JobResult(AttemptOutcome.PERMANENT, error_code="RESOURCE_NOT_FOUND")
        if inbox.state != InboxState.RECEIVED:
            return JobResult(AttemptOutcome.SUCCESS, disposition="CANCELLED_AS_OBSOLETE")
        integration = inbox.integration
        source_version = str(inbox.payload.get("source_version") or "")
        state = _entity_state(integration, inbox.source_entity_id)
        verdict = classify(
            _applied(state),
            sequence=inbox.source_sequence,
            source_version=source_version,
            occurred_at=inbox.occurred_at,
        )
        if verdict == APPLY:
            apply_snapshot(
                state,
                integration,
                sequence=inbox.source_sequence,
                source_version=source_version,
                occurred_at=inbox.occurred_at,
                event_id=inbox.source_event_id,
                payload=inbox.payload,
            )
            inbox.state = InboxState.PROCESSED
            inbox.disposition = "APPLIED"
            inbox.processed_at = now
            inbox.save(update_fields=["state", "disposition", "processed_at"])
            audit.record_audit(
                entity_type="partner_entity",
                entity_id=state.pk,
                action="integration.event_applied",
                actor_id=None,
                request_id=_system_request_id(inbox.pk),
                at=now,
                summary={
                    "integration": integration.key,
                    "source_entity_id": inbox.source_entity_id,
                    "source_event_id": inbox.source_event_id,
                    "sequence": inbox.source_sequence,
                    "source_version": source_version,
                    "fields": sorted(
                        owned_fields(inbox.payload, integration.system_of_record_fields)
                    ),
                },
            )
            outbox.enqueue_intent(
                event_type="integration.source_applied.v1",
                aggregate_type="partner_entity",
                aggregate_id=state.pk,
                payload={
                    "integration": integration.key,
                    "source_entity_id": inbox.source_entity_id,
                    "sequence": inbox.source_sequence,
                    "source_version": source_version,
                    "application_id": str(state.application_id) if state.application_id else None,
                },
                available_at=now,
            )
            release_successors(integration, state, now)
            return JobResult(AttemptOutcome.SUCCESS, disposition="APPLIED")
        if verdict == DUPLICATE:
            inbox.state = InboxState.PROCESSED
            inbox.disposition = "IGNORED_DUPLICATE"
            inbox.processed_at = now
            inbox.save(update_fields=["state", "disposition", "processed_at"])
            return JobResult(AttemptOutcome.SUCCESS, disposition="IGNORED_DUPLICATE")
        reason = (
            ConflictReason.SEQUENCE_GAP
            if verdict == SEQUENCE_GAP
            else ConflictReason.OLDER_THAN_APPLIED
        )
        inbox.state = InboxState.CONFLICT
        inbox.error_code = reason
        inbox.save(update_fields=["state", "error_code"])
        _open_conflict(
            inbox,
            integration,
            entity=inbox.source_entity_id,
            reason=reason,
            detail={
                "received_sequence": inbox.source_sequence,
                "received_source_version": source_version,
                "applied_sequence": state.applied_sequence,
                "applied_source_version": state.applied_source_version,
                "expected_sequence": (state.applied_sequence or 0) + 1
                if inbox.source_sequence is not None
                else None,
                "source_event_id": inbox.source_event_id,
            },
            now=now,
        )
        return JobResult(AttemptOutcome.SUCCESS, disposition=reason)
