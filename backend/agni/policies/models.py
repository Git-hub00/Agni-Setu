"""Foundational policy master data (data model s.3 `jurisdiction`, `service`). Policy
versions, artifacts and contributors arrive in B04."""

from __future__ import annotations

from django.db import models

from agni.platform.models import VersionedModel


class JurisdictionState(models.TextChoices):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Jurisdiction(VersionedModel):
    code = models.CharField(max_length=40, unique=True)
    display_name = models.CharField(max_length=160)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    state = models.CharField(
        max_length=10, choices=JurisdictionState.choices, default=JurisdictionState.ACTIVE
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in JurisdictionState]),
                name="chk_jurisdiction_state",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")), name="chk_jurisdiction_not_own_parent"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class ServiceMode(models.TextChoices):
    DEMO = "DEMO"
    STANDALONE = "STANDALONE"
    INTEGRATED_MONITORING = "INTEGRATED_MONITORING"


class Service(VersionedModel):
    """A regulated service. The locked row is the activation fence used by submission and
    policy activation (data model s.3)."""

    key = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=200)
    mode = models.CharField(max_length=24, choices=ServiceMode.choices, default=ServiceMode.DEMO)
    active = models.BooleanField(default=False)
    activation_epoch = models.BigIntegerField(default=1)
    system_of_record = models.CharField(max_length=80, default="agni-setu")
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="owned_services"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=[m.value for m in ServiceMode]), name="chk_service_mode"
            ),
        ]

    def __str__(self) -> str:
        return self.key
