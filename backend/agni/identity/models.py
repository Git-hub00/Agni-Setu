"""Identity persistence (data model s.3 `principal`). The custom Principal is created in the
initial identity migration because changing AUTH_USER_MODEL later is a migration risk (s.8).

No role or power column is writable by clients; authority comes from role bindings and
approved grants (B03/B04). `authz_epoch` changes whenever authorization facts change so
sessions and cached offline packages can be invalidated.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone


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
    # identities (B03). Never shown to users and never a secret.
    login_key = models.CharField(max_length=200, unique=True)
    external_issuer = models.CharField(max_length=200, null=True, blank=True)
    external_subject = models.CharField(max_length=200, null=True, blank=True)
    kind = models.CharField(max_length=12, choices=PrincipalKind.choices)
    display_name = models.CharField(max_length=160)
    verified_contact_ref = models.UUIDField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    authz_epoch = models.BigIntegerField(default=1)
    disabled_at = models.DateTimeField(null=True, blank=True)
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
