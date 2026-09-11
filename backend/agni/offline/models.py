"""Offline synchronisation persistence (FR-12/FR-13; data model `sync_operation`, docs/09).

A `SyncOperation` is the server-side record of one client operation identity: accepted results
are immutable receipts; a conflict keeps the safe server snapshot and can spawn a reviewed
`ReportConflict` proposal, never a mutation of the original payload. The client's device time,
base versions and manifests are corroborating information, never authority."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


class OperationType(models.TextChoices):
    SUBMIT_INSPECTION_REPORT = "SUBMIT_INSPECTION_REPORT"
    RECORD_FAILED_VISIT = "RECORD_FAILED_VISIT"


class SyncState(models.TextChoices):
    ACCEPTED = "ACCEPTED"
    CONFLICT = "CONFLICT"


class SyncOperation(AppendOnlyModel):
    """One (principal, operation_id) identity. Unique per principal so a lost response is
    answered by replaying the stored result, and a changed payload behind the same id is
    refused (docs/09 s.5 step 7 and s.7 'same operation ID, different hash')."""

    operation_id = models.UUIDField()
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sync_operations"
    )
    inspection = models.ForeignKey(
        "inspections.Inspection", on_delete=models.PROTECT, related_name="sync_operations"
    )
    operation_type = models.CharField(max_length=32, choices=OperationType.choices)
    request_sha256 = models.CharField(max_length=64)
    base_version = models.BigIntegerField()
    assignment_version = models.BigIntegerField()
    schema_version = models.CharField(max_length=20)
    state = models.CharField(max_length=10, choices=SyncState.choices)
    report = models.ForeignKey(
        "inspections.InspectionReport",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["principal", "operation_id"], name="uniq_sync_operation_principal"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in SyncState]),
                name="chk_sync_operation_state",
            ),
        ]
        indexes = [models.Index(fields=["inspection", "created_at"], name="idx_sync_inspection")]

    def __str__(self) -> str:
        return f"{self.operation_type} {self.operation_id} [{self.state}]"


class ConflictState(models.TextChoices):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ConflictOutcome(models.TextChoices):
    PROPOSE_NEW_REPORT = "PROPOSE_NEW_REPORT"
    REINSPECTION_REQUIRED = "REINSPECTION_REQUIRED"
    DECLINE = "DECLINE"


class ReportConflict(VersionedModel):
    """Safe conflict proposal (API-051) reviewed by a supervisor (API-052). The local manifest
    is stored as evidence of what the device holds; it never becomes an active report."""

    inspection = models.ForeignKey(
        "inspections.Inspection", on_delete=models.PROTECT, related_name="conflicts"
    )
    operation_id = models.UUIDField()
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    application_version_seen = models.BigIntegerField()
    local_manifest = models.JSONField(default=dict)
    local_manifest_sha256 = models.CharField(max_length=64)
    safe_local_summary = models.TextField()
    reason = models.TextField()
    server_snapshot = models.JSONField(default=dict)
    state = models.CharField(
        max_length=10, choices=ConflictState.choices, default=ConflictState.OPEN
    )
    outcome = models.CharField(
        max_length=24, choices=ConflictOutcome.choices, null=True, blank=True
    )
    resolution_reason = models.TextField(blank=True, default="")
    selected_evidence_ids = models.JSONField(default=list)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposer", "operation_id"], name="uniq_conflict_proposal"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ConflictState]),
                name="chk_conflict_state",
            ),
        ]

    def __str__(self) -> str:
        return f"conflict {self.operation_id} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"conflict:{self.id}:v{self.version}"'
