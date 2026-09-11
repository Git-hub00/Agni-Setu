"""Controlled exports (API-082..084; FR-26; security s.8). The request freezes the scope
(population ids or reader scope), the field set, the purpose and the cutoff; a durable job writes
a CSV with neutralised cells to private storage; access is reauthorised against the *current*
scope, expires, and is audited. No permanent object URL ever leaves the server."""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

from agni.cases.models import Application
from agni.certificates.application.registry import effective_status
from agni.certificates.models import Certificate
from agni.documents.adapters import get_object_store
from agni.documents.ports import ObjectStoreError, ObjectStoreUnavailable
from agni.identity.authz import AuthzSnapshot, load_snapshot
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import PrincipalKind
from agni.platform import audit_reader, jobs
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import Forbidden, ServiceDisabled, ValidationFailed, Violation
from agni.platform.jobs import JobResult, register
from agni.platform.models import AttemptOutcome, LogicalJob

from ..domain.metrics import DEFINITION_VERSION, csv_safe
from ..models import ExportJob, ExportKind, ExportState
from .metrics import metrics_snapshot, parse_filters, population, scope_descriptor, states_at_cutoff

EXPORT_JOB_KIND = "export.generate"
EXPORT_TTL = timedelta(hours=24)
MAX_ROWS = 10_000
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024

# Approved, minimised field sets per kind (no applicant contacts, no evidence references).
FIELD_SETS: dict[str, dict[str, list[str]]] = {
    ExportKind.CASES: {
        "case-summary": [
            "public_reference",
            "status_at_cutoff",
            "premises_display_name",
            "category_key",
            "locality",
            "owner_queue",
            "submitted_at",
            "updated_at",
        ],
    },
    ExportKind.CERTIFICATES: {
        "register": [
            "certificate_number",
            "effective_status",
            "recorded_status",
            "premises_display_name",
            "locality",
            "issued_at",
            "valid_until",
            "is_demo",
        ],
    },
    ExportKind.AUDIT: {
        "audit-summary": [
            "timestamp",
            "entity_type",
            "entity_id",
            "action",
            "actor_id",
            "request_id",
        ],
    },
    ExportKind.REPORT: {"metrics": ["metric", "value", "definition"]},
}


def export_body(job: ExportJob, *, scope_valid: bool | None = None) -> dict[str, Any]:
    return {
        "export_id": str(job.pk),
        "kind": job.kind,
        "field_set_key": job.field_set_key,
        "fields": FIELD_SETS.get(str(job.kind), {}).get(job.field_set_key, []),
        "purpose": job.purpose,
        "filters": job.filter_snapshot,
        "scope": {k: v for k, v in job.scope_snapshot.items() if k != "population_ids"},
        "population": len(job.scope_snapshot.get("population_ids", []))
        if "population_ids" in job.scope_snapshot
        else None,
        "as_of": job.as_of.isoformat(),
        "definition_version": job.definition_version,
        "state": job.state,
        "row_count": job.row_count,
        "expires_at": job.expires_at.isoformat(),
        "last_error_code": job.last_error_code,
        "requester_id": str(job.requester_id),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "version": job.version,
        "etag": job.etag,
        "scope_valid": scope_valid,
        "allowed_actions": [
            {
                "key": "access",
                "enabled": job.state == ExportState.COMPLETE and scope_valid is not False,
                "reason_code": None
                if job.state == ExportState.COMPLETE and scope_valid is not False
                else ("NOT_COMPLETE" if job.state != ExportState.COMPLETE else "SCOPE_CHANGED"),
            }
        ],
    }


def authorize_kind(snapshot: AuthzSnapshot, kind: str) -> str:
    """Security s.5: applicants export their own cases; supervisors their jurisdictions with a
    purpose; leadership needs the `export.sensitive` grant; operations administrators export
    metrics and (with the grant) audit summaries. Returns the scope label."""
    if not snapshot.active:
        raise Forbidden("Account is not active")
    if snapshot.kind == PrincipalKind.APPLICANT:
        if kind in (ExportKind.CASES, ExportKind.CERTIFICATES, ExportKind.REPORT):
            return "OWN_CASES"
        raise Forbidden("Applicants export their own cases only")
    if kind == ExportKind.AUDIT:
        if (snapshot.has_role(RoleKey.ADMIN) or snapshot.has_role(RoleKey.LEADERSHIP)) and (
            snapshot.grant_for(Capability.EXPORT_SENSITIVE) is not None
        ):
            return "AUDIT_SCOPE"
        raise Forbidden("Audit exports need leadership or operations scope plus export.sensitive")
    if snapshot.has_role(RoleKey.SUPERVISOR):
        return "JURISDICTIONS"
    if snapshot.has_role(RoleKey.LEADERSHIP):
        if snapshot.grant_for(Capability.EXPORT_SENSITIVE) is None:
            raise Forbidden("Leadership exports need the export.sensitive grant")
        return "JURISDICTIONS"
    if snapshot.has_role(RoleKey.ADMIN) and kind == ExportKind.REPORT:
        return "GLOBAL"
    raise Forbidden("Your roles do not permit this export")


