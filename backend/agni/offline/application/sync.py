"""Synchronisation service (API-049/050; docs/09 s.5-7).

One client operation = one server identity. The manifest is normalised and hashed; the same id
with the same hash replays the stored result, a different hash is refused
(SYNC_PAYLOAD_CONFLICT). Accepted operations run the *online* command handlers (SubmitReport /
FailVisit) through the kernel, so current authorization, the assignment fence, version
preconditions and every domain guard apply exactly as for an online submission. A refused
operation is recorded as a CONFLICT with the safe server snapshot and the structured problem,
and automatic retries must stop on the device."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils.dateparse import parse_datetime

from agni.identity.models import Principal
from agni.inspections.application.commands import FailVisit
from agni.inspections.application.reports import SubmitReport
from agni.inspections.models import Assignment, Inspection
from agni.platform.canonical import canonical_sha256
from agni.platform.clock import Clock
from agni.platform.commands import ActorContext, CommandEnvelope, CommandResult, execute
from agni.platform.errors import (
    AssignmentChanged,
    AuthorityRevoked,
    DomainError,
    InvalidTransition,
    PreconditionRequired,
    ResourceNotFound,
    SyncPayloadConflict,
    SyncSchemaUnsupported,
    ValidationFailed,
    VersionConflict,
    Violation,
)

from ..models import OperationType, SyncOperation, SyncState

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
ENVELOPE_KEYS = {
    "operation_id",
    "operation_type",
    "inspection_id",
    "application_version",
    "base_inspection_version",
    "assignment_version",
    "schema_version",
    "captured_at",
}
REPORT_KEYS = {
    "checklist_version",
    "observations",
    "summary",
    "declaration_accepted",
    "capture_unavailable_reason",
}
VISIT_KEYS = {"reason_code", "reason", "document_version_ids", "suggested_window"}


def _positive_int(data: dict[str, Any], key: str, violations: list[Violation]) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        violations.append(Violation(f"/{key}", "invalid", "positive integer required"))
        return 0
    return value


def normalise_manifest(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the SyncOperation envelope (docs/24) and return the normalised manifest plus
    the command payload the online handler expects."""
    violations: list[Violation] = []
    op_type = data.get("operation_type")
    if op_type not in OperationType.values:
        violations.append(
            Violation(
                "/operation_type", "invalid", "SUBMIT_INSPECTION_REPORT or RECORD_FAILED_VISIT"
            )
        )
    try:
        operation_id = UUID(str(data.get("operation_id")))
    except ValueError:
        violations.append(Violation("/operation_id", "invalid", "must be a UUID"))
        operation_id = None
    try:
        inspection_id = UUID(str(data.get("inspection_id")))
    except ValueError:
        violations.append(Violation("/inspection_id", "invalid", "must be a UUID"))
        inspection_id = None
    application_version = _positive_int(data, "application_version", violations)
    base_version = _positive_int(data, "base_inspection_version", violations)
    assignment_version = _positive_int(data, "assignment_version", violations)
    schema_version = str(data.get("schema_version", ""))
    captured_at = data.get("captured_at")
    if captured_at is not None:
        parsed = parse_datetime(str(captured_at))
        if parsed is None or parsed.tzinfo is None:
            violations.append(
                Violation("/captured_at", "format", "must be an ISO 8601 UTC timestamp")
            )
    allowed = ENVELOPE_KEYS | (
        REPORT_KEYS if op_type == OperationType.SUBMIT_INSPECTION_REPORT else VISIT_KEYS
    )
    for key in sorted(set(data) - allowed):
        violations.append(Violation(f"/{key}", "unknown_field", "not part of this operation type"))
    if op_type == OperationType.RECORD_FAILED_VISIT and "observations" in data:
        violations.append(
            Violation(
                "/observations", "forbidden", "a failed visit carries no checklist observations"
            )
        )
    if violations:
        raise ValidationFailed(violations=violations)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SyncSchemaUnsupported(
            f"Offline schema {schema_version!r} is not supported; upgrade the app",
            extensions={"supported": sorted(SUPPORTED_SCHEMA_VERSIONS)},
        )
    manifest = {k: data[k] for k in sorted(data)}
    # The online handler payload: everything except the sync envelope, plus the version fences
    # and the operation identity for provenance.
    payload: dict[str, Any] = {
        k: v
        for k, v in data.items()
        if k not in ENVELOPE_KEYS
        or k in ("application_version", "assignment_version", "captured_at")
    }
    if op_type == OperationType.SUBMIT_INSPECTION_REPORT:
        payload["source_operation_id"] = str(operation_id)
    return {
        "operation_id": operation_id,
        "operation_type": op_type,
        "inspection_id": inspection_id,
        "application_version": application_version,
        "base_version": base_version,
        "assignment_version": assignment_version,
        "schema_version": schema_version,
        "manifest": manifest,
        "sha256": canonical_sha256(manifest),
        "payload": payload,
    }


def _receipt(op: dict[str, Any], result: CommandResult, *, now: datetime) -> dict[str, Any]:
    body = result.body
    if op["operation_type"] == OperationType.SUBMIT_INSPECTION_REPORT:
        entity_kind = "REPORT"
        entity_id = body.get("receipt", {}).get("report_id") or body.get("report", {}).get(
            "report_id"
        )
        application_version = body.get("receipt", {}).get("application_version")
    else:
        entity_kind = "VISIT_OUTCOME"
        entity_id = body.get("inspection_id")
        application_version = body.get("application_version")
    return {
        "operation_id": str(op["operation_id"]),
        "operation_type": op["operation_type"],
        "state": SyncState.ACCEPTED,
        "accepted_entity_kind": entity_kind,
        "accepted_entity_id": str(entity_id) if entity_id else None,
        "accepted_at": result.accepted_at.isoformat(),
        "returned_application_version": application_version,
        "returned_inspection_version": result.resulting_version,
        "command_id": str(result.command_id),
        "sha256": op["sha256"],
    }


