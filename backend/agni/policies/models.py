"""Policy master data and versioned packages (data model s.3 `jurisdiction`, `service`,
`policy_version`, `policy_contributor`, `policy_artifact`, `policy_simulation`; workflow s.5-7).

Approved payloads are immutable; later changes create another version. Approval, preparer
identities and payload hash are relational governance records, never user-editable properties
inside the JSON.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


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
    policy activation (data model s.3, workflow s.7)."""

    key = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=200)
    mode = models.CharField(max_length=24, choices=ServiceMode.choices, default=ServiceMode.DEMO)
    active = models.BooleanField(default=False)
    activation_epoch = models.BigIntegerField(default=1)
    system_of_record = models.CharField(max_length=80, default="agni-setu")
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="owned_services"
    )
    public_summary = models.CharField(max_length=400, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=[m.value for m in ServiceMode]), name="chk_service_mode"
            ),
        ]

    def __str__(self) -> str:
        return self.key


class ArtifactKind(models.TextChoices):
    FORM = "FORM"
    CHECKLIST = "CHECKLIST"
    CALENDAR = "CALENDAR"
    ROUTING = "ROUTING"
    TEMPLATE = "TEMPLATE"


class PolicyArtifact(VersionedModel):
    """Immutable-when-referenced building blocks a policy version points at by key+number."""

    kind = models.CharField(max_length=10, choices=ArtifactKind.choices)
    key = models.CharField(max_length=80)
    number = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=20)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "key", "number"], name="uniq_policy_artifact"),
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in ArtifactKind]),
                name="chk_artifact_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}#{self.number}"

    @property
    def reference(self) -> str:
        return f"{self.key}#{self.number}"


class PolicyState(models.TextChoices):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


EDITABLE_POLICY_STATES = frozenset({PolicyState.DRAFT, PolicyState.RETURNED})
EFFECTIVE_POLICY_STATES = frozenset(
    {PolicyState.APPROVED, PolicyState.SCHEDULED, PolicyState.ACTIVE}
)


class PolicyVersion(VersionedModel):
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="policy_versions")
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="policy_versions",
    )
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=10, choices=PolicyState.choices, default=PolicyState.DRAFT)
    payload = models.JSONField()
    payload_sha256 = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=20)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    legal_basis = models.TextField(null=True, blank=True)
    source_references = models.JSONField(default=list, blank=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_basis = models.TextField(blank=True, default="")
    review_candidate_sha256 = models.CharField(max_length=64, blank=True, default="")
    returned_reason = models.TextField(blank=True, default="")
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "number"], name="uniq_policy_version_number"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in PolicyState]),
                name="chk_policy_state",
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_by=models.F("prepared_by")),
                name="chk_policy_approver_not_preparer",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__isnull=True)
                | models.Q(effective_from__isnull=True)
                | models.Q(effective_until__gt=models.F("effective_from")),
                name="chk_policy_interval",
            ),
            models.CheckConstraint(
                condition=~models.Q(state__in=["APPROVED", "SCHEDULED", "ACTIVE"])
                | models.Q(effective_from__isnull=False, approved_by__isnull=False),
                name="chk_policy_effective_requires_approval",
            ),
        ]
        indexes = [
            models.Index(
                fields=["service", "state", "effective_from"], name="idx_policy_service_state"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.service_id}:v{self.number}:{self.state}"

    @property
    def is_editable(self) -> bool:
        return self.state in EDITABLE_POLICY_STATES


class ContributorAction(models.TextChoices):
    CREATE = "CREATE"
    EDIT = "EDIT"


class PolicyContributor(AppendOnlyModel):
    """Every material preparer is barred from independent approval, not just the creator."""

    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.PROTECT, related_name="contributors"
    )
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=6, choices=ContributorAction.choices)
    command_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy_version", "principal", "command_id"],
                name="uniq_policy_contribution",
            )
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.principal_id}"


class PolicySimulation(AppendOnlyModel):
    """Append-only deterministic simulation results (data model s.9). Approval references an
    exact successful result for the frozen candidate hash."""

    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.PROTECT, related_name="simulations"
    )
    candidate_sha256 = models.CharField(max_length=64)
    fixture_suite_key = models.CharField(max_length=80)
    fixture_suite_version = models.CharField(max_length=20)
    engine_version = models.CharField(max_length=20)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    passed = models.BooleanField()
    result_json = models.JSONField()
    correlation_id = models.UUIDField()

    class Meta:
        indexes = [
            models.Index(
                fields=["policy_version", "candidate_sha256", "completed_at"],
                name="idx_policy_sim_candidate",
            )
        ]

    def __str__(self) -> str:
        return f"sim:{self.fixture_suite_key}:{'pass' if self.passed else 'fail'}"
