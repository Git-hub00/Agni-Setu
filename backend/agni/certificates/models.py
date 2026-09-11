"""Issuance and the certificate registry (FR-21/FR-22; data model `issuance_request`,
`certificate`; integrations s.5-7).

An `IssuanceRequest` carries the stable identity a retry must reuse: logical action id,
certificate number and, once rendered, the artifact. A `Certificate` is the registry entry
created by the guarded publication (TR-11). Expiry is derived from the validity interval at
read time; the administrative `recorded_status` is preserved beneath the derived display."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


class IssuanceState(models.TextChoices):
    READY = "READY"
    PROCESSING = "PROCESSING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ArtifactMode(models.TextChoices):
    DEMO_WATERMARK = "DEMO_WATERMARK"
    SIGNED = "SIGNED"


class OutcomeKind(models.TextChoices):
    DEMO_CERTIFICATE = "DEMO_CERTIFICATE"
    ISSUED_DEPARTMENT = "ISSUED_DEPARTMENT"
    REGISTERED_EXTERNAL = "REGISTERED_EXTERNAL"


class RecordedStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CertificateSequence(models.Model):
    """Per-year allocator for the human certificate reference (locked FOR UPDATE)."""

    year = models.PositiveIntegerField(primary_key=True)
    last_number = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "certificates_certificatesequence"

    def __str__(self) -> str:
        return f"{self.year}: {self.last_number}"


class IssuanceRequest(VersionedModel):
    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="issuance_requests"
    )
    decision = models.OneToOneField(
        "decisions.Decision", on_delete=models.PROTECT, related_name="issuance_request"
    )
    logical_action_id = models.UUIDField(unique=True)
    certificate_number = models.CharField(max_length=50, unique=True)
    state = models.CharField(
        max_length=24, choices=IssuanceState.choices, default=IssuanceState.READY
    )
    template_key = models.CharField(max_length=80)
    template_version = models.PositiveIntegerField()
    # Frozen at the first attempt so every retry renders the same business data.
    render_snapshot = models.JSONField(default=dict)
    token_hash = models.CharField(max_length=64, null=True, blank=True)
    token_ciphertext = models.BinaryField(null=True, blank=True)
    token_key_version = models.CharField(max_length=40, blank=True, default="")
    artifact = models.ForeignKey(
        "certificates.CertificateArtifact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    provider_request_id = models.TextField(null=True, blank=True)
    signature_verification = models.JSONField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=80, null=True, blank=True)
    reconciliation_note = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in IssuanceState]),
                name="chk_issuance_state",
            )
        ]

    def __str__(self) -> str:
        return f"issuance {self.certificate_number} [{self.state}]"


class CertificateArtifact(AppendOnlyModel):
    """Immutable rendered instrument bytes (content-addressed object key)."""

    issuance_request = models.ForeignKey(
        IssuanceRequest, on_delete=models.PROTECT, related_name="artifacts"
    )
    object_key = models.TextField(unique=True)
    object_version_id = models.TextField()
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField()
    media_type = models.CharField(max_length=120)
    mode = models.CharField(max_length=20, choices=ArtifactMode.choices)
    renderer = models.CharField(max_length=80)
    renderer_version = models.CharField(max_length=80)
    rendered_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"artifact {self.sha256[:12]} ({self.mode})"


class Certificate(VersionedModel):
    application = models.ForeignKey(
        "cases.Application", on_delete=models.PROTECT, related_name="certificates"
    )
    issuance_request = models.OneToOneField(
        IssuanceRequest,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="certificate",
    )
    outcome_kind = models.CharField(max_length=24, choices=OutcomeKind.choices)
    certificate_number = models.CharField(max_length=50, unique=True)
    # SHA-256 (hex) of the high-entropy public token: lookups never touch the token itself.
    verification_token_hash = models.CharField(max_length=64, unique=True)
    verification_token_ciphertext = models.BinaryField()
    token_key_version = models.CharField(max_length=40)
    artifact = models.ForeignKey(
        CertificateArtifact, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issuer_reference = models.TextField()
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    recorded_status = models.CharField(
        max_length=12, choices=RecordedStatus.choices, default=RecordedStatus.ACTIVE
    )
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors"
    )
    source_system = models.TextField(null=True, blank=True)
    source_certificate_id = models.TextField(null=True, blank=True)
    verified_source_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "source_certificate_id"],
                condition=models.Q(source_system__isnull=False),
                name="uniq_certificate_external_tuple",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_status__in=[s.value for s in RecordedStatus]),
                name="chk_certificate_recorded_status",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome_kind__in=[k.value for k in OutcomeKind]),
                name="chk_certificate_outcome_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["application", "issued_at"], name="idx_certificate_case"),
        ]

    def __str__(self) -> str:
        return f"{self.certificate_number} [{self.recorded_status}]"

    @property
    def etag(self) -> str:
        return f'"certificate:{self.id}:v{self.version}"'


class StatusAction(models.TextChoices):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"
    SUPERSEDE = "SUPERSEDE"


class CertificateStatusInstrument(AppendOnlyModel):
    """Authorised status action (data model `certificate_status_instrument`): reason, public
    reason, basis evidence and the grant in force; the effect is applied under the certificate
    lock. Append-only - a reversal is another instrument."""

    certificate = models.ForeignKey(
        Certificate, on_delete=models.PROTECT, related_name="status_instruments"
    )
    action = models.CharField(max_length=12, choices=StatusAction.choices)
    authority_grant = models.ForeignKey(
        "identity.AuthorityGrant", on_delete=models.PROTECT, related_name="+"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    effective_at = models.DateTimeField()
    reason = models.TextField()
    public_reason = models.TextField()
    evidence = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    successor_certificate = models.ForeignKey(
        Certificate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status_before = models.CharField(max_length=12, choices=RecordedStatus.choices)
    status_after = models.CharField(max_length=12, choices=RecordedStatus.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action__in=[a.value for a in StatusAction]),
                name="chk_status_instrument_action",
            )
        ]
        indexes = [
            models.Index(fields=["certificate", "effective_at"], name="idx_status_instrument_cert")
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.certificate_id} @ {self.effective_at:%Y-%m-%d}"