def frozen_population(
    snapshot: AuthzSnapshot, kind: str, filters: dict[str, Any], as_of: datetime
) -> list[str]:
    if kind in (ExportKind.CASES, ExportKind.REPORT):
        return [
            str(pk)
            for pk in population(snapshot, filters, as_of).values_list("pk", flat=True)[:MAX_ROWS]
        ]
    if kind == ExportKind.CERTIFICATES:
        apps = population(snapshot, filters, as_of).values("pk")
        return [
            str(pk)
            for pk in Certificate.objects.filter(application__in=apps, issued_at__lte=as_of)
            .order_by("issued_at")
            .values_list("pk", flat=True)[:MAX_ROWS]
        ]
    return []


def current_population(snapshot: AuthzSnapshot, job: ExportJob, now: datetime) -> set[str]:
    filters = dict(job.filter_snapshot)
    if job.kind in (ExportKind.CASES, ExportKind.REPORT):
        return {
            str(pk) for pk in population(snapshot, filters, job.as_of).values_list("pk", flat=True)
        }
    if job.kind == ExportKind.CERTIFICATES:
        apps = population(snapshot, filters, job.as_of).values("pk")
        return {
            str(pk)
            for pk in Certificate.objects.filter(
                application__in=apps, issued_at__lte=job.as_of
            ).values_list("pk", flat=True)
        }
    return set()


def scope_still_covers(snapshot: AuthzSnapshot, job: ExportJob, now: datetime) -> bool:
    """Access is reauthorised against the reader's current scope: the frozen population must
    still be entirely visible; audit exports need the role/grant still in force."""
    try:
        authorize_kind(snapshot, str(job.kind))
    except Forbidden:
        return False
    if job.kind == ExportKind.AUDIT:
        return True
    frozen = set(job.scope_snapshot.get("population_ids", []))
    return frozen <= current_population(snapshot, job, now)


