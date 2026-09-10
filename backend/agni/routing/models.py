"""Duty queues (data model s.3 `duty_queue`): every submitted case has an accountable owner
queue; the fallback queue keeps unowned work visible."""

from __future__ import annotations

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
