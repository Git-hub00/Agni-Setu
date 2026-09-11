"""Duty queues and routing entries (data model s.3 `duty_queue`, `routing_entry`): every
submitted case has an accountable owner queue; routing resolves to exactly one target or an
owned exception."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from agni.platform.models import VersionedModel


class DutyQueue(VersionedModel):
    jurisdiction = models.ForeignKey(
        "policies.Jurisdiction", on_delete=models.PROTECT, related_name="duty_queues"
    )
    service = models.ForeignKey(
        "policies.Service",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="duty_queues",
    )
    queue_key = models.CharField(max_length=80)
    display_name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)
    primary_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    deputy_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "service", "queue_key"],
                name="uniq_duty_queue_scope_key",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return self.queue_key


class RoutingExceptionCode(models.TextChoices):
    NO_MATCH = "NO_MATCH"
    MULTIPLE_MATCH = "MULTIPLE_MATCH"
    INACTIVE_TARGET = "INACTIVE_TARGET"


class RoutingExceptionState(models.TextChoices):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RoutingException(VersionedModel):
    """A visible, owned routing failure (data model `routing_exception`, FR-07). The case keeps
    its accountable central queue; the exception never resets elapsed case age."""

    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="routing_exceptions"
    )
    code = models.CharField(max_length=16, choices=RoutingExceptionCode.choices)
    input_snapshot = models.JSONField(default=dict)
    routing_artifact = models.ForeignKey(
        "policies.PolicyArtifact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    owner_queue = models.ForeignKey(DutyQueue, on_delete=models.PROTECT, related_name="+")
    state = models.CharField(
        max_length=10, choices=RoutingExceptionState.choices, default=RoutingExceptionState.OPEN
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolution = models.TextField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "code"],
                condition=models.Q(state="OPEN"),
                name="uniq_open_routing_exception_per_case_code",
            ),
            models.CheckConstraint(
                condition=models.Q(code__in=[c.value for c in RoutingExceptionCode]),
                name="chk_routing_exception_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} [{self.state}] {self.application_id}"


class RoutingEntry(models.Model):
    """One row of a ROUTING artifact, materialised for indexed lookup. Rows are replaced only by
    publishing a new artifact number; they are never edited in place."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(
        "policies.PolicyArtifact", on_delete=models.PROTECT, related_name="routing_entries"
    )
    ward_key = models.CharField(max_length=40)
    category_key = models.CharField(max_length=40, null=True, blank=True)
    target_jurisdiction = models.ForeignKey(
        "policies.Jurisdiction", on_delete=models.PROTECT, related_name="+"
    )
    target_queue = models.ForeignKey(DutyQueue, on_delete=models.PROTECT, related_name="+")
    priority = models.IntegerField(default=0)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["artifact", "ward_key", "category_key"], name="idx_routing_lookup")
        ]

    def __str__(self) -> str:
        return f"{self.ward_key}/{self.category_key or '*'} -> {self.target_queue_id}"