class CreateExport(CommandHandler[ExportJob]):
    """API-082: persist scope, purpose, field set and cutoff; generation is asynchronous."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only signed-in accounts request exports")

    def lock_target(self, uow: UnitOfWork) -> ExportJob | None:
        return None

    def apply(self, uow: UnitOfWork, target: ExportJob | None) -> CommandOutcome[ExportJob]:
        data = dict(uow.envelope.payload)
        allowed = {"kind", "field_set_key", "filters", "purpose", "format", "as_of"}
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        kind = str(data.get("kind") or "")
        if kind not in ExportKind.values:
            violations.append(Violation("/kind", "invalid", "CASES, CERTIFICATES, AUDIT or REPORT"))
        field_set = str(data.get("field_set_key") or "")
        if kind in ExportKind.values and field_set not in FIELD_SETS.get(kind, {}):
            violations.append(
                Violation(
                    "/field_set_key",
                    "invalid",
                    f"approved field sets: {', '.join(sorted(FIELD_SETS.get(kind, {})))}",
                )
            )
        purpose = data.get("purpose")
        if not isinstance(purpose, str) or not (10 <= len(purpose.strip()) <= 500):
            violations.append(Violation("/purpose", "length", "10 to 500 characters"))
            purpose = ""
        fmt = str(data.get("format") or "CSV").upper()
        if fmt not in ("CSV", "PDF"):
            violations.append(Violation("/format", "invalid", "CSV or PDF"))
        raw_filters = data.get("filters", {})
        if raw_filters is None:
            raw_filters = {}
        if not isinstance(raw_filters, dict):
            violations.append(Violation("/filters", "invalid", "must be an object"))
            raw_filters = {}
        params = {**raw_filters, **({"as_of": data["as_of"]} if data.get("as_of") else {})}
        filters, as_of, filter_violations = parse_filters(params, now=uow.now)
        violations.extend(filter_violations)
        if kind == ExportKind.AUDIT:
            audit_filters, audit_violations = audit_reader.parse_audit_filters(raw_filters)
            violations.extend(audit_violations)
            filters = audit_filters
        if violations:
            raise ValidationFailed(violations=violations)
        if fmt == "PDF":
            raise ServiceDisabled("PDF exports are not enabled in this build; request CSV")
        snapshot = load_snapshot(uow.actor, uow.now)
        scope_label = authorize_kind(snapshot, kind)
        if kind == ExportKind.AUDIT:
            audit_reader.audit_scope(snapshot, uow.now)  # raises when out of scope
        ids = frozen_population(snapshot, kind, filters, as_of)
        job = ExportJob.objects.create(
            requester=uow.actor,
            kind=kind,
            field_set_key=field_set,
            purpose=purpose.strip(),
            scope_snapshot={
                **scope_descriptor(snapshot),
                "label": scope_label,
                "population_ids": ids,
                "reader_kind": snapshot.kind,
            },
            filter_snapshot=filters,
            as_of=as_of,
            expires_at=uow.now + EXPORT_TTL,
            definition_version=DEFINITION_VERSION,
            logical_action_id=uuid4(),
        )
        jobs.enqueue_job(
            kind=EXPORT_JOB_KIND,
            aggregate_ref={"export_id": str(job.pk)},
            run_at=uow.now,
            logical_action_id=job.logical_action_id,
        )
        return CommandOutcome(
            status=202,
            body=export_body(job, scope_valid=True),
            aggregate=job,
            created=True,
            audits=[
                AuditEntry(
                    "export_job",
                    job.pk,
                    "export.requested",
                    {
                        "kind": kind,
                        "field_set_key": field_set,
                        "purpose": purpose.strip()[:200],
                        "population": len(ids),
                        "as_of": as_of.isoformat(),
                        "scope": scope_label,
                    },
                )
            ],
        )


# ---- generation ---------------------------------------------------------------------------------


def _rows_cases(job: ExportJob) -> list[list[str]]:
    ids = [UUID(x) for x in job.scope_snapshot.get("population_ids", [])]
    states = states_at_cutoff(ids, job.as_of)
    rows: list[list[str]] = []
    for a in (
        Application.objects.filter(pk__in=ids)
        .select_related("premises", "owner_queue")
        .order_by("submitted_at")
    ):
        rows.append(
            [
                a.public_reference or a.draft_reference,
                states.get(a.pk, "UNKNOWN"),
                a.premises.display_name,
                a.premises.category_key,
                a.premises.locality,
                a.owner_queue.queue_key,
                a.submitted_at.isoformat() if a.submitted_at else "",
                a.updated_at.isoformat(),
            ]
        )
    return rows


def _rows_certificates(job: ExportJob) -> list[list[str]]:
    ids = [UUID(x) for x in job.scope_snapshot.get("population_ids", [])]
    rows: list[list[str]] = []
    for c in (
        Certificate.objects.filter(pk__in=ids)
        .select_related("application__premises")
        .order_by("issued_at")
    ):
        rows.append(
            [
                c.certificate_number,
                effective_status(c, job.as_of),
                str(c.recorded_status),
                c.application.premises.display_name,
                c.application.premises.locality,
                c.issued_at.isoformat(),
                c.valid_until.isoformat() if c.valid_until else "",
                "true" if c.is_demo else "false",
            ]
        )
    return rows


def _rows_audit(job: ExportJob) -> list[list[str]]:
    snapshot = load_snapshot(job.requester, job.as_of)
    queryset, _ = audit_reader.audit_scope(snapshot, job.as_of)
    queryset = audit_reader.apply_filters(queryset, dict(job.filter_snapshot)).filter(
        timestamp__lte=job.as_of
    )
    return [
        [
            r.timestamp.isoformat(),
            r.entity_type,
            str(r.entity_id),
            r.action,
            str(r.actor_id) if r.actor_id else "",
            str(r.request_id),
        ]
        for r in queryset.order_by("timestamp")[:MAX_ROWS]
    ]


def _rows_report(job: ExportJob) -> list[list[str]]:
    snapshot = load_snapshot(job.requester, job.as_of)
    data = metrics_snapshot(snapshot, as_of=job.as_of, filters=dict(job.filter_snapshot))
    rows: list[list[str]] = []
    for key, value in data["metrics"].items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                rows.append(
                    [
                        f"{key}.{sub}",
                        "" if sub_value is None else str(sub_value),
                        data["definitions"].get(key, ""),
                    ]
                )
        else:
            rows.append([key, str(value), data["definitions"].get(key, "")])
    rows.append(
        ["population", str(data["population"]), "Received applications in scope at the cutoff"]
    )
    rows.append(
        [
            "reconciled",
            str(data["reconciled"]).lower(),
            "open + completed + rejected + withdrawn == received",
        ]
    )
    return rows


BUILDERS: dict[str, Callable[[ExportJob], list[list[str]]]] = {
    ExportKind.CASES.value: _rows_cases,
    ExportKind.CERTIFICATES.value: _rows_certificates,
    ExportKind.AUDIT.value: _rows_audit,
    ExportKind.REPORT.value: _rows_report,
}


def render_csv(job: ExportJob, rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    header = FIELD_SETS[str(job.kind)][job.field_set_key]
    writer.writerow(["# Agni Setu export", f"kind={job.kind}", f"field_set={job.field_set_key}"])
    writer.writerow(
        ["# as_of", job.as_of.isoformat(), f"definition_version={job.definition_version}"]
    )
    writer.writerow(["# purpose", csv_safe(job.purpose), f"rows={len(rows)}"])
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return buffer.getvalue().encode("utf-8")


@register(EXPORT_JOB_KIND)
def generate_export(job: LogicalJob) -> JobResult:
    export_id = UUID(str(job.aggregate_ref.get("export_id")))
    export = ExportJob.objects.select_related("requester").filter(pk=export_id).first()
    if export is None:
        return JobResult(AttemptOutcome.PERMANENT, error_code="RESOURCE_NOT_FOUND")
    if export.state == ExportState.COMPLETE:
        return JobResult(AttemptOutcome.SUCCESS, disposition="CANCELLED_AS_OBSOLETE")
    now = jobs.current_clock().now()
    if export.expires_at <= now:
        ExportJob.objects.filter(pk=export.pk).update(state=ExportState.EXPIRED)
        return JobResult(AttemptOutcome.PERMANENT, error_code="EXPORT_EXPIRED")
    ExportJob.objects.filter(pk=export.pk, state=ExportState.READY).update(
        state=ExportState.RUNNING
    )
    try:
        rows = BUILDERS[str(export.kind)](export)
        data = render_csv(export, rows)
    except Forbidden as exc:
        ExportJob.objects.filter(pk=export.pk).update(
            state=ExportState.FAILED, last_error_code="SCOPE_LOST"
        )
        return JobResult(
            AttemptOutcome.PERMANENT, error_code="FORBIDDEN", safe_message=str(exc)[:120]
        )
    digest = hashlib.sha256(data).hexdigest()
    store = get_object_store()
    staging = f"staging/exports/{export.pk}/{digest}"
    final_key = f"exports/{export.pk}/{digest}.csv"
    try:
        store.put_staging(staging, [data], max_bytes=MAX_ARTIFACT_BYTES)
        store.promote(staging, final_key, expected_size=len(data))
        store.delete(staging)
    except ObjectStoreUnavailable as exc:
        return JobResult(
            AttemptOutcome.RETRYABLE,
            error_code="DEPENDENCY_UNAVAILABLE",
            safe_message=str(exc)[:120],
        )
    except ObjectStoreError as exc:
        return JobResult(
            AttemptOutcome.RETRYABLE, error_code="OBJECT_STORE_ERROR", safe_message=str(exc)[:120]
        )

    def apply() -> None:
        with transaction.atomic():
            current = ExportJob.objects.select_for_update().get(pk=export.pk)
            if current.state in (ExportState.COMPLETE, ExportState.EXPIRED):
                return
            current.state = ExportState.COMPLETE
            current.row_count = len(rows)
            current.artifact_object_key = final_key
            current.artifact_sha256 = digest
            current.artifact_size = len(data)
            current.last_error_code = None
            current.version += 1
            current.save()

    return JobResult(AttemptOutcome.SUCCESS, apply=apply, response_digest=digest)


def parse_as_of(value: Any, now: datetime) -> datetime:
    parsed = parse_datetime(str(value)) if value else None
    return parsed if parsed is not None and parsed.tzinfo is not None and parsed <= now else now


ACCESS_SALT = "agni.export-access"


def access_ttl() -> int:
    return int(settings.AGNI_UPLOADS["ACCESS_TTL_SECONDS"])
