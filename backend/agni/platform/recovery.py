"""Operator job recovery (API-105/106; docs/08 s.8; UI-20). Retry resumes the SAME logical
action and refuses when the last outcome was ambiguous; reconcile runs the kind-specific
lookup-before-retry procedure. Neither can change a case, mark evidence clean or replace a
decision - they only re-queue durable work with a reason on the audit trail."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal

from .commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from .errors import InvalidTransition, ResourceNotFound, ValidationFailed, Violation
from .models import AttemptOutcome, JobState, LogicalJob

# Kinds whose handlers look the provider up (or are idempotent) before doing anything again.
RECONCILABLE_KINDS = {
    "certificate.issue": "issuance lookup by the stable request id before any resubmission",
    "document.scan": "re-scan of the exact immutable object version",
    "notification.fanout": "idempotent per (recipient, logical key)",
    "obligation.threshold": "idempotent per (obligation, stage, threshold)",
    "export.generate": "regenerates from the frozen population",
}


def _reason(payload: Any) -> str:
    reason = str(payload.get("reason") or "").strip()
    if not (10 <= len(reason) <= 4000):
        raise ValidationFailed(violations=[Violation("/reason", "length", "10 to 4000 characters")])
    return reason


def _job(target_id: UUID) -> LogicalJob:
    job = LogicalJob.objects.select_for_update().filter(pk=target_id).first()
    if job is None:
        raise ResourceNotFound("Job not found")
    return job


def _requeue(job: LogicalJob, now: Any) -> None:
    job.state = JobState.PENDING
    job.next_attempt_at = now
    job.lease_owner = None
    job.lease_until = None
    job.max_attempts = max(job.max_attempts, job.attempt_count + 1)
    job.save(
        update_fields=[
            "state",
            "next_attempt_at",
            "lease_owner",
            "lease_until",
            "max_attempts",
            "updated_at",
        ]
    )


def _body(job: LogicalJob) -> dict[str, Any]:
    from .api.operations import job_body

    return job_body(job)


class RetryJob(CommandHandler[Principal]):
    """API-105: same logical action; refuses a blind retry after an ambiguous (UNKNOWN) attempt."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN)

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        return None

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        reason = _reason(uow.envelope.payload)
        job = _job(uow.envelope.target_id)
        if job.state not in (JobState.DEAD_LETTER, JobState.RETRY_WAIT):
            raise InvalidTransition(f"A {job.state} job is not retried; use reconcile or wait")
        last = job.attempts.order_by("-attempt_number").first()
        if last is not None and last.outcome == AttemptOutcome.UNKNOWN:
            raise InvalidTransition(
                "The last outcome is ambiguous; reconcile before any retry",
                extensions={"job_kind": job.kind},
            )
        _requeue(job, uow.now)
        return CommandOutcome(
            status=202,
            body=_body(job),
            aggregate=None,
            audits=[
                AuditEntry(
                    "logical_job",
                    job.pk,
                    "job.retried",
                    {
                        "kind": job.kind,
                        "attempts_before": job.attempt_count,
                        "reason": reason[:200],
                    },
                )
            ],
        )


class ReconcileJob(CommandHandler[Principal]):
    """API-106: verify/lookup the provider outcome before completing or retrying."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN)

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        return None

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        reason = _reason(uow.envelope.payload)
        job = _job(uow.envelope.target_id)
        if job.state != JobState.RECONCILIATION_REQUIRED:
            raise InvalidTransition(f"A {job.state} job needs no reconciliation")
        procedure = RECONCILABLE_KINDS.get(job.kind)
        if procedure is None:
            raise InvalidTransition(
                "No approved reconciliation procedure exists for this job kind; resolve with "
                "manual evidence",
                extensions={"job_kind": job.kind},
            )
        if job.kind == "certificate.issue":
            from agni.certificates.application.issuance import reconcile_issuance

            request_id = UUID(str(job.aggregate_ref.get("issuance_request_id")))
            reconcile_issuance(request_id, now=uow.now, note=reason)
            job.refresh_from_db()
        else:
            _requeue(job, uow.now)
        return CommandOutcome(
            status=202,
            body={**_body(job), "procedure": procedure},
            aggregate=None,
            audits=[
                AuditEntry(
                    "logical_job",
                    job.pk,
                    "job.reconciled",
                    {"kind": job.kind, "procedure": procedure, "reason": reason[:200]},
                )
            ],
        )