def _server_snapshot(inspection: Inspection | None, principal: Principal) -> dict[str, Any]:
    if inspection is None:
        return {}
    current = inspection.current_assignment
    return {
        "inspection_id": str(inspection.pk),
        "inspection_version": inspection.version,
        "inspection_status": inspection.status,
        "application_version": inspection.application.version,
        "application_status": inspection.application.status,
        "assignment_version": current.version if current else None,
        "assigned_to_you": bool(
            current and current.officer_id == principal.pk and current.state == "ACTIVE"
        ),
        "has_accepted_report": inspection.current_report_id is not None,
    }


def process_operation(
    *,
    principal: Principal,
    actor: ActorContext,
    data: dict[str, Any],
    header_version: int | None,
    clock: Clock,
) -> tuple[int, dict[str, Any], int | None]:
    """Returns (status, body, resulting inspection version)."""
    op = normalise_manifest(data)
    now = clock.now()
    existing = SyncOperation.objects.filter(
        principal=principal, operation_id=op["operation_id"]
    ).first()
    if existing is not None:
        if existing.request_sha256 != op["sha256"]:
            raise SyncPayloadConflict(
                "This operation id was already used with different content; create a new operation",
                extensions={
                    "operation_id": str(op["operation_id"]),
                    "recorded_state": existing.state,
                },
            )
        body = dict(existing.result)
        body["replayed"] = True
        return (200 if existing.state == SyncState.ACCEPTED else 409), body, None
    inspection = (
        Inspection.objects.select_related("application", "current_assignment")
        .filter(pk=op["inspection_id"])
        .first()
    )
    if (
        inspection is None
        or not Assignment.objects.filter(inspection=inspection, officer=principal).exists()
    ):
        raise ResourceNotFound("Inspection not found")  # never held a package for it
    if header_version is not None and header_version != op["base_version"]:
        raise ValidationFailed(
            violations=[
                Violation("/base_inspection_version", "mismatch", "If-Match and manifest disagree")
            ]
        )
    handler: Any = (
        SubmitReport()
        if op["operation_type"] == OperationType.SUBMIT_INSPECTION_REPORT
        else FailVisit()
    )
    envelope = CommandEnvelope(
        actor=actor,
        command_name="sync:"
        + (
            "submit-report"
            if op["operation_type"] == OperationType.SUBMIT_INSPECTION_REPORT
            else "fail-visit"
        ),
        target_type="inspection",
        target_id=inspection.pk,
        payload=op["payload"],
        idempotency_key=f"sync:{op['operation_id']}",
        expected_version=op["base_version"],
    )
    try:
        with transaction.atomic():
            result = execute(envelope, handler, clock=clock)
            receipt = _receipt(op, result, now=now)
            SyncOperation.objects.create(
                operation_id=op["operation_id"],
                principal=principal,
                inspection=inspection,
                operation_type=op["operation_type"],
                request_sha256=op["sha256"],
                base_version=op["base_version"],
                assignment_version=op["assignment_version"],
                schema_version=op["schema_version"],
                state=SyncState.ACCEPTED,
                report_id=UUID(receipt["accepted_entity_id"])
                if receipt["accepted_entity_kind"] == "REPORT" and receipt["accepted_entity_id"]
                else None,
                accepted_at=result.accepted_at,
                result=receipt,
            )
    except (
        VersionConflict,
        AssignmentChanged,
        InvalidTransition,
        ValidationFailed,
        PreconditionRequired,
        AuthorityRevoked,
        ResourceNotFound,
    ) as exc:
        inspection.refresh_from_db()
        inspection = Inspection.objects.select_related("application", "current_assignment").get(
            pk=inspection.pk
        )
        conflict: DomainError = exc
        if isinstance(exc, ResourceNotFound):
            # The officer held a package but is no longer the assignee: a structured conflict,
            # not "unknown resource" (docs/09 s.7 'Assignment superseded').
            conflict = AssignmentChanged(
                "Your assignment for this attempt is no longer current; local submission is locked",
                extensions={
                    "current_assignment_version": _server_snapshot(inspection, principal)[
                        "assignment_version"
                    ]
                },
            )
        problem = conflict.to_problem(actor.request_id)
        problem.pop("request_id", None)
        snapshot = _server_snapshot(inspection, principal)
        SyncOperation.objects.create(
            operation_id=op["operation_id"],
            principal=principal,
            inspection=inspection,
            operation_type=op["operation_type"],
            request_sha256=op["sha256"],
            base_version=op["base_version"],
            assignment_version=op["assignment_version"],
            schema_version=op["schema_version"],
            state=SyncState.CONFLICT,
            result={
                "operation_id": str(op["operation_id"]),
                "operation_type": op["operation_type"],
                "state": SyncState.CONFLICT,
                "problem": problem,
                "server": snapshot,
                "recorded_at": now.isoformat(),
                "sha256": op["sha256"],
            },
        )
        raise type(conflict)(
            conflict.detail,
            violations=conflict.violations,
            extensions={
                **conflict.extensions,
                "operation_id": str(op["operation_id"]),
                "server": snapshot,
                "sync_state": "CONFLICT",
            },
        ) from exc
    return 200, {**receipt, "replayed": False}, result.resulting_version


def operation_receipt(*, principal: Principal, operation_id: UUID) -> dict[str, Any] | None:
    op = SyncOperation.objects.filter(principal=principal, operation_id=operation_id).first()
    if op is None:
        return None
    return {**op.result, "replayed": True}
