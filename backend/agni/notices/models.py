"""Notices persistence (data model s.3 `finding`, `notice`, `notice_item`, `response_revision`,
`finding_review`). Published notice content is immutable; item and finding states move only
through reviewed commands; responses and reviews are append-only history. Applicants can
never execute VERIFIED_CLOSED."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


class NoticeType(models.TextChoices):
    INFORMATION = "INFORMATION"
    DEFICIENCY = "DEFICIENCY"


class NoticeState(models.TextChoices):
    DRAFT = "DRAFT"  # reserved by the state machine; publication is direct in baseline 2.0
    PUBLISHED = "PUBLISHED"
    SATISFIED = "SATISFIED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ItemState(models.TextChoices):
    OPEN = "OPEN"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class FindingSeverity(models.TextChoices):
    MANDATORY = "MANDATORY"
    ADVISORY = "ADVISORY"


class FindingState(models.TextChoices):
    OPEN = "OPEN"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class ReviewOutcome(models.TextChoices):
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    RETURNED = "RETURNED"
    REINSPECTION_REQUIRED = "REINSPECTION_REQUIRED"


class ItemReviewOutcome(models.TextChoices):
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class Finding(VersionedModel):
    """An itemised deficiency recorded by an accepted inspection report (FR-14). Retained when a
    notice is superseded; closed only by an authorised verification."""

    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="findings"
    )
    originating_report = models.ForeignKey(
        "inspections.InspectionReport", on_delete=models.PROTECT, related_name="findings"
    )
    checklist_item_code = models.CharField(max_length=40)
    severity = models.CharField(max_length=10, choices=FindingSeverity.choices)
    state = models.CharField(max_length=20, choices=FindingState.choices, default=FindingState.OPEN)
    description = models.TextField()
    current_response = models.ForeignKey(
        "notices.ResponseRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reinspection_required = models.BooleanField(default=False)
    last_review_reason = models.TextField(blank=True, default="")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_evidence = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["originating_report", "checklist_item_code"],
                name="uniq_finding_report_item",
            ),
            models.CheckConstraint(
                condition=~models.Q(state="VERIFIED_CLOSED")
                | models.Q(closed_by__isnull=False, closed_at__isnull=False),
                name="chk_finding_closure_attributed",
            ),
        ]
        indexes = [models.Index(fields=["application", "state"], name="idx_finding_case_state")]

    def __str__(self) -> str:
        return f"{self.checklist_item_code} [{self.severity}/{self.state}]"

    @property
    def etag(self) -> str:
        return f'"finding:{self.id}:v{self.version}"'


class Notice(VersionedModel):
    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="notices"
    )
    round_number = models.PositiveIntegerField()
    type = models.CharField(max_length=12, choices=NoticeType.choices)
    state = models.CharField(
        max_length=12, choices=NoticeState.choices, default=NoticeState.PUBLISHED
    )
    policy_version = models.ForeignKey(
        "policies.PolicyVersion", on_delete=models.PROTECT, related_name="+"
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    published_at = models.DateTimeField()
    due_obligation = models.ForeignKey(
        "obligations.Obligation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    public_reason = models.TextField()
    internal_note = models.TextField(blank=True, default="")
    response_budget_minutes = models.PositiveIntegerField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "type", "round_number"], name="uniq_notice_round"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in NoticeState]),
                name="chk_notice_state",
            ),
        ]
        indexes = [models.Index(fields=["application", "state"], name="idx_notice_case_state")]

    def __str__(self) -> str:
        return f"{self.type} round {self.round_number} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"notice:{self.id}:v{self.version}"'


class NoticeItem(VersionedModel):
    notice = models.ForeignKey(Notice, on_delete=models.PROTECT, related_name="items")
    code = models.CharField(max_length=60)
    finding = models.ForeignKey(
        Finding, null=True, blank=True, on_delete=models.PROTECT, related_name="notice_items"
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    required = models.BooleanField(default=True)
    acceptable_evidence_types = models.JSONField(default=list)
    public_guidance = models.TextField(blank=True, default="")
    state = models.CharField(max_length=20, choices=ItemState.choices, default=ItemState.OPEN)
    current_response = models.ForeignKey(
        "notices.ResponseRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reviewer_feedback = models.TextField(blank=True, default="")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["notice", "code"], name="uniq_notice_item_code"),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ItemState]),
                name="chk_notice_item_state",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.notice_id}:{self.code} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"notice_item:{self.id}:v{self.version}"'


class ResponseRevision(AppendOnlyModel):
    """One applicant response to one item (FR-16). Never deletes earlier revisions and never
    closes a finding by itself."""

    notice_item = models.ForeignKey(NoticeItem, on_delete=models.PROTECT, related_name="responses")
    number = models.PositiveIntegerField()
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    explanation = models.TextField()
    declaration_accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notice_item", "number"], name="uniq_response_revision_number"
            )
        ]

    def __str__(self) -> str:
        return f"response {self.notice_item_id} r{self.number}"


class ResponseDocument(AppendOnlyModel):
    response = models.ForeignKey(
        ResponseRevision, on_delete=models.PROTECT, related_name="documents"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["response", "document_version"], name="uniq_response_document"
            )
        ]

    def __str__(self) -> str:
        return f"{self.response_id}:{self.document_version_id}"


class NoticeItemReview(AppendOnlyModel):
    """API-058 history: accept or return one item with an actionable public reason."""

    notice_item = models.ForeignKey(NoticeItem, on_delete=models.PROTECT, related_name="reviews")
    response_revision = models.ForeignKey(
        ResponseRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    outcome = models.CharField(max_length=10, choices=ItemReviewOutcome.choices)
    reason = models.TextField()
    evidence_refs = models.JSONField(default=list)
    accepted_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.notice_item_id} {self.outcome}"


class FindingReview(AppendOnlyModel):
    """API-060 history (data model `finding_review`): the finding's current state changes in the
    same transaction."""

    finding = models.ForeignKey(Finding, on_delete=models.PROTECT, related_name="reviews")
    response_revision = models.ForeignKey(
        ResponseRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    outcome = models.CharField(max_length=24, choices=ReviewOutcome.choices)
    reason = models.TextField()
    evidence_snapshot = models.JSONField(default=dict)
    accepted_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.finding_id} {self.outcome}"
