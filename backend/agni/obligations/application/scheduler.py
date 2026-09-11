"""Due-obligation scanner and threshold job (FR-19; docs/08 s.5).

`scan_due_obligations` runs every 30 s in the scheduler. For every ACTIVE obligation whose plan
has crossed a threshold without a recorded action it inserts the unique `ThresholdAction` row
and enqueues one durable job with a deterministic logical action id. Two schedulers racing on
the same obligation hit the unique constraint and the `get_or_create` on the job - exactly one
action, one job. The job re-checks everything at execution: a satisfied obligation suppresses
the obsolete reminder (COMPLETE / CANCELLED_AS_OBSOLETE) and never fabricates a send."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction

from agni.cases.models import CaseEvent, EventAudience
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind, RoleBinding
from agni.platform import jobs
from agni.platform.models import AttemptOutcome, LogicalJob
from agni.policies.models import PolicyVersion

from ..domain.thresholds import due_thresholds, threshold_plan
from ..models import (
    Escalation,
    EscalationState,
    Obligation,
    ObligationState,
    ThresholdAction,
    ThresholdActionType,
)
from .clock_service import calendar_for, pauses_for

THRESHOLD_JOB = "obligation.threshold"
_NAMESPACE = uuid.UUID("6f0a1e9c-1c3d-4b52-9d1f-2a7d2b0f5e10")


def threshold_job_id(obligation_id: Any, stage_instance_id: Any, key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"threshold:{obligation_id}:{stage_instance_id}:{key}")


def supervisors_for_queue(owner_queue: Any, at: datetime) -> list[Principal]:
    from django.db.models import Q

    bindings = RoleBinding.objects.filter(
        role_key=RoleKey.SUPERVISOR,
        jurisdiction_id=owner_queue.jurisdiction_id,
        revoked_at__isnull=True,
        effective_from__lte=at,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
    return list(
        Principal.objects.filter(
            kind=PrincipalKind.STAFF, is_active=True, pk__in=bindings.values("principal_id")
        ).order_by("display_name")
    )


def scan_due_obligations(*, now: datetime, limit: int = 200) -> dict[str, int]:
    """One scheduler pass. Returns counters for the operations log."""
    created = 0
    scanned = 0
    candidates = (
        Obligation.objects.filter(state=ObligationState.ACTIVE, due_at__isnull=False)
        .exclude(application_stage_instance__isnull=True)
        .select_related("calendar_artifact", "policy_version", "owner_queue")
        .order_by("due_at")[:limit]
    )
    for obligation in candidates:
        scanned += 1
        policy: PolicyVersion | None = obligation.policy_version
        payload = policy.payload if policy else {}
        plan = threshold_plan(
            policy_payload=payload,
            basis=obligation.time_basis,
            started_at=obligation.started_at,
            budget_minutes=obligation.budget_minutes,
            due_at=obligation.due_at,
            calendar=calendar_for(obligation),
            pauses=pauses_for(obligation),
        )
        stage_id = obligation.application_stage_instance_id
        if stage_id is None:
            continue
        for threshold in due_thresholds(plan, now):
            existing = ThresholdAction.objects.filter(
                obligation=obligation, stage_instance_id=stage_id, threshold_key=threshold.key
            ).exists()
            if existing:
                continue
            job_id = threshold_job_id(obligation.pk, stage_id, threshold.key)
            try:
                with transaction.atomic():
                    action = ThresholdAction.objects.create(
                        obligation=obligation,
                        stage_instance_id=stage_id,
                        threshold_key=threshold.key,
                        scheduled_for=threshold.scheduled_for,
                        action_type=threshold.action_type,
                        level=threshold.level,
                        logical_job_id=job_id,
                    )
                    jobs.enqueue_job(
                        kind=THRESHOLD_JOB,
                        aggregate_ref={
                            "threshold_action_id": str(action.pk),
                            "obligation_id": str(obligation.pk),
                            "threshold_key": threshold.key,
                        },
                        run_at=now,
                        logical_action_id=job_id,
                        owner_queue_id=obligation.owner_queue_id,
                    )
            except IntegrityError:
                continue  # another scheduler won the race: one action, one job
            created += 1
    return {"scanned": scanned, "created": created}


def _system_event(
    application: Any, event_type: str, payload: dict[str, Any], *, audience: str, now: datetime
) -> CaseEvent:
    from django.db.models import Max

    version = application.version
    current = CaseEvent.objects.filter(
        application=application, aggregate_version=version
    ).aggregate(m=Max("ordinal"))["m"]
    return CaseEvent.objects.create(
        application=application,
        aggregate_version=version,
        ordinal=0 if current is None else current + 1,
        event_type=event_type,
        actor=None,
        actor_kind="SYSTEM",
        occurred_at=now,
        payload=payload,
        audience=audience,
        request_id=uuid.uuid4(),
        command_receipt=None,
    )


@jobs.register(THRESHOLD_JOB)
def run_threshold(job: LogicalJob) -> jobs.JobResult:
    """Execute one threshold crossing. All checks are redone under the completion lock."""
    from agni.notifications.application.fanout import notify_threshold

    action_id = job.aggregate_ref.get("threshold_action_id")
    now = jobs.current_clock().now()

    def apply() -> None:
        # Lock the action row only (`of=self`): the obligation's application is a nullable
        # join and PostgreSQL refuses FOR UPDATE on the nullable side of an outer join.
        action = (
            ThresholdAction.objects.select_for_update(of=("self",))
            .select_related("obligation__owner_queue", "obligation__application")
            .get(pk=action_id)
        )
        obligation = action.obligation
        if action.executed_at is not None:
            return
        if (
            obligation.state != ObligationState.ACTIVE
            or action.superseded_at is not None
            or obligation.application_stage_instance_id != action.stage_instance_id
        ):
            action.executed_at = now
            action.disposition = "CANCELLED_AS_OBSOLETE"
            action.save(update_fields=["executed_at", "disposition", "updated_at"])
            return
        escalation: Escalation | None = None
        if action.action_type == ThresholdActionType.ESCALATION:
            escalation, _ = Escalation.objects.get_or_create(
                threshold_action=action,
                defaults={
                    "obligation": obligation,
                    "level": max(1, action.level),
                    "owner_queue": obligation.owner_queue,
                    "state": EscalationState.OPEN,
                    "reason": f"Threshold {action.threshold_key} reached",
                },
            )
        application = obligation.application
        event = None
        if application is not None:
            event = _system_event(
                application,
                "obligation.threshold_reached.v1",
                {
                    "obligation_id": str(obligation.pk),
                    "kind": obligation.kind,
                    "threshold_key": action.threshold_key,
                    "action_type": action.action_type,
                    "escalation_id": str(escalation.pk) if escalation else None,
                    "due_at": obligation.due_at.isoformat() if obligation.due_at else None,
                },
                audience=EventAudience.INTERNAL,
                now=now,
            )
        notify_threshold(action, obligation, escalation, event, now=now)
        action.executed_at = now
        action.disposition = "EXECUTED"
        action.save(update_fields=["executed_at", "disposition", "updated_at"])

    return jobs.JobResult(AttemptOutcome.SUCCESS, apply=apply)
