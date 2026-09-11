"""Platform persistence: base model conventions (data model s.1) and the command kernel's
tables - command receipts, transactional outbox and audit events (data model s.3 platform/audit).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from .errors import AppendOnlyViolation


class VersionedModel(models.Model):
    """Mutable business row: UUID id, timestamps and an optimistic `version` that only the
    command kernel increments (data model s.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.BigIntegerField(default=1)

    class Meta:
        abstract = True

    @property
    def etag(self) -> str:
        return f'"{type(self).__name__.lower()}:{self.id}:v{self.version}"'


class AppendOnlyModel(models.Model):
    """Immutable record: inserts only. Ordinary code cannot update or delete it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyViolation(f"{type(self).__name__} is append-only")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise AppendOnlyViolation(f"{type(self).__name__} is append-only")


class CommandReceipt(AppendOnlyModel):
    """Idempotency receipt: same principal/target/command/key returns the original authorized
    result; a different request hash is IDEMPOTENCY_CONFLICT (docs/06 s.4)."""

    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    target_type = models.CharField(max_length=60)
    target_id = models.UUIDField()
    command_name = models.CharField(max_length=80)
    key_hash = models.CharField(max_length=64)
    request_sha256 = models.CharField(max_length=64)
    result_status = models.PositiveSmallIntegerField()
    result_body = models.JSONField()
    resulting_version = models.BigIntegerField(null=True, blank=True)
    accepted_at = models.DateTimeField()
    retain_until = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["principal", "target_type", "target_id", "command_name", "key_hash"],
                name="uniq_command_receipt_scope_key",
            )
        ]
        indexes = [models.Index(fields=["retain_until"], name="idx_receipt_retain_until")]

    def __str__(self) -> str:
        return f"{self.command_name}@{self.target_type}:{self.target_id}"


class OutboxState(models.TextChoices):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    COMPLETE = "COMPLETE"


class OutboxMessage(models.Model):
    """Durable intent written in the same transaction as the business change (ADR-06). The
    dispatcher (B10) publishes it; the row survives broker acknowledgement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    logical_action_id = models.UUIDField(unique=True)
    event_type = models.CharField(max_length=100)
    aggregate_type = models.CharField(max_length=60)
    aggregate_id = models.UUIDField()
    payload_version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    available_at = models.DateTimeField()
    state = models.CharField(
        max_length=12, choices=OutboxState.choices, default=OutboxState.PENDING
    )
    last_dispatched_at = models.DateTimeField(null=True, blank=True)
    dispatch_attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        indexes = [models.Index(fields=["state", "available_at"], name="idx_outbox_due")]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.logical_action_id}"


class JobState(models.TextChoices):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETE = "COMPLETE"
    DEAD_LETTER = "DEAD_LETTER"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class LogicalJob(models.Model):
    """Durable unit of asynchronous work (data model `logical_job`, docs/08 s.3-4). The database
    row is the source of truth; a broker message is only a wake-up. Workers claim rows with
    `FOR UPDATE SKIP LOCKED`, hold a lease and may only record a result with the current
    fencing token."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    logical_action_id = models.UUIDField(unique=True)
    kind = models.CharField(max_length=80)
    aggregate_ref = models.JSONField(default=dict)
    state = models.CharField(max_length=24, choices=JobState.choices, default=JobState.PENDING)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=6)
    lease_owner = models.CharField(max_length=120, null=True, blank=True)
    lease_token = models.BigIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, null=True, blank=True)
    disposition = models.CharField(max_length=40, null=True, blank=True)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    provider_id = models.CharField(max_length=80, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in JobState]), name="chk_job_state"
            )
        ]
        indexes = [
            models.Index(fields=["state", "next_attempt_at"], name="idx_job_due"),
            models.Index(fields=["kind", "state"], name="idx_job_kind_state"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.logical_action_id} [{self.state}]"


class AttemptOutcome(models.TextChoices):
    SUCCESS = "SUCCESS"
    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"
    UNKNOWN = "UNKNOWN"


class JobAttempt(models.Model):
    """One execution attempt (data model `job_attempt`). Provider secrets and personal payloads
    are excluded; `safe_error` holds a catalogue code and a short safe message only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(LogicalJob, on_delete=models.PROTECT, related_name="attempts")
    attempt_number = models.PositiveIntegerField()
    lease_token = models.BigIntegerField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    provider_request_id = models.TextField(null=True, blank=True)
    outcome = models.CharField(max_length=12, choices=AttemptOutcome.choices, null=True, blank=True)
    safe_error = models.JSONField(default=dict)
    response_digest = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "attempt_number"], name="uniq_job_attempt")
        ]

    def __str__(self) -> str:
        return f"{self.job_id}#{self.attempt_number}"


class AuditEvent(AppendOnlyModel):
    """Append-only audit with a per-entity hash chain (data model `audit_event`). The chain
    detects alteration; it is not a claim of mathematical immutability."""

    entity_type = models.CharField(max_length=60)
    entity_id = models.UUIDField()
    action = models.CharField(max_length=100)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    authority_grant_id = models.UUIDField(null=True, blank=True)
    request_id = models.UUIDField()
    timestamp = models.DateTimeField()
    safe_change_summary = models.JSONField()
    prior_hash = models.CharField(max_length=64, null=True, blank=True)
    hash = models.CharField(max_length=64)
    checkpoint_batch_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id", "timestamp"], name="idx_audit_entity_time"
            ),
            models.Index(fields=["request_id"], name="idx_audit_request"),
        ]

    def __str__(self) -> str:
        return f"{self.action}@{self.entity_type}:{self.entity_id}"
