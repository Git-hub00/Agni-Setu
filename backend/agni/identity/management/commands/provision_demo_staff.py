"""Demo-only staff mapping seed (docs/13 s.3; ADR-15).

Creates a STAFF principal bound to an OIDC issuer+subject with one role binding, approved by
a synthetic `demo-bootstrap` SERVICE principal. Refuses to run unless demo controls are enabled
and APP_ENV is not production: live provisioning goes through an approved access request and
the ProvisionStaff command (FR-02), never this shortcut.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind, RoleBinding
from agni.policies.models import Jurisdiction


class Command(BaseCommand):
    help = "DEMO ONLY: bind an OIDC issuer+subject to a staff principal with one role."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--issuer", required=True)
        parser.add_argument("--subject", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--role", required=True, choices=[r.value for r in RoleKey])
        parser.add_argument(
            "--jurisdiction", default="", help="Jurisdiction code (created if missing, demo only)"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.ENABLE_DEMO_CONTROLS or settings.APP_ENV == "production":
            raise CommandError(
                "Refused: demo staff provisioning is only available in demo/non-production mode."
            )
        issuer, subject, name = options["issuer"], options["subject"], options["name"]
        role, jurisdiction_code = options["role"], options["jurisdiction"]
        now = timezone.now()
        with transaction.atomic():
            bootstrap, _ = Principal.objects.get_or_create(
                login_key="service:demo-bootstrap",
                defaults={
                    "kind": PrincipalKind.SERVICE,
                    "display_name": "Demo bootstrap (synthetic)",
                },
            )
            if not hasattr(bootstrap, "fence"):
                from agni.identity.models import PrincipalFence

                PrincipalFence.objects.get_or_create(principal=bootstrap)
            principal = Principal.objects.filter(
                external_issuer=issuer, external_subject=subject
            ).first()
            created = principal is None
            if principal is None:
                principal = Principal.objects.create_principal(
                    kind=PrincipalKind.STAFF,
                    display_name=name,
                    external_issuer=issuer,
                    external_subject=subject,
                )
            jurisdiction = None
            if jurisdiction_code:
                jurisdiction, _ = Jurisdiction.objects.get_or_create(
                    code=jurisdiction_code, defaults={"display_name": f"{jurisdiction_code} (demo)"}
                )
            if not RoleBinding.objects.filter(
                principal=principal,
                role_key=role,
                jurisdiction=jurisdiction,
                revoked_at__isnull=True,
            ).exists():
                RoleBinding.objects.create(
                    principal=principal,
                    role_key=role,
                    jurisdiction=jurisdiction,
                    effective_from=now,
                    approved_by=bootstrap,
                )
        self.stdout.write(
            f"{'created' if created else 'reused'} staff principal {principal.pk} role={role} "
            f"jurisdiction={jurisdiction_code or '-'} (demo mode)"
        )
