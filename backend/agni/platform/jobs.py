"""Durable job claim, lease fencing and result recording (docs/08 s.3-4).

Pattern (per job):
  short transaction: claim due row FOR UPDATE SKIP LOCKED, bump lease token, RUNNING, attempt
  outside:           run the bounded handler (external I/O) with the stable logical action id
  short transaction: lock the row, require the same lease token and a live lease, record the
                     attempt outcome, apply the guarded business effect, release the lease

A worker that lost its lease cannot write a completion. Retry backoff and the attempt cap come
from settings; an unknown outcome never becomes success by retrying blindly.
"""

from __future__ import annotations

import random
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from .clock import Clock, get_clock
from .models import AttemptOutcome, JobAttempt, JobState, LogicalJob

# Demo backoff schedule (docs/08 s.4): 30 s, 2 min, 10 min, 30 min, 2 h with bounded jitter.
BACKOFF: Sequence[timedelta] = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=2),
)


@dataclass(frozen=True)
class JobResult:
    """What a handler learned. `apply` runs inside the completion transaction, after the fence
    check, and must re-validate its own business guards (state may have moved)."""

    outcome: str  # AttemptOutcome value
    error_code: str | None = None
    safe_message: str = ""
    provider_request_id: str | None = None
    response_digest: str | None = None
    disposition: str | None = None
    apply: Callable[[], None] | None = None


@dataclass
class Claim:
    job: LogicalJob
    attempt: JobAttempt


class LeaseLost(Exception):
    """The lease token no longer matches (another worker recovered the job)."""


Handler = Callable[[LogicalJob], JobResult]
_HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return decorator


def handlers() -> Mapping[str, Handler]:
    return dict(_HANDLERS)


def enqueue_job(
    *,
    kind: str,
    aggregate_ref: Mapping[str, Any],
    run_at: datetime,
    logical_action_id: UUID | None = None,
    max_attempts: int | None = None,
    owner_queue_id: UUID | None = None,
) -> LogicalJob:
    """Idempotent on `logical_action_id`: re-running the same command reuses the same job."""
    job, _ = LogicalJob.objects.get_or_create(
        logical_action_id=logical_action_id or uuid4(),
        defaults={
            "kind": kind,
            "aggregate_ref": dict(aggregate_ref),
            "state": JobState.PENDING,
            "next_attempt_at": run_at,
            "max_attempts": max_attempts or settings.AGNI_JOBS["MAX_ATTEMPTS"],
            "owner_queue_id": owner_queue_id,
        },
    )
    return job


def default_owner() -> str:
    return f"{socket.gethostname()}:{uuid4().hex[:8]}"


def claim_due_jobs(
    *, owner: str, now: datetime, limit: int = 10, kinds: Sequence[str] | None = None
) -> list[Claim]:
    lease = timedelta(seconds=settings.AGNI_JOBS["LEASE_SECONDS"])
    claims: list[Claim] = []
    with transaction.atomic():
        due = Q(state__in=[JobState.PENDING, JobState.RETRY_WAIT], next_attempt_at__lte=now)
        expired = Q(state=JobState.RUNNING, lease_until__lt=now)  # crashed worker recovery
        queryset = (
            LogicalJob.objects.select_for_update(skip_locked=True)
            .filter(due | expired)
            .order_by("next_attempt_at", "created_at")
        )
        if kinds:
            queryset = queryset.filter(kind__in=list(kinds))
        for job in queryset[:limit]:
            job.lease_token += 1
            job.state = JobState.RUNNING
            job.lease_owner = owner
            job.lease_until = now + lease
            job.attempt_count += 1
            job.save(
                update_fields=[
                    "lease_token",
                    "state",
                    "lease_owner",
                    "lease_until",
                    "attempt_count",
                    "updated_at",
                ]
            )
            attempt = JobAttempt.objects.create(
                job=job,
                attempt_number=job.attempt_count,
                lease_token=job.lease_token,
                started_at=now,
            )
            claims.append(Claim(job=job, attempt=attempt))
    return claims


