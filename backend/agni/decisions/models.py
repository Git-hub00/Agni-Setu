"""Guarded decisions (FR-20; data model `decision`). A decision binds the outcome to the exact
evidence reviewed - accepted submission revision, accepted report, finding set, pinned policy -
and to the authority grant in force at command time. Rows are append-only; a later correction
is a separate authorised instrument, never an edit of this row."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel


class DecisionKind(models.TextChoices):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Decision(AppendOnlyModel):
    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="decisions"
    )
    decision_number = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=DecisionKind.choices)
    submitted_revision = models.ForeignKey(
        "cases.SubmissionRevision", on_delete=models.PROTECT, related_name="+"
    )
    report = models.ForeignKey(
        "inspections.InspectionReport",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    evidence_snapshot = models.JSONField(default=dict)
    policy_version = models.ForeignKey(
        "policies.PolicyVersion", on_delete=models.PROTECT, related_name="+"
    )
    authority_grant = models.ForeignKey(
        "identity.AuthorityGrant", on_delete=models.PROTECT, related_name="+"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    public_reason = models.TextField()
    accepted_at = models.DateTimeField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "decision_number"], name="uniq_decision_number"
            ),
            # Initial department-review profile: exactly one final decision per case
            # (data model s.3 `decision`). A later profile with appeals adds instruments.
            models.UniqueConstraint(
                fields=["application"], name="uniq_final_decision_per_application"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in DecisionKind]),
                name="chk_decision_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} #{self.decision_number} on {self.application_id}"
