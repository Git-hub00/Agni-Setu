"""Controlled exports (FR-26; data model `export_job`). The population and the field set are
frozen when the export is requested; scope expansion afterwards never enlarges the file, scope
reduction refuses access. Artifacts expire and are served only through reauthorised tickets."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import VersionedModel


class ExportKind(models.TextChoices):
    CASES = "CASES"
    CERTIFICATES = "CERTIFICATES"
    AUDIT = "AUDIT"
    REPORT = "REPORT"


class ExportState(models.TextChoices):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ExportJob(VersionedModel):
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="exports"
    )
    kind = models.CharField(max_length=16, choices=ExportKind.choices)
    field_set_key = models.CharField(max_length=60)
    purpose = models.CharField(max_length=500)
    scope_snapshot = models.JSONField(default=dict)
    filter_snapshot = models.JSONField(default=dict)
    as_of = models.DateTimeField()
    state = models.CharField(max_length=10, choices=ExportState.choices, default=ExportState.READY)
    row_count = models.BigIntegerField(null=True, blank=True)
    artifact_object_key = models.TextField(null=True, blank=True)
    artifact_sha256 = models.CharField(max_length=64, null=True, blank=True)
    artifact_size = models.BigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField()
    definition_version = models.CharField(max_length=40)
    logical_action_id = models.UUIDField(unique=True)
    last_error_code = models.CharField(max_length=80, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in ExportKind]), name="chk_export_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ExportState]),
                name="chk_export_state",
            ),
        ]
        indexes = [models.Index(fields=["requester", "created_at"], name="idx_export_requester")]

    def __str__(self) -> str:
        return f"export {self.kind}/{self.field_set_key} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"export:{self.id}:v{self.version}"'
