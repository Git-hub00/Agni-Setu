"""Identity persistence (data model s.3 identity tables). The custom Principal is created in
the initial identity migration because changing AUTH_USER_MODEL later is a migration risk (s.8).

No role or power column is writable by clients; authority comes from role bindings and
approved grants. `authz_epoch` changes whenever authorization facts change so sessions and
cached offline packages stop being valid.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone

from agni.platform.models import VersionedModel

from .domain.roles import Capability, RoleKey, ScopeKind


class PrincipalKind(models.TextChoices):
    APPLICANT = "APPLICANT"
    STAFF = "STAFF"
    SERVICE = "SERVICE"


class PrincipalManager(BaseUserManager["Principal"]):
    use_in_migrations = True

    def create_principal(
        self,
        *,
        kind: str,
        display_name: str,
        login_key: str | None = None,
        external_issuer: str | None = None,
        external_subject: str | None = None,
        **extra: Any,
    ) -> Principal:
        """Create a principal with an unusable password and its authorization fence."""
        if login_key is None:
            if external_issuer and external_subject:
                login_key = f"{external_issuer}|{external_subject}"
            else:
                login_key = f"principal:{uuid.uuid4()}"
        with transaction.atomic():
            principal = self.model(
                kind=kind,
                display_name=display_name,
                login_key=login_key,
                external_issuer=external_issuer,
                external_subject=external_subject,
                **extra,
            )
            principal.set_unusable_password()
            principal.save(using=self._db)
            PrincipalFence.objects.create(principal=principal)
        return principal


class Principal(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Internal unique login handle: "<issuer>|<subject>" for OIDC, "contact:<hmac>" for OTP
    # identities. Never shown to users and never a secret.
    login_key = models.CharField(max_length=200, unique=True)
    external_issuer = models.CharField(max_length=200, null=True, blank=True)
    external_subject = models.CharField(max_length=200, null=True, blank=True)
    kind = models.CharField(max_length=12, choices=PrincipalKind.choices)
    display_name = models.CharField(max_length=160)
    verified_contact_ref = models.UUIDField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    authz_epoch = models.BigIntegerField(default=1)
    disabled_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "login_key"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = PrincipalManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["external_issuer", "external_subject"],
                condition=models.Q(external_issuer__isnull=False, external_subject__isnull=False),
                name="uniq_principal_external_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in PrincipalKind]),
                name="chk_principal_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.display_name}"

    @property
    def active(self) -> bool:
        return self.is_active

    def disable(self, at: Any) -> None:
        """Deactivate and bump the epoch so sessions and cached authority stop being valid."""
        self.is_active = False
        self.disabled_at = at
        self.authz_epoch += 1

    def bump_epoch(self) -> None:
        self.authz_epoch += 1


class PrincipalFence(models.Model):
    """Authorization fence row: every command and every grant/delegation change locks this
    row FOR UPDATE (in sorted principal order) so check-then-write races serialise
    (security s.6, architecture s.7)."""

    principal = models.OneToOneField(
        Principal, primary_key=True, on_delete=models.CASCADE, related_name="fence"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"fence:{self.principal_id}"


class ContactChannel(models.TextChoices):
    EMAIL = "EMAIL"
    SMS = "SMS"


class ContactIdentity(models.Model):
    """A verified contact bound to a principal. The value is encrypted at rest; lookups use a
    purpose-specific HMAC (data model `contact_identity`). A contact is not proof of
    ownership or authority (security s.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    principal = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="contacts")
    channel = models.CharField(max_length=5, choices=ContactChannel.choices)
    ciphertext = models.BinaryField()
    lookup_hmac = models.CharField(max_length=64)
    key_version = models.CharField(max_length=30, default="v1")
    verified_at = models.DateTimeField(null=True, blank=True)
    replaced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "lookup_hmac"],
                condition=models.Q(replaced_at__isnull=True),
                name="uniq_active_contact_lookup",
            )
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.lookup_hmac[:8]}"


class OtpPurpose(models.TextChoices):
    SIGN_IN = "SIGN_IN"
    CONTACT_CHANGE = "CONTACT_CHANGE"


