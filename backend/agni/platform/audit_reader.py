"""Scoped audit reading (FR-28; API-085/086; security s.5 'View audit'). Supervisors read the
rows of entities in their jurisdictions; leadership and operations administrators read wider
but redacted; applicants have only their public case timeline. Every listing is itself audited
as `audit.read` on the reader's own chain, and those rows are left out of ordinary listings so
reading never produces recursive noise."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils.dateparse import parse_datetime

from agni.identity.authz import AuthzSnapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind

from . import audit
from .errors import Forbidden, Violation
from .models import AuditEvent

SENSITIVE_KEYS = frozenset(
    {"reason", "public_reason", "detail", "approval_basis", "justification", "safe_message"}
)
READ_ACTION = "audit.read"
SCOPED_ENTITY_TYPES = ("application", "certificate", "inspection", "notice", "decision", "ticket")


def audit_scope(snapshot: AuthzSnapshot, now: datetime) -> tuple[QuerySet[AuditEvent], bool]:
    """(queryset, redact). Applicants are refused here; their public timeline is the case view."""
    if snapshot.kind == PrincipalKind.APPLICANT or not snapshot.active:
        raise Forbidden("Audit reading is a staff function with scope")
    if snapshot.has_role(RoleKey.ADMIN):
        return AuditEvent.objects.all(), True
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    if not jurisdictions:
        raise Forbidden("No audit scope is bound to your roles")
    from agni.cases.models import Application
    from agni.certificates.models import Certificate
    from agni.decisions.models import Decision
    from agni.inspections.models import Inspection
    from agni.notices.models import Notice
    from agni.support.models import SupportTicket

    applications = Application.objects.filter(
        owner_queue__jurisdiction_id__in=jurisdictions
    ).values("pk")
    scope = (
        Q(entity_type="application", entity_id__in=applications)
        | Q(
            entity_type="certificate",
            entity_id__in=Certificate.objects.filter(application__in=applications).values("pk"),
        )
        | Q(
            entity_type="decision",
            entity_id__in=Decision.objects.filter(application__in=applications).values("pk"),
        )
        | Q(
            entity_type="inspection",
            entity_id__in=Inspection.objects.filter(application__in=applications).values("pk"),
        )
        | Q(
            entity_type="notice",
            entity_id__in=Notice.objects.filter(application__in=applications).values("pk"),
        )
        | Q(
            entity_type="ticket",
            entity_id__in=SupportTicket.objects.filter(
                owner_queue__jurisdiction_id__in=jurisdictions
            ).values("pk"),
        )
        # A reader always sees the record of their own audit reads.
        | Q(entity_type="audit_query", entity_id=snapshot.principal_id)
    )
    redact = not snapshot.has_role(RoleKey.SUPERVISOR)  # leadership reads redacted
    return AuditEvent.objects.filter(scope), redact


def parse_audit_filters(params: Any) -> tuple[dict[str, Any], list[Violation]]:
    filters: dict[str, Any] = {}
    violations: list[Violation] = []
    for key in ("actor_id", "entity_id", "request_id"):
        raw = params.get(key)
        if raw:
            try:
                filters[key] = str(UUID(str(raw)))
            except ValueError:
                violations.append(Violation(f"/{key}", "invalid", "must be a UUID"))
    for key in ("entity_type", "action"):
        raw = params.get(key)
        if raw:
            filters[key] = str(raw)[:100]
    for key in ("from", "to"):
        raw = params.get(key)
        if raw:
            parsed = parse_datetime(str(raw))
            if parsed is None or parsed.tzinfo is None:
                violations.append(
                    Violation(f"/{key}", "format", "must be an ISO 8601 UTC timestamp")
                )
            else:
                filters[key] = parsed.isoformat()
    limit = params.get("limit")
    if limit:
        try:
            filters["limit"] = max(1, min(100, int(str(limit))))
        except ValueError:
            violations.append(Violation("/limit", "invalid", "1 to 100"))
    return filters, violations


def apply_filters(queryset: QuerySet[AuditEvent], filters: dict[str, Any]) -> QuerySet[AuditEvent]:
    if filters.get("actor_id"):
        queryset = queryset.filter(actor_id=filters["actor_id"])
    if filters.get("entity_id"):
        queryset = queryset.filter(entity_id=filters["entity_id"])
    if filters.get("request_id"):
        queryset = queryset.filter(request_id=filters["request_id"])
    if filters.get("entity_type"):
        queryset = queryset.filter(entity_type=filters["entity_type"])
    if filters.get("action"):
        queryset = queryset.filter(action__startswith=filters["action"])
    else:
        queryset = queryset.exclude(action=READ_ACTION)
    if filters.get("from"):
        queryset = queryset.filter(timestamp__gte=filters["from"])
    if filters.get("to"):
        queryset = queryset.filter(timestamp__lt=filters["to"])
    return queryset


def redact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if k in SENSITIVE_KEYS else v) for k, v in summary.items()}


def audit_body(row: AuditEvent, *, redact: bool) -> dict[str, Any]:
    summary = dict(row.safe_change_summary or {})
    return {
        "audit_event_id": str(row.pk),
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "action": row.action,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "authority_grant_id": str(row.authority_grant_id) if row.authority_grant_id else None,
        "request_id": str(row.request_id),
        "timestamp": row.timestamp.isoformat(),
        "summary": redact_summary(summary) if redact else summary,
        "redacted": redact,
        "hash": row.hash,
        "prior_hash": row.prior_hash,
        "checkpoint_batch_id": str(row.checkpoint_batch_id) if row.checkpoint_batch_id else None,
    }


def record_audit_read(
    *,
    principal_id: UUID,
    request_id: UUID,
    now: datetime,
    filters: dict[str, Any],
    count: int,
    detail_id: UUID | None = None,
) -> None:
    """The reader's own chain records what was asked and how much came back - never the rows."""
    audit.record_audit(
        entity_type="audit_query",
        entity_id=principal_id,
        action=READ_ACTION,
        actor_id=principal_id,
        request_id=request_id,
        at=now,
        summary={
            "filters": {k: v for k, v in filters.items() if k != "limit"},
            "count": count,
            "detail_id": str(detail_id) if detail_id else None,
        },
    )