def _backoff(attempt_count: int) -> timedelta:
    base = BACKOFF[min(attempt_count - 1, len(BACKOFF) - 1)]
    jitter = random.uniform(0, min(base.total_seconds() * 0.2, 30))  # noqa: S311 - not security
    return base + timedelta(seconds=jitter)


def finish(claim: Claim, result: JobResult, *, now: datetime) -> LogicalJob:
    """Record the attempt outcome under the fence and apply the business effect."""
    with transaction.atomic():
        job = LogicalJob.objects.select_for_update().get(pk=claim.job.pk)
        if job.lease_token != claim.attempt.lease_token or (
            job.lease_until is not None and job.lease_until < now
        ):
            raise LeaseLost(f"job {job.pk} lease token {claim.attempt.lease_token} is stale")
        attempt = JobAttempt.objects.get(pk=claim.attempt.pk)
        attempt.ended_at = now
        attempt.outcome = result.outcome
        attempt.provider_request_id = result.provider_request_id
        attempt.response_digest = result.response_digest
        attempt.safe_error = (
            {"code": result.error_code, "message": result.safe_message[:200]}
            if result.error_code
            else {}
        )
        attempt.save()

        job.last_error_code = result.error_code
        if result.outcome == AttemptOutcome.SUCCESS:
            if result.apply is not None:
                result.apply()
            job.state = JobState.COMPLETE
            job.disposition = result.disposition
            job.next_attempt_at = None
        elif result.outcome == AttemptOutcome.RETRYABLE:
            if job.attempt_count >= job.max_attempts:
                job.state = JobState.DEAD_LETTER
                job.next_attempt_at = None
            else:
                job.state = JobState.RETRY_WAIT
                job.next_attempt_at = now + _backoff(job.attempt_count)
        elif result.outcome == AttemptOutcome.UNKNOWN:
            job.state = JobState.RECONCILIATION_REQUIRED
            job.next_attempt_at = None
        else:
            job.state = JobState.DEAD_LETTER
            job.next_attempt_at = None
        job.lease_owner = None
        job.lease_until = None
        job.save()
        return job


@dataclass
class RunReport:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead: int = 0
    reconcile: int = 0
    lost: int = 0
    kinds: dict[str, int] = field(default_factory=dict)


def run_due_jobs(
    *, owner: str, limit: int = 10, kinds: Sequence[str] | None = None, clock: Clock | None = None
) -> RunReport:
    """One worker pass: claim, execute each handler outside the transaction, record results."""
    clock = clock or get_clock()
    report = RunReport()
    for claim in claim_due_jobs(owner=owner, now=clock.now(), limit=limit, kinds=kinds):
        report.claimed += 1
        report.kinds[claim.job.kind] = report.kinds.get(claim.job.kind, 0) + 1
        handler = _HANDLERS.get(claim.job.kind)
        if handler is None:
            result = JobResult(
                AttemptOutcome.PERMANENT,
                error_code="UNSUPPORTED_JOB_KIND",
                safe_message=claim.job.kind,
            )
        else:
            try:
                result = handler(claim.job)
            except Exception as exc:  # noqa: BLE001 - a handler bug must not kill the worker
                result = JobResult(
                    AttemptOutcome.RETRYABLE,
                    error_code="HANDLER_EXCEPTION",
                    safe_message=type(exc).__name__,
                )
        try:
            job = finish(claim, result, now=clock.now())
        except LeaseLost:
            report.lost += 1
            continue
        if job.state == JobState.COMPLETE:
            report.completed += 1
        elif job.state == JobState.RETRY_WAIT:
            report.retried += 1
        elif job.state == JobState.DEAD_LETTER:
            report.dead += 1
        elif job.state == JobState.RECONCILIATION_REQUIRED:
            report.reconcile += 1
    return report
