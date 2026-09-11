"""Single-cutoff reconciled metrics (API-081; FR-25). Everything is computed from the scoped
authoritative records at one `as_of`: the population is the reader's visible applications with a
receipt at or before the cutoff; status comes from the stage instance in force at the cutoff, so
totals partition the population and reconcile with the list the same reader sees."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils.dateparse import parse_datetime

from agni.cases.models import Application, StageInstance
from agni.cases.selectors import visible_applications
from agni.certificates.models import Certificate
from agni.identity.authz import AuthzSnapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.obligations.models import Obligation, ObligationState
from agni.platform.errors import Violation

from ..domain.metrics import (
    DEFINITION_VERSION,
    DEFINITIONS,
    MIN_SAMPLE,
    TERMINAL,
    percentile,
    state_at,
)

FILTER_KEYS = ("service_id", "jurisdiction_id", "category_key", "submitted_from", "submitted_to")


def parse_filters(
    params: Any, *, now: datetime
) -> tuple[dict[str, Any], datetime, list[Violation]]:
    """ReportQuery (docs/24): permitted ids, approved category, UTC half-open window, optional
    cutoff never later than now."""
    violations: list[Violation] = []
    filters: dict[str, Any] = {}
    for key in ("service_id", "jurisdiction_id"):
        raw = params.get(key)
        if raw:
            try:
                filters[key] = str(UUID(str(raw)))
            except ValueError:
                violations.append(Violation(f"/{key}", "invalid", "must be a UUID"))
    category = params.get("category_key")
    if category:
        filters["category_key"] = str(category)[:60]
    for key in ("submitted_from", "submitted_to"):
        raw = params.get(key)
        if raw:
            parsed = parse_datetime(str(raw))
            if parsed is None or parsed.tzinfo is None:
                violations.append(
                    Violation(f"/{key}", "format", "must be an ISO 8601 UTC timestamp")
                )
            else:
                filters[key] = parsed.isoformat()
    as_of = now
    raw_as_of = params.get("as_of")
    if raw_as_of:
        parsed = parse_datetime(str(raw_as_of))
        if parsed is None or parsed.tzinfo is None:
            violations.append(Violation("/as_of", "format", "must be an ISO 8601 UTC timestamp"))
        elif parsed > now:
            violations.append(Violation("/as_of", "future", "the cutoff cannot be in the future"))
        else:
            as_of = parsed
    return filters, as_of, violations


def population(
    snapshot: AuthzSnapshot, filters: dict[str, Any], as_of: datetime
) -> QuerySet[Application]:
    """Received applications visible to the reader at the cutoff, narrowed by the filters."""
    queryset = visible_applications(snapshot, as_of).filter(
        submitted_at__isnull=False, submitted_at__lte=as_of
    )
    if filters.get("service_id"):
        queryset = queryset.filter(service_id=filters["service_id"])
    if filters.get("jurisdiction_id"):
        queryset = queryset.filter(owner_queue__jurisdiction_id=filters["jurisdiction_id"])
    if filters.get("category_key"):
        queryset = queryset.filter(premises__category_key=filters["category_key"])
    if filters.get("submitted_from"):
        queryset = queryset.filter(submitted_at__gte=filters["submitted_from"])
    if filters.get("submitted_to"):
        queryset = queryset.filter(submitted_at__lt=filters["submitted_to"])
    return queryset


def scope_descriptor(snapshot: AuthzSnapshot) -> dict[str, Any]:
    if snapshot.kind == PrincipalKind.APPLICANT:
        return {"kind": "OWN_CASES"}
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    return {
        "kind": "GLOBAL" if snapshot.has_role(RoleKey.ADMIN) else "JURISDICTIONS",
        "jurisdiction_ids": sorted(str(j) for j in jurisdictions),
    }


def states_at_cutoff(ids: list[UUID], as_of: datetime) -> dict[UUID, str]:
    rows = StageInstance.objects.filter(application_id__in=ids, entered_at__lte=as_of).filter(
        Q(exited_at__isnull=True) | Q(exited_at__gt=as_of)
    )
    grouped: dict[UUID, list[tuple[str, datetime, datetime | None]]] = {}
    for application_id, state, entered_at, exited_at in rows.values_list(
        "application_id", "state", "entered_at", "exited_at"
    ):
        grouped.setdefault(application_id, []).append((state, entered_at, exited_at))
    out: dict[UUID, str] = {}
    for application_id, stages in grouped.items():
        found = state_at(stages, as_of)
        if found is not None:
            out[application_id] = found
    return out


def metrics_snapshot(
    snapshot: AuthzSnapshot, *, as_of: datetime, filters: dict[str, Any]
) -> dict[str, Any]:
    apps = population(snapshot, filters, as_of)
    submitted = dict(apps.values_list("pk", "submitted_at"))
    ids = list(submitted)
    states = states_at_cutoff(ids, as_of)
    by_status: Counter[str] = Counter(states.get(pk, "UNKNOWN") for pk in ids)
    received = len(ids)
    completed = by_status.get("COMPLETED", 0)
    rejected = by_status.get("REJECTED", 0)
    withdrawn = by_status.get("WITHDRAWN", 0)
    open_count = sum(n for state, n in by_status.items() if state not in TERMINAL)
    published = Certificate.objects.filter(application_id__in=ids, issued_at__lte=as_of).count()
    overdue = Obligation.objects.filter(
        application_id__in=ids,
        state__in=[ObligationState.ACTIVE, ObligationState.PAUSED],
        due_at__lt=as_of,
    ).count()
    terminal_entries = StageInstance.objects.filter(
        application_id__in=[
            pk for pk, state in states.items() if state in ("COMPLETED", "REJECTED")
        ],
        state__in=["COMPLETED", "REJECTED"],
        entered_at__lte=as_of,
    ).values_list("application_id", "entered_at")
    hours: list[float] = []
    for application_id, entered_at in terminal_entries:
        started = submitted.get(application_id)
        if started is not None:
            hours.append(max(0.0, (entered_at - started).total_seconds() / 3600))
    drafts_excluded = visible_applications(snapshot, as_of).filter(status="DRAFT").count()
    return {
        "as_of": as_of.isoformat(),
        "definition_version": DEFINITION_VERSION,
        "scope": scope_descriptor(snapshot),
        "filters": filters,
        "population": received,
        "metrics": {
            "received": received,
            "open": open_count,
            "completed": completed,
            "rejected": rejected,
            "withdrawn": withdrawn,
            "published_certificates": published,
            "overdue_obligations": overdue,
            "resolution_hours": {
                "sample_size": len(hours),
                "median": percentile(hours, 50),
                "p90": percentile(hours, 90),
                "insufficient_sample": len(hours) < MIN_SAMPLE,
            },
        },
        "by_status": dict(sorted(by_status.items())),
        "reconciled": open_count + completed + rejected + withdrawn == received,
        "exclusions": {"drafts": drafts_excluded},
        "definitions": DEFINITIONS,
    }
