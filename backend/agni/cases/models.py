"""Cases persistence - foundational entities (data model s.3 `premises`, `application`,
`stage_instance`, `case_event`). Draft/submission revisions, holds and routing exceptions are
added by B05/B06 through expand migrations."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from agni.platform.models import AppendOnlyModel, VersionedModel

from .domain.states import ApplicationStatus

STATUS_CHOICES = [(s.value, s.value) for s in ApplicationStatus]


class Premises(VersionedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="premises"
    )
    display_name = models.CharField(max_length=160)
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True, default="")
    locality = models.CharField(max_length=100)
    ward_key = models.CharField(max_length=40)
    postal_code = models.CharField(max_length=6)
    category_key = models.CharField(max_length=40)
    area_sqm = models.DecimalField(max_digits=12, decimal_places=2)
    height_m = models.DecimalField(max_digits=7, decimal_places=2)
    floor_count = models.PositiveIntegerField()
    occupancy_count = models.PositiveIntegerField(null=True, blank=True)
    source_reference = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "premises"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(area_sqm__gte=0), name="chk_premises_area_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(height_m__gte=0), name="chk_premises_height_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(floor_count__gte=1), name="chk_premises_floor_count_positive"
            ),
        ]
        indexes = [models.Index(fields=["owner", "created_at"], name="idx_premises_owner_created")]

    def __str__(self) -> str:
        return self.display_name


class Application(VersionedModel):
    public_reference = models.CharField(max_length=40, null=True, blank=True, unique=True)
    draft_reference = models.CharField(max_length=40, unique=True)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="applications"
    )
    acting_operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    delegation_id = models.UUIDField(null=True, blank=True)
    premises = models.ForeignKey(Premises, on_delete=models.PROTECT, related_name="applications")
    service = models.ForeignKey(
        "policies.Service", on_delete=models.PROTECT, related_name="applications"
    )
    jurisdiction = models.ForeignKey(
        "policies.Jurisdiction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="applications"
    )
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=ApplicationStatus.DRAFT.value
    )
    policy_version_id = models.UUIDField(null=True, blank=True)
    submitted_revision_id = models.UUIDField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    prior_certificate_id = models.UUIDField(null=True, blank=True)
    source_system = models.TextField(null=True, blank=True)
    source_case_id = models.TextField(null=True, blank=True)
    source_version = models.BigIntegerField(null=True, blank=True)
    current_stage_instance = models.ForeignKey(
        "cases.StageInstance", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    current_draft_revision = models.ForeignKey(
        "cases.DraftRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in ApplicationStatus]),
                name="chk_application_status",
            ),
            models.UniqueConstraint(
                fields=["source_system", "source_case_id"],
                condition=models.Q(source_system__isnull=False, source_case_id__isnull=False),
                name="uniq_application_source_tuple",
            ),
            # Received cases (anything but DRAFT / pre-receipt WITHDRAWN) carry a receipt time.
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT", "WITHDRAWN"])
                | models.Q(submitted_at__isnull=False),
                name="chk_application_received_has_submitted_at",
            ),
        ]
        indexes = [
            models.Index(fields=["applicant", "created_at"], name="idx_application_applicant"),
            models.Index(
                fields=["jurisdiction", "status", "submitted_at"],
                name="idx_application_juris_status",
            ),
            models.Index(fields=["owner_queue", "status"], name="idx_application_queue_status"),
        ]

    def __str__(self) -> str:
        return self.public_reference or self.draft_reference

    @property
    def status_enum(self) -> ApplicationStatus:
        return ApplicationStatus(self.status)


class DraftRevision(AppendOnlyModel):
    """One autosave of the editable draft (data model `draft_revision`). Never a submitted
    revision: submission (B06) freezes a separate `submission_revision`."""

    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="draft_revisions"
    )
    revision_number = models.PositiveIntegerField()
    editable_payload = models.JSONField(default=dict)
    form_schema_ref = models.CharField(max_length=120, blank=True, default="")
    form_schema_artifact = models.ForeignKey(
        "policies.PolicyArtifact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    saved_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "revision_number"], name="uniq_draft_revision_number"
            )
        ]

    def __str__(self) -> str:
        return f"{self.application_id}#{self.revision_number}"


class SubmissionRevision(AppendOnlyModel):
    """Immutable accepted submission (data model `submission_revision`): the frozen fields,
    premises snapshot, declaration snapshot and the pinned policy. Files are fixed through
    `SubmissionDocument` rows pointing at immutable document versions."""

    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="submission_revisions"
    )
    number = models.PositiveIntegerField()
    payload = models.JSONField(default=dict)
    premise_snapshot = models.JSONField(default=dict)
    policy_version = models.ForeignKey(
        "policies.PolicyVersion", on_delete=models.PROTECT, related_name="+"
    )
    schema_ref = models.CharField(max_length=120, blank=True, default="")
    declaration_snapshot = models.JSONField(default=list)
    selection_explanation = models.JSONField(default=dict)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    accepted_at = models.DateTimeField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "number"], name="uniq_submission_revision_number"
            )
        ]

    def __str__(self) -> str:
        return f"{self.application_id}#{self.number}"


class SubmissionDocument(AppendOnlyModel):
    submission_revision = models.ForeignKey(
        SubmissionRevision, on_delete=models.PROTECT, related_name="documents"
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion", on_delete=models.PROTECT, related_name="+"
    )
    requirement_code = models.CharField(max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission_revision", "requirement_code", "document_version"],
                name="uniq_submission_document",
            )
        ]

    def __str__(self) -> str:
        return f"{self.requirement_code}:{self.document_version_id}"


class EventAudience(models.TextChoices):
    PUBLIC_CASE = "PUBLIC_CASE"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"


class HoldKind(models.TextChoices):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    COURT_ORDER = "COURT_ORDER"


class HoldState(models.TextChoices):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CaseHold(VersionedModel):
    """Authorised legal/administrative hold (data model `case_hold`; workflow s.7). Not a
    twelfth case state: it blocks the listed command scope and pauses only the listed
    obligations. Release and time corrections are recorded as events, never edits."""

    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="holds")
    kind = models.CharField(max_length=16, choices=HoldKind.choices)
    reason = models.TextField()
    basis_document = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    authority_grant_id = models.UUIDField(null=True, blank=True)
    starts_at = models.DateTimeField()
    requested_end_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    affected_obligations = models.JSONField(default=list)
    command_block_scope = models.JSONField(default=list)
    state = models.CharField(max_length=10, choices=HoldState.choices, default=HoldState.ACTIVE)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    release_reason = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in HoldKind]), name="chk_case_hold_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in HoldState]),
                name="chk_case_hold_state",
            ),
        ]
        indexes = [models.Index(fields=["application", "state"], name="idx_case_hold_state")]

    def __str__(self) -> str:
        return f"{self.kind} hold on {self.application_id} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"hold:{self.id}:v{self.version}"'


class CaseEvent(AppendOnlyModel):
    """Append-only business timeline ordered by aggregate version, never browser time."""

    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="events")
    aggregate_version = models.BigIntegerField()
    ordinal = models.PositiveSmallIntegerField(default=0)
    event_type = models.CharField(max_length=100)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_kind = models.CharField(max_length=30)
    occurred_at = models.DateTimeField()
    payload = models.JSONField(default=dict)
    audience = models.CharField(
        max_length=12, choices=EventAudience.choices, default=EventAudience.INTERNAL
    )
    request_id = models.UUIDField()
    command_receipt = models.ForeignKey(
        "platform.CommandReceipt", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "aggregate_version", "ordinal"],
                name="uniq_case_event_version_ordinal",
            )
        ]
        indexes = [
            models.Index(
                fields=["application", "occurred_at", "id"], name="idx_case_event_timeline"
            )
        ]


class StageInstance(models.Model):
    """One entry into a named state (workflow s.8, data model s.9). A repeated entry into the
    same state is a new instance; obligations attach to the instance, not the bare state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="stage_instances"
    )
    state = models.CharField(max_length=24, choices=STATUS_CHOICES)
    cycle_number = models.PositiveIntegerField()
    policy_version_id = models.UUIDField(null=True, blank=True)
    entered_event = models.ForeignKey(CaseEvent, on_delete=models.PROTECT, related_name="+")
    entered_at = models.DateTimeField()
    exited_event = models.ForeignKey(
        CaseEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    exited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "cycle_number"], name="uniq_stage_instance_cycle"
            ),
            models.UniqueConstraint(
                fields=["application"],
                condition=models.Q(exited_at__isnull=True),
                name="uniq_open_stage_per_case",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ApplicationStatus]),
                name="chk_stage_instance_state",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.state}#{self.cycle_number}"
