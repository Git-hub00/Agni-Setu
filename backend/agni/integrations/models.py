"""Integration ownership and reconciliation (FR-29; data model `integration`,
`integration_inbox`, `integration_conflict`). A provider row declares its mode (SIMULATED /
SANDBOX / LIVE), the fields the partner owns, the allowlisted endpoints and a secret
*reference* - never a secret value. Inbound events are persisted before processing, deduplicated
by (integration, source_event_id) and ordered per source entity; anything out of order or
inconsistent becomes an owned conflict instead of overwriting the local reflection."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from agni.platform.models import VersionedModel


class IntegrationMode(models.TextChoices):
    SIMULATED = "SIMULATED"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"


class IntegrationState(models.TextChoices):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    DEGRADED = "DEGRADED"


class ProviderKind(models.TextChoices):
    PARTNER_CASE_SOURCE = "partner_case_source"
    EXTERNAL_CERTIFICATE_SOURCE = "external_certificate_source"
    MESSAGE_SENDER = "message_sender"
    CERTIFICATE_SIGNER = "certificate_signer"
    MALWARE_SCANNER = "malware_scanner"
    OBJECT_STORE = "object_store"
    STAFF_IDENTITY = "staff_identity"


class HealthStatus(models.TextChoices):
    NOT_RUN = "NOT_RUN"
    OK = "OK"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class Integration(VersionedModel):
    key = models.CharField(max_length=80, unique=True)
    display_name = models.CharField(max_length=160)
    mode = models.CharField(max_length=10, choices=IntegrationMode.choices)
    provider_kind = models.CharField(max_length=60, choices=ProviderKind.choices)
    system_of_record_fields = models.JSONField(default=list, blank=True)
    endpoint_allowlist = models.JSONField(default=list, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    # Name of the secret in the approved secret store / environment; the value never lands here.
    credential_secret_ref = models.CharField(max_length=200, blank=True, default="")
    state = models.CharField(
        max_length=10, choices=IntegrationState.choices, default=IntegrationState.DISABLED
    )
    freshness_budget_seconds = models.PositiveIntegerField(default=86400)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    last_health_status = models.CharField(
        max_length=10, choices=HealthStatus.choices, default=HealthStatus.NOT_RUN
    )
    last_health_at = models.DateTimeField(null=True, blank=True)
    last_health_detail = models.CharField(max_length=200, blank=True, default="")
    last_event_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=[m.value for m in IntegrationMode]),
                name="chk_integration_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in IntegrationState]),
                name="chk_integration_state",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.key} [{self.mode}/{self.state}]"

    @property
    def etag(self) -> str:
        return f'"integration:{self.id}:v{self.version}"'


class InboxState(models.TextChoices):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    QUARANTINED = "QUARANTINED"
    CONFLICT = "CONFLICT"


class IntegrationInbox(models.Model):
    """Authenticated raw event, stored before any processing (integrations s.10)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT, related_name="inbox")
    source_event_id = models.CharField(max_length=160)
    source_entity_id = models.CharField(max_length=160)
    source_sequence = models.BigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=80)
    schema_version = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    payload = models.JSONField(default=dict)
    payload_sha256 = models.CharField(max_length=64)
    auth_evidence = models.JSONField(default=dict)
    state = models.CharField(max_length=12, choices=InboxState.choices, default=InboxState.RECEIVED)
    processed_at = models.DateTimeField(null=True, blank=True)
    disposition = models.CharField(max_length=40, null=True, blank=True)
    error_code = models.CharField(max_length=80, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "source_event_id"], name="one_partner_event"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in InboxState]),
                name="chk_inbox_state",
            ),
        ]
        indexes = [
            models.Index(
                fields=["integration", "source_entity_id", "source_sequence"],
                name="idx_inbox_entity_sequence",
            ),
            models.Index(fields=["integration", "state"], name="idx_inbox_state"),
        ]

    def __str__(self) -> str:
        return f"{self.integration_id}:{self.source_event_id} [{self.state}]"


class ConflictReason(models.TextChoices):
    SEQUENCE_GAP = "SEQUENCE_GAP"
    OLDER_THAN_APPLIED = "OLDER_THAN_APPLIED"
    PAYLOAD_MISMATCH = "PAYLOAD_MISMATCH"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class ConflictState(models.TextChoices):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ResolutionOutcome(models.TextChoices):
    APPLY_VERIFIED_SOURCE = "APPLY_VERIFIED_SOURCE"
    IGNORE_DUPLICATE = "IGNORE_DUPLICATE"
    REQUEST_RESEND = "REQUEST_RESEND"
    KEEP_QUARANTINED = "KEEP_QUARANTINED"
    PREDECESSOR_ARRIVED = "PREDECESSOR_ARRIVED"


class IntegrationConflict(VersionedModel):
    inbox = models.ForeignKey(
        IntegrationInbox, null=True, blank=True, on_delete=models.PROTECT, related_name="conflicts"
    )
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT, related_name="conflicts")
    source_entity_id = models.TextField()
    reason_code = models.CharField(max_length=80, choices=ConflictReason.choices)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    detail = models.JSONField(default=dict)
    state = models.CharField(
        max_length=10, choices=ConflictState.choices, default=ConflictState.OPEN
    )
    outcome = models.CharField(
        max_length=30, choices=ResolutionOutcome.choices, null=True, blank=True
    )
    resolution_basis = models.JSONField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in ConflictState]),
                name="chk_integration_conflict_state",
            ),
        ]
        indexes = [
            models.Index(fields=["integration", "state"], name="idx_int_conflict_state"),
            models.Index(fields=["owner_queue", "state"], name="idx_int_conflict_queue"),
        ]

    def __str__(self) -> str:
        return f"conflict {self.reason_code} {self.source_entity_id} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"integration_conflict:{self.id}:v{self.version}"'


class PartnerEntityState(VersionedModel):
    """The local reflection of a partner-owned record: only the fields the partner owns, the
    sequence / version last applied and an optional link to a local case."""

    integration = models.ForeignKey(
        Integration, on_delete=models.PROTECT, related_name="entity_states"
    )
    source_entity_id = models.CharField(max_length=160)
    applied_sequence = models.BigIntegerField(null=True, blank=True)
    applied_source_version = models.CharField(max_length=120, blank=True, default="")
    applied_event_id = models.CharField(max_length=160, blank=True, default="")
    applied_occurred_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict)
    application = models.ForeignKey(
        "cases.Application", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "source_entity_id"], name="uniq_partner_entity"
            )
        ]

    def __str__(self) -> str:
        return f"{self.integration_id}:{self.source_entity_id}@{self.applied_sequence}"
