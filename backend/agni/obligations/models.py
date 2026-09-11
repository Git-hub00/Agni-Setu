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


class ObligationPause(VersionedModel):
    """Authorised pause interval (data model `obligation_pause`). The clock subtracts the clipped
    union of pauses; an open interval (no end) means no due estimate. Technical outages never
    create pauses; only an authorised hold/pause command does (B13 holds reuse this table)."""

    obligation = models.ForeignKey(Obligation, on_delete=models.PROTECT, related_name="pauses")
    hold_id = models.UUIDField(null=True, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reason_code = models.CharField(max_length=60)
    reason = models.TextField(blank=True, default="")
    authority_grant_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__isnull=True)
                | models.Q(ends_at__gt=models.F("starts_at")),
                name="chk_pause_interval",
            )
        ]
        indexes = [models.Index(fields=["obligation", "starts_at"], name="idx_pause_obligation")]

    def __str__(self) -> str:
        return f"pause {self.obligation_id} {self.starts_at}-{self.ends_at}"


class ThresholdActionType(models.TextChoices):
    REMINDER = "REMINDER"
    ESCALATION = "ESCALATION"


class ThresholdAction(VersionedModel):
    """One logical threshold crossing per obligation cycle (data model `threshold_action`). The
    unique key is what makes two schedulers produce exactly one action and one job."""

    obligation = models.ForeignKey(
        Obligation, on_delete=models.PROTECT, related_name="threshold_actions"
    )
    stage_instance_id = models.UUIDField()
    threshold_key = models.CharField(max_length=80)
    scheduled_for = models.DateTimeField()
    action_type = models.CharField(max_length=12, choices=ThresholdActionType.choices)
    level = models.PositiveIntegerField(default=0)
    logical_job_id = models.UUIDField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    disposition = models.CharField(max_length=40, blank=True, default="")
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["obligation", "stage_instance_id", "threshold_key"],
                name="uniq_threshold_action",
            )
        ]
        indexes = [models.Index(fields=["scheduled_for"], name="idx_threshold_scheduled")]

    def __str__(self) -> str:
        return f"{self.threshold_key} for {self.obligation_id}"


class EscalationState(models.TextChoices):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class Escalation(VersionedModel):
    """Duty-owned intervention task (data model `escalation`). Acknowledgement records ownership
    of the intervention; it never satisfies the obligation or decides the case."""

    obligation = models.ForeignKey(Obligation, on_delete=models.PROTECT, related_name="escalations")
    threshold_action = models.OneToOneField(
        ThresholdAction, null=True, blank=True, on_delete=models.PROTECT, related_name="escalation"
    )
    manual_request_id = models.UUIDField(null=True, blank=True, unique=True)
    level = models.PositiveIntegerField(default=1)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="escalations"
    )
    state = models.CharField(
        max_length=14, choices=EscalationState.choices, default=EscalationState.OPEN
    )
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    next_action = models.TextField(blank=True, default="")
    resolved_event_id = models.UUIDField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(threshold_action__isnull=False)
                | models.Q(manual_request_id__isnull=False),
                name="chk_escalation_origin",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in EscalationState]),
                name="chk_escalation_state",
            ),
        ]
        indexes = [models.Index(fields=["owner_queue", "state"], name="idx_escalation_queue_state")]

    def __str__(self) -> str:
        return f"escalation L{self.level} {self.obligation_id} [{self.state}]"
