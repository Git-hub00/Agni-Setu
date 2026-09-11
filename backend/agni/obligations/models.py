"""Obligations (data model s.3 `obligation`): time-bound duties with an accountable owner queue,
a pinned policy/calendar and a stage-instance association. Overdue is calculated, never a
terminal state; pauses (B10/B13) are separate intervals."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import VersionedModel


class TimeBasis(models.TextChoices):
    CALENDAR = "CALENDAR"
    WORKING = "WORKING"


class ObligationState(models.TextChoices):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SATISFIED = "SATISFIED"
    CANCELLED = "CANCELLED"


class ObligationKind(models.TextChoices):
    CASE_TARGET = "CASE_TARGET"
    SCRUTINY_TASK = "SCRUTINY_TASK"
    APPLICANT_RESPONSE = "APPLICANT_RESPONSE"
    INSPECTION_TASK = "INSPECTION_TASK"
    REVIEW_TASK = "REVIEW_TASK"
    ISSUANCE_TASK = "ISSUANCE_TASK"


class Obligation(VersionedModel):
    application = models.ForeignKey(
        "cases.Application",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="obligations",
    )
    certificate_id = models.UUIDField(null=True, blank=True)
    application_stage_instance = models.ForeignKey(
        "cases.StageInstance",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="obligations",
    )
    certificate_lifecycle_instance_id = models.UUIDField(null=True, blank=True)
    kind = models.CharField(max_length=60, choices=ObligationKind.choices)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="obligations"
    )
    responsible_principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    policy_version = models.ForeignKey(
        "policies.PolicyVersion", on_delete=models.PROTECT, related_name="+"
    )
    calendar_artifact = models.ForeignKey(
        "policies.PolicyArtifact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    time_basis = models.CharField(max_length=10, choices=TimeBasis.choices)
    start_event = models.ForeignKey("cases.CaseEvent", on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField()
    budget_minutes = models.BigIntegerField()
    state = models.CharField(
        max_length=10, choices=ObligationState.choices, default=ObligationState.ACTIVE
    )
    due_at = models.DateTimeField(null=True, blank=True)
    next_action_at = models.DateTimeField(null=True, blank=True)
    satisfied_event = models.ForeignKey(
        "cases.CaseEvent", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    generation = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(budget_minutes__gt=0), name="chk_obligation_budget_positive"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        application_stage_instance__isnull=False,
                        certificate_lifecycle_instance_id__isnull=True,
                    )
                    | models.Q(
                        application_stage_instance__isnull=True,
                        certificate_lifecycle_instance_id__isnull=False,
                    )
                ),
                name="chk_obligation_exactly_one_instance",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ObligationState]),
                name="chk_obligation_state",
            ),
            models.UniqueConstraint(
                fields=["application_stage_instance", "kind", "generation"],
                name="uniq_obligation_stage_kind_generation",
            ),
        ]
        indexes = [
            models.Index(
                fields=["due_at"],
                name="idx_obligation_active_due",
                condition=models.Q(state="ACTIVE"),
            ),
            models.Index(fields=["owner_queue", "state"], name="idx_obligation_queue_state"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} [{self.state}] due {self.due_at}"
