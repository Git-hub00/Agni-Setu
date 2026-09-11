"""Obligation and escalation endpoints API-074..077 (UI-15). One cutoff (`as_of`) drives every
count and urgency label so the monitoring screen never disagrees with itself."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import AuthzSnapshot, load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    Forbidden,
    MalformedRequest,
    ResourceNotFound,
)

from ..application.clock_service import clock_breakdown
from ..application.commands import AcknowledgeEscalation, CreateEscalation, escalation_body
from ..models import Escalation, EscalationState, Obligation, ObligationState

DUE_SOON = timedelta(hours=24)


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _scope(request: Request) -> tuple[Principal, datetime, AuthzSnapshot, QuerySet[Obligation]]:
    principal = _principal(request)
    now = get_clock().now()
    snapshot = load_snapshot(principal, now)
    if snapshot.kind != PrincipalKind.STAFF:
        raise Forbidden("Obligations are a staff workspace")
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    queryset = Obligation.objects.filter(owner_queue__jurisdiction_id__in=jurisdictions)
    return principal, now, snapshot, queryset


def urgency(o: Obligation, as_of: datetime) -> str:
    if o.state == ObligationState.PAUSED or o.due_at is None:
        return "PAUSED" if o.state == ObligationState.PAUSED else "NO_ESTIMATE"
    if o.state != ObligationState.ACTIVE:
        return "CLOSED"
    if o.due_at <= as_of:
        return "OVERDUE"
    if o.due_at <= as_of + DUE_SOON:
        return "DUE_SOON"
    return "ON_TRACK"


def obligation_row(
    o: Obligation, as_of: datetime, *, escalations: list[Escalation]
) -> dict[str, Any]:
    application = o.application
    return {
        "obligation_id": str(o.pk),
        "application_id": str(o.application_id) if o.application_id else None,
        "public_reference": application.public_reference if application else None,
        "application_status": application.status if application else None,
        "kind": o.kind,
        "state": o.state,
        "urgency": urgency(o, as_of),
        "time_basis": o.time_basis,
        "budget_minutes": o.budget_minutes,
        "started_at": o.started_at.isoformat(),
        "due_at": o.due_at.isoformat() if o.due_at else None,
        "owner_queue": o.owner_queue.queue_key,
        "responsible_principal": str(o.responsible_principal_id)
        if o.responsible_principal_id
        else None,
        "generation": o.generation,
        "open_escalations": [
            escalation_body(e) for e in escalations if e.state != EscalationState.RESOLVED
        ],
        "etag": o.etag,
        "version": o.version,
    }


class ObligationListView(ApiView):
    """API-074."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _, now, _, queryset = _scope(request)
        as_of_raw = request.query_params.get("as_of")
        as_of = now
        if as_of_raw:
            parsed = parse_datetime(as_of_raw)
            if parsed is None or parsed.tzinfo is None:
                raise MalformedRequest("as_of must be an ISO 8601 UTC timestamp")
            as_of = parsed
        states = [s for s in request.query_params.getlist("state") if s]
        if states:
            if any(s not in ObligationState.values for s in states):
                raise MalformedRequest("unknown state filter")
            queryset = queryset.filter(state__in=states)
        else:
            queryset = queryset.filter(state__in=[ObligationState.ACTIVE, ObligationState.PAUSED])
        owner = request.query_params.get("owner_queue_id")
        if owner:
            try:
                queryset = queryset.filter(owner_queue_id=UUID(owner))
            except ValueError as exc:
                raise MalformedRequest("owner_queue_id must be a UUID") from exc
        wanted = request.query_params.get("urgency")
        if wanted and wanted not in ("DUE_SOON", "OVERDUE", "ON_TRACK", "PAUSED", "NO_ESTIMATE"):
            raise MalformedRequest("unknown urgency filter")
        if wanted == "OVERDUE":
            queryset = queryset.filter(state=ObligationState.ACTIVE, due_at__lte=as_of)
        elif wanted == "DUE_SOON":
            queryset = queryset.filter(
                state=ObligationState.ACTIVE, due_at__gt=as_of, due_at__lte=as_of + DUE_SOON
            )
        elif wanted == "ON_TRACK":
            queryset = queryset.filter(state=ObligationState.ACTIVE, due_at__gt=as_of + DUE_SOON)
        elif wanted == "PAUSED":
            queryset = queryset.filter(Q(state=ObligationState.PAUSED) | Q(due_at__isnull=True))
        rows = list(
            queryset.select_related("application", "owner_queue").order_by("due_at", "started_at")[
                :200
            ]
        )
        escalations: dict[UUID, list[Escalation]] = {}
        for e in Escalation.objects.filter(obligation__in=[r.pk for r in rows]).select_related(
            "owner_queue"
        ):
            escalations.setdefault(e.obligation_id, []).append(e)
        active = queryset.filter(state=ObligationState.ACTIVE)
        return ok(
            {
                "as_of": as_of.isoformat(),
                "counts": {
                    "overdue": active.filter(due_at__lte=as_of).count(),
                    "due_soon": active.filter(
                        due_at__gt=as_of, due_at__lte=as_of + DUE_SOON
                    ).count(),
                    "paused": queryset.filter(
                        Q(state=ObligationState.PAUSED) | Q(due_at__isnull=True)
                    ).count(),
                    "open_escalations": Escalation.objects.filter(
                        obligation__in=queryset.values("pk"), state=EscalationState.OPEN
                    ).count(),
                },
                "items": [
                    obligation_row(o, as_of, escalations=escalations.get(o.pk, [])) for o in rows
                ],
            },
            request,
        )


class ObligationDetailView(ApiView):
    """API-075: clock breakdown, pauses, threshold history and escalations."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, obligation_id: UUID) -> Response:
        _, now, _, queryset = _scope(request)
        obligation = (
            queryset.select_related(
                "application", "owner_queue", "calendar_artifact", "policy_version"
            )
            .filter(pk=obligation_id)
            .first()
        )
        if obligation is None:
            raise ResourceNotFound("Obligation not found")
        escalations = list(
            Escalation.objects.filter(obligation=obligation)
            .select_related("owner_queue")
            .order_by("created_at")
        )
        body = {
            **obligation_row(obligation, now, escalations=escalations),
            "clock": clock_breakdown(obligation, cutoff=now),
            "policy_version_id": str(obligation.policy_version_id),
            "thresholds": [
                {
                    "threshold_action_id": str(t.pk),
                    "threshold_key": t.threshold_key,
                    "action_type": t.action_type,
                    "level": t.level,
                    "scheduled_for": t.scheduled_for.isoformat(),
                    "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                    "disposition": t.disposition or None,
                    "superseded_at": t.superseded_at.isoformat() if t.superseded_at else None,
                }
                for t in obligation.threshold_actions.order_by("scheduled_for")
            ],
            "escalations": [escalation_body(e) for e in escalations],
            "as_of": now.isoformat(),
        }
        response = ok(body, request)
        response["ETag"] = obligation.etag
        return response


class EscalationCreateView(ApiView):
    """API-076."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, obligation_id: UUID) -> Response:
        return self.run_command(
            request,
            CreateEscalation(),
            command_name="create-escalation",
            target_type="obligation",
            target_id=obligation_id,
            etag_type="obligation",
        )


class EscalationAcknowledgeView(ApiView):
    """API-077."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, escalation_id: UUID) -> Response:
        return self.run_command(
            request,
            AcknowledgeEscalation(),
            command_name="acknowledge-escalation",
            target_type="escalation",
            target_id=escalation_id,
            etag_type="escalation",
        )
