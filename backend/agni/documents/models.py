"""Documents persistence (data model s.3 `upload_reservation`, `document_version`,
`document_access`; integrations s.3). Objects live in private storage under server-generated
keys; a document version binds one immutable object identity (final key + SHA-256) to a scan
state. Rejected files are never exposed to ordinary preview."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


class UploadTargetType(models.TextChoices):
    APPLICATION_DRAFT = "APPLICATION_DRAFT"
    NOTICE_RESPONSE = "NOTICE_RESPONSE"
    INSPECTION_EVIDENCE = "INSPECTION_EVIDENCE"
    SUPPORT_ATTACHMENT = "SUPPORT_ATTACHMENT"
    POLICY_BASIS = "POLICY_BASIS"


class ReservationState(models.TextChoices):
    RESERVED = "RESERVED"
    UPLOADED = "UPLOADED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    ABORTED = "ABORTED"


class UploadReservation(VersionedModel):
    """Temporary, bounded write target. The client never receives bucket credentials: bytes are
    streamed through the API to the staging key and hashed server-side."""

    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    target_type = models.CharField(max_length=24, choices=UploadTargetType.choices)
    target_id = models.UUIDField()
    requirement_code = models.CharField(max_length=60)
    original_name = models.CharField(max_length=180)
    media_type = models.CharField(max_length=120)
    expected_size = models.BigIntegerField()
    expected_sha256 = models.CharField(max_length=64, null=True, blank=True)
    object_key = models.TextField(unique=True)
    state = models.CharField(
        max_length=12, choices=ReservationState.choices, default=ReservationState.RESERVED
    )
    expires_at = models.DateTimeField()
    uploaded_size = models.BigIntegerField(null=True, blank=True)
    uploaded_sha256 = models.CharField(max_length=64, null=True, blank=True)
    object_version_id = models.TextField(null=True, blank=True)
    document_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expected_size__gt=0), name="chk_reservation_size_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(target_type__in=[t.value for t in UploadTargetType]),
                name="chk_reservation_target_type",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ReservationState]),
                name="chk_reservation_state",
            ),
        ]
        indexes = [
            models.Index(fields=["state", "expires_at"], name="idx_reservation_expiry"),
            models.Index(fields=["target_type", "target_id"], name="idx_reservation_target"),
        ]

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id}:{self.requirement_code} [{self.state}]"


class ScanState(models.TextChoices):
    QUARANTINED = "QUARANTINED"
    CLEAN = "CLEAN"
    REJECTED = "REJECTED"


class DocumentVersion(VersionedModel):
    """Immutable object identity (`object_key` + `sha256`) with a scan state that moves
    QUARANTINED -> CLEAN | REJECTED exactly once. Metadata edits never change the bytes."""

    application = models.ForeignKey(
        "cases.Application",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    premises = models.ForeignKey(
        "cases.Premises", null=True, blank=True, on_delete=models.PROTECT, related_name="documents"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requirement_code = models.CharField(max_length=60)
    original_name = models.CharField(max_length=180)
    media_type = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    object_key = models.TextField()
    object_version_id = models.TextField()
    scan_state = models.CharField(
        max_length=12, choices=ScanState.choices, default=ScanState.QUARANTINED
    )
    scan_engine = models.CharField(max_length=120, null=True, blank=True)
    scan_engine_version = models.CharField(max_length=120, null=True, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    scan_detail = models.CharField(max_length=200, blank=True, default="")
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    reservation = models.OneToOneField(
        UploadReservation, on_delete=models.PROTECT, related_name="produced_version"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(application__isnull=False) | models.Q(premises__isnull=False),
                name="chk_document_has_owner_aggregate",
            ),
            models.CheckConstraint(
                condition=models.Q(scan_state__in=[s.value for s in ScanState]),
                name="chk_document_scan_state",
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0), name="chk_document_size_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["application", "requirement_code"], name="idx_document_app_req"),
            models.Index(fields=["sha256"], name="idx_document_sha256"),
        ]

    def __str__(self) -> str:
        return f"{self.requirement_code}:{self.original_name} [{self.scan_state}]"


class AccessPurpose(models.TextChoices):
    PREVIEW = "PREVIEW"
    DOWNLOAD = "DOWNLOAD"
    PRINT = "PRINT"


class AccessMechanism(models.TextChoices):
    PROXY = "PROXY"
    SIGNED_URL = "SIGNED_URL"


class DocumentAccess(AppendOnlyModel):
    """Append-only access grant audit. The ticket is short-lived and principal-bound; no
    reusable unexpired URL is ever stored."""

    document_version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="accesses"
    )
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    purpose = models.CharField(max_length=10, choices=AccessPurpose.choices)
    mechanism = models.CharField(max_length=12, choices=AccessMechanism.choices)
    expires_at = models.DateTimeField()
    request_id = models.UUIDField()

    class Meta:
        indexes = [
            models.Index(fields=["document_version", "created_at"], name="idx_doc_access_time")
        ]

    def __str__(self) -> str:
        return f"{self.purpose}:{self.document_version_id}"
