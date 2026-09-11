"""Inspections persistence (data model s.3 `inspection`, `assignment`, `availability`; s.5
constraint examples). Attempts are retained forever; one ACTIVE assignment per attempt; an
officer's ACTIVE bookings never overlap (half-open GiST exclusion); availability changes and
booking commands share the officer's scheduling fence (the principal fence row)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import Func

from agni.platform.models import VersionedModel


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class InspectionPurpose(models.TextChoices):
    INITIAL = "INITIAL"
    REINSPECTION = "REINSPECTION"
    CLARIFICATION = "CLARIFICATION"


class InspectionStatus(models.TextChoices):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_INSPECTION_STATES = frozenset(
    {InspectionStatus.COMPLETED, InspectionStatus.FAILED, InspectionStatus.CANCELLED}
)

FAILED_VISIT_REASONS = (
    "SITE_INACCESSIBLE",
    "APPLICANT_UNAVAILABLE",
    "SAFETY_CONCERN",
    "WEATHER",
    "OFFICER_UNAVAILABLE",
    "OTHER",
)


class Inspection(VersionedModel):
    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="inspections"
    )
    attempt_number = models.PositiveIntegerField()
    purpose = models.CharField(max_length=16, choices=InspectionPurpose.choices)
    parent_inspection = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="follow_ups"
    )
    status = models.CharField(
        max_length=12, choices=InspectionStatus.choices, default=InspectionStatus.REQUESTED
    )
    checklist_artifact = models.ForeignKey(
        "policies.PolicyArtifact", on_delete=models.PROTECT, related_name="+"
    )
    current_assignment = models.ForeignKey(
        "inspections.Assignment", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    appointment_timezone = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    check_in = models.JSONField(default=dict, blank=True)
    failed_reason_code = models.CharField(max_length=50, null=True, blank=True)
    failed_notes = models.TextField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    request_reason = models.TextField(blank=True, default="")
    preferred_window_start = models.DateTimeField(null=True, blank=True)
    preferred_window_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "attempt_number"], name="uniq_inspection_attempt"
            ),
            models.CheckConstraint(
                condition=models.Q(scheduled_end__isnull=True)
                | models.Q(scheduled_end__gt=models.F("scheduled_start")),
                name="chk_inspection_schedule_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in InspectionStatus]),
                name="chk_inspection_status",
            ),
        ]
        indexes = [
            models.Index(fields=["application", "status"], name="idx_inspection_case_status"),
            models.Index(fields=["scheduled_start"], name="idx_inspection_scheduled"),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}#{self.attempt_number} [{self.status}]"

    @property
    def etag(self) -> str:
        return f'"inspection:{self.id}:v{self.version}"'


class AssignmentState(models.TextChoices):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    FULFILLED = "FULFILLED"


class Assignment(VersionedModel):
    inspection = models.ForeignKey(Inspection, on_delete=models.PROTECT, related_name="assignments")
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    number = models.PositiveIntegerField()
    state = models.CharField(
        max_length=10, choices=AssignmentState.choices, default=AssignmentState.ACTIVE
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    booking_start = models.DateTimeField(null=True, blank=True)
    booking_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["inspection", "number"], name="uniq_assignment_number"),
            models.UniqueConstraint(
                fields=["inspection"],
                condition=models.Q(state="ACTIVE"),
                name="one_active_assignment_per_inspection",
            ),
            models.CheckConstraint(
                condition=models.Q(booking_end__isnull=True)
                | models.Q(booking_end__gt=models.F("booking_start")),
                name="chk_assignment_booking_interval",
            ),
            ExclusionConstraint(
                name="no_active_officer_booking_overlap",
                expressions=[
                    (
                        TsTzRange("booking_start", "booking_end", RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                    ("officer", RangeOperators.EQUAL),
                ],
                condition=models.Q(
                    state="ACTIVE", booking_start__isnull=False, booking_end__isnull=False
                ),
            ),
        ]
        indexes = [models.Index(fields=["officer", "state"], name="idx_assignment_officer_state")]

    def __str__(self) -> str:
        return f"{self.inspection_id} -> {self.officer_id} #{self.number} [{self.state}]"


class AvailabilityKind(models.TextChoices):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class Availability(VersionedModel):
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="availability"
    )
    kind = models.CharField(max_length=12, choices=AvailabilityKind.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason_code = models.CharField(max_length=40)
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="chk_availability_interval",
            )
        ]
        indexes = [
            models.Index(
                fields=["officer", "starts_at", "ends_at"], name="idx_availability_officer"
            )
        ]

    def __str__(self) -> str:
        return f"{self.officer_id} {self.kind} {self.starts_at}-{self.ends_at}"