class OtpChallenge(models.Model):
    """Purpose-bound one-time code challenge. Stores only a keyed MAC over
    (challenge id, purpose, code) with a dedicated pepper - never the code (security s.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact_lookup_hmac = models.CharField(max_length=64)
    channel = models.CharField(max_length=5, choices=ContactChannel.choices)
    purpose = models.CharField(max_length=40, choices=OtpPurpose.choices)
    code_mac = models.CharField(max_length=64)
    pepper_version = models.CharField(max_length=30)
    principal = models.ForeignKey(
        Principal, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    expires_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    consumed_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    delivery_job_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["contact_lookup_hmac", "purpose", "created_at"], name="idx_otp_contact"
            ),
            models.Index(fields=["expires_at"], name="idx_otp_expiry"),
        ]

    def __str__(self) -> str:
        return f"otp:{self.purpose}:{self.id}"


class RoleBinding(VersionedModel):
    """Workspace membership with explicit scope. NULL scope never means global access."""

    principal = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="role_bindings")
    role_key = models.CharField(max_length=40, choices=[(r.value, r.value) for r in RoleKey])
    jurisdiction = models.ForeignKey(
        "policies.Jurisdiction", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    service = models.ForeignKey(
        "policies.Service", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    approved_request = models.ForeignKey(
        "identity.AccessRequest", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role_key__in=[r.value for r in RoleKey]),
                name="chk_role_binding_key",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__isnull=True)
                | models.Q(effective_until__gt=models.F("effective_from")),
                name="chk_role_binding_interval",
            ),
        ]
        indexes = [
            models.Index(fields=["principal", "role_key"], name="idx_role_binding_principal")
        ]

    def __str__(self) -> str:
        return f"{self.role_key}:{self.principal_id}"


class GrantState(models.TextChoices):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuthorityGrant(VersionedModel):
    """Separately approved statutory/governance power (data model `authority_grant`).
    Approver must differ from preparer and from the subject."""

    subject = models.ForeignKey(
        Principal, on_delete=models.PROTECT, related_name="authority_grants"
    )
    capability = models.CharField(max_length=80, choices=[(c.value, c.value) for c in Capability])
    scope_kind = models.CharField(max_length=12, choices=[(s.value, s.value) for s in ScopeKind])
    jurisdiction = models.ForeignKey(
        "policies.Jurisdiction", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    service = models.ForeignKey(
        "policies.Service", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    category_keys = models.JSONField(default=list, blank=True)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    preparer = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="+")
    approver = models.ForeignKey(
        Principal, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    state = models.CharField(max_length=10, choices=GrantState.choices, default=GrantState.PROPOSED)
    approval_basis = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(approver=models.F("preparer")),
                name="chk_grant_approver_not_preparer",
            ),
            models.CheckConstraint(
                condition=~models.Q(approver=models.F("subject")),
                name="chk_grant_approver_not_subject",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in GrantState]), name="chk_grant_state"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__isnull=True)
                | models.Q(effective_until__gt=models.F("effective_from")),
                name="chk_grant_interval",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind="GLOBAL")
                    & models.Q(jurisdiction__isnull=True, service__isnull=True)
                )
                | (models.Q(scope_kind="JURISDICTION") & models.Q(jurisdiction__isnull=False))
                | (models.Q(scope_kind="SERVICE") & models.Q(service__isnull=False)),
                name="chk_grant_scope_shape",
            ),
        ]
        indexes = [
            models.Index(
                fields=["subject", "capability", "state"], name="idx_grant_subject_capability"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.capability}:{self.subject_id}:{self.state}"


class AccessRequestStatus(models.TextChoices):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AccessRequest(VersionedModel):
    """Provisioning must reference an approved request; no self-approval (data model
    `access_request`, FR-02)."""

    requester = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="+")
    beneficiary = models.ForeignKey(
        Principal, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # For a not-yet-provisioned staff member: the approved OIDC identity to bind.
    intended_issuer = models.CharField(max_length=200, blank=True, default="")
    intended_subject = models.CharField(max_length=200, blank=True, default="")
    intended_display_name = models.CharField(max_length=160, blank=True, default="")
    requested_role = models.CharField(max_length=40, blank=True, default="")
    requested_capabilities = models.JSONField(default=list, blank=True)
    jurisdiction = models.ForeignKey(
        "policies.Jurisdiction", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    service = models.ForeignKey(
        "policies.Service", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    justification = models.TextField()
    status = models.CharField(
        max_length=10, choices=AccessRequestStatus.choices, default=AccessRequestStatus.OPEN
    )
    approver = models.ForeignKey(
        Principal, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decision_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(approver=models.F("requester")),
                name="chk_access_request_no_self_approval",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in AccessRequestStatus]),
                name="chk_access_request_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="idx_access_request_status")]

    def __str__(self) -> str:
        return f"access-request:{self.status}:{self.id}"


class DelegationState(models.TextChoices):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Delegation(VersionedModel):
    """Assisted intake (FR-10, data model `delegation`): a beneficiary lets a delegate act on
    bounded premises/service scope for a finite interval. Contacts never create ownership; the
    beneficiary confirms, the proposer cannot self-confirm."""

    beneficiary = models.ForeignKey(
        Principal, on_delete=models.PROTECT, related_name="delegations_granted"
    )
    delegate = models.ForeignKey(
        Principal, on_delete=models.PROTECT, related_name="delegations_received"
    )
    proposed_by = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="+")
    premises = models.ForeignKey(
        "cases.Premises",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delegations",
    )
    service = models.ForeignKey(
        "policies.Service", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    capabilities = models.JSONField(default=list)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField()
    state = models.CharField(
        max_length=10, choices=DelegationState.choices, default=DelegationState.PROPOSED
    )
    evidence_document_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        Principal, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(beneficiary=models.F("delegate")),
                name="chk_delegation_distinct_parties",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__gt=models.F("effective_from")),
                name="chk_delegation_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in DelegationState]),
                name="chk_delegation_state",
            ),
            models.CheckConstraint(
                condition=models.Q(premises__isnull=False) | models.Q(service__isnull=False),
                name="chk_delegation_has_scope",
            ),
        ]
        indexes = [
            models.Index(fields=["delegate", "state"], name="idx_delegation_delegate"),
            models.Index(fields=["beneficiary", "state"], name="idx_delegation_beneficiary"),
        ]

    def __str__(self) -> str:
        return f"{self.state}:{self.beneficiary_id}->{self.delegate_id}"

    def is_active_at(self, at: Any) -> bool:
        return (
            self.state == DelegationState.ACTIVE
            and self.effective_from <= at < self.effective_until
            and self.revoked_at is None
        )


# Re-exported for convenience in settings-driven code.
AUTH_USER_MODEL_LABEL = settings.AUTH_USER_MODEL
