"""Operations skeleton (UI-20; API-103/104): job list with a health summary and sanitised job
detail for the operations administrator. Recovery commands (API-105/106) arrive with B14; no
endpoint here can change a case, mark evidence clean or replace a decision (docs/08 s.8)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db.models import Count
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal

from ..clock import get_clock
from ..dispatch import outbox_lag
from ..errors import AuthenticationRequired, MalformedRequest, ResourceNotFound
from ..models import JobAttempt, JobState, LogicalJob
from .views import ApiView, ok


def _operator(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    require_role(load_snapshot(user, get_clock().now()), RoleKey.ADMIN)
    return user


def job_body(job: LogicalJob) -> dict[str, Any]:
    return {
        "job_id": str(job.pk),
        "logical_action_id": str(job.logical_action_id),
        "kind": job.kind,
        "state": job.state,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "next_attempt_at": job.next_attempt_at.isoformat() if job.next_attempt_at else None,
        "lease_owner": job.lease_owner,
        "lease_until": job.lease_until.isoformat() if job.lease_until else None,
        "last_error_code": job.last_error_code,
        "disposition": job.disposition,
        # Aggregate references are ids only; never a payload or personal data.
        "aggregate_ref": {k: str(v) for k, v in job.aggregate_ref.items()},
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "next_permitted_action": (
            "RETRY"
            if job.state == JobState.DEAD_LETTER
            else ("RECONCILE" if job.state == JobState.RECONCILIATION_REQUIRED else None)
        ),
    }


class JobListView(ApiView):
    """API-103 with the operations summary UI-20 needs (outbox lag, oldest due job, dead letters,
    unknown outcomes, last worker activity)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _operator(request)
        now = get_clock().now()
        queryset = LogicalJob.objects.all()
        states = [s for s in request.query_params.getlist("state") if s]
        if states:
            if any(s not in JobState.values for s in states):
                raise MalformedRequest("unknown state filter")
            queryset = queryset.filter(state__in=states)
        kind = request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        rows = list(queryset.order_by("-updated_at")[:100])
        due = LogicalJob.objects.filter(
            state__in=[JobState.PENDING, JobState.RETRY_WAIT], next_attempt_at__lte=now
        ).order_by("next_attempt_at")
        oldest = due.first()
        last_attempt = (
            JobAttempt.objects.filter(ended_at__isnull=False).order_by("-ended_at").first()
        )
        heartbeat_age = (
            int((now - last_attempt.ended_at).total_seconds())
            if last_attempt and last_attempt.ended_at
            else None
        )
        summary = {
            "as_of": now.isoformat(),
            "outbox": outbox_lag(now),
            "due_jobs": due.count(),
            "oldest_due_seconds": int((now - oldest.next_attempt_at).total_seconds())
            if oldest and oldest.next_attempt_at
            else 0,
            "running": LogicalJob.objects.filter(state=JobState.RUNNING).count(),
            "expired_leases": LogicalJob.objects.filter(
                state=JobState.RUNNING, lease_until__lt=now
            ).count(),
            "retry_wait": LogicalJob.objects.filter(state=JobState.RETRY_WAIT).count(),
            "dead_letter": LogicalJob.objects.filter(state=JobState.DEAD_LETTER).count(),
            "reconciliation_required": LogicalJob.objects.filter(
                state=JobState.RECONCILIATION_REQUIRED
            ).count(),
            "worker_last_activity_seconds": heartbeat_age,
            "worker_heartbeat_ok": heartbeat_age is not None
            and heartbeat_age <= int(timedelta(minutes=10).total_seconds()),
            "by_kind": {
                row["kind"]: row["n"]
                for row in LogicalJob.objects.values("kind").annotate(n=Count("id"))
            },
        }
        return ok({"summary": summary, "items": [job_body(j) for j in rows]}, request)


class JobDetailView(ApiView):
    """API-104: attempts with safe errors only."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, job_id: UUID) -> Response:
        _operator(request)
        job = LogicalJob.objects.filter(pk=job_id).first()
        if job is None:
            raise ResourceNotFound("Job not found")
        return ok(
            {
                **job_body(job),
                "attempts": [
                    {
                        "attempt_number": a.attempt_number,
                        "lease_token": a.lease_token,
                        "started_at": a.started_at.isoformat(),
                        "ended_at": a.ended_at.isoformat() if a.ended_at else None,
                        "outcome": a.outcome,
                        "safe_error": a.safe_error,
                        "provider_request_id": a.provider_request_id,
                    }
                    for a in job.attempts.order_by("attempt_number")
                ],
            },
            request,
        )
