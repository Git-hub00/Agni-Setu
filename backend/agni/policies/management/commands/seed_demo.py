"""Demo-only baseline scenario seed (docs/13 s.1-4, task card B04).

Creates the synthetic CENTRAL-PILOT jurisdiction, duty queues, the `demo-fire-noc` service, the
four policy artifacts (FORM / CHECKLIST / CALENDAR / ROUTING), the persona principals with their
role bindings and authority grants, one applicant with owned premises, and policy version 1 taken
through the *real* governance commands: prepared by Arjun (admin), simulated, approved by Meera
(independent approver) and activated by Anita (activation grant). Nothing here invents law or
authority: every value is marked synthetic and the outcome is a DEMO_CERTIFICATE policy.

Refuses to run unless demo controls are enabled outside production. Idempotent: existing rows
are reused, and the governance chain is skipped when an ACTIVE version already exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from agni.cases.models import Premises
from agni.identity import otp
from agni.identity.contacts import normalize_contact
from agni.identity.domain.roles import Capability, RoleKey, ScopeKind
from agni.identity.models import (
    AuthorityGrant,
    ContactIdentity,
    GrantState,
    Principal,
    PrincipalFence,
    PrincipalKind,
    RoleBinding,
)
from agni.platform.canonical import canonical_sha256
from agni.platform.clock import get_clock
from agni.platform.commands import ActorContext, CommandEnvelope, execute
from agni.policies.application.commands import (
    ActivatePolicy,
    ApprovePolicy,
    PreparePolicyDraft,
    RunPolicySimulation,
    SubmitPolicyForReview,
)
from agni.policies.models import (
    ArtifactKind,
    Jurisdiction,
    PolicyArtifact,
    PolicyState,
    PolicyVersion,
    Service,
    ServiceMode,
)
from agni.routing.models import DutyQueue, RoutingEntry

JURISDICTION_CODE = "CENTRAL-PILOT"
SERVICE_KEY = "demo-fire-noc"
POLICY_EFFECTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)

# Stable Keycloak subjects: the realm import (infra/identity/realm-agni-dev.json) pins the same
# user ids, so OIDC `sub` claims map to these principals on every fresh stack.
KEYCLOAK_SUBJECTS: dict[str, str] = {
    "arjun": "5d9b0c4e-2a7f-4b1e-9c3d-000000000001",
    "meera": "5d9b0c4e-2a7f-4b1e-9c3d-000000000002",
    "anita": "5d9b0c4e-2a7f-4b1e-9c3d-000000000003",
    "neha": "5d9b0c4e-2a7f-4b1e-9c3d-000000000004",
    "suresh": "5d9b0c4e-2a7f-4b1e-9c3d-000000000011",
    "priya": "5d9b0c4e-2a7f-4b1e-9c3d-000000000012",
    "dev": "5d9b0c4e-2a7f-4b1e-9c3d-000000000013",
    "asha": "5d9b0c4e-2a7f-4b1e-9c3d-000000000014",
    "chitra": "5d9b0c4e-2a7f-4b1e-9c3d-000000000021",
}

STAFF_PERSONAS: list[tuple[str, str, RoleKey, bool]] = [
    # (subject, display name, role, jurisdiction-scoped?)
    ("arjun", "Arjun Rao", RoleKey.ADMIN, False),
    ("meera", "Meera Shah", RoleKey.POLICY_APPROVER, False),
    ("anita", "Anita Kapoor", RoleKey.SUPERVISOR, True),
    ("neha", "Neha Bansal", RoleKey.LEADERSHIP, True),
    ("suresh", "Suresh Yadav", RoleKey.OFFICER, True),
    ("priya", "Priya Nair", RoleKey.OFFICER, True),
    ("dev", "Dev Malhotra", RoleKey.OFFICER, True),
    ("asha", "Asha Singh", RoleKey.OFFICER, True),
    ("chitra", "Chitra Clerk", RoleKey.SUPERVISOR, True),
]

WARDS: dict[str, str] = {
    "W-01": "Karol Bagh",
    "W-02": "Paharganj",
    "W-03": "Civil Lines",
    "W-04": "Connaught Place",
    "W-05": "Rajendra Nagar",
    "W-06": "Patel Nagar",
    "W-07": "Daryaganj",
    "W-08": "Shadipur",
}

CATEGORIES = ["Restaurant", "Office", "Hospital", "School", "Residential", "Hotel", "Warehouse"]

# Synthetic educational checklist exactly as docs/24 s.4 (not a legal inspection standard).
CHECKLIST_ITEMS: list[dict[str, Any]] = [
    {
        "code": "C01",
        "title": "Means of escape",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": False,
    },
    {
        "code": "C02",
        "title": "Portable fire extinguishers",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": False,
    },
    {
        "code": "C03",
        "title": "Alarm and detection test",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": False,
    },
    {
        "code": "C04",
        "title": "Fire-water and suppression provision",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": True,
    },
    {
        "code": "C05",
        "title": "Electrical safety documentation",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": False,
    },
    {
        "code": "C06",
        "title": "Emergency signage and lighting",
        "mandatory": True,
        "evidence_required": True,
        "na_permitted": False,
    },
    {
        "code": "C07",
        "title": "Emergency access observations",
        "mandatory": False,
        "evidence_required": False,
        "na_permitted": True,
    },
    {
        "code": "C08",
        "title": "Staff training records",
        "mandatory": False,
        "evidence_required": False,
        "na_permitted": True,
    },
]

RAKESH_PREMISES: list[dict[str, Any]] = [
    {
        "display_name": "Mehta Family Restaurant",
        "locality": "Karol Bagh",
        "ward_key": "W-01",
        "category_key": "Restaurant",
        "area_sqm": "320.00",
        "height_m": "7.50",
        "floor_count": 2,
        "occupancy_count": 120,
    },
    {
        "display_name": "Mehta Banquet Studio",
        "locality": "Rajendra Nagar",
        "ward_key": "W-05",
        "category_key": "Restaurant",
        "area_sqm": "780.00",
        "height_m": "9.00",
        "floor_count": 2,
        "occupancy_count": 350,
    },
    {
        "display_name": "Mehta Corner Cafe",
        "locality": "Patel Nagar",
        "ward_key": "W-06",
        "category_key": "Restaurant",
        "area_sqm": "95.00",
        "height_m": "4.20",
        "floor_count": 1,
        "occupancy_count": 40,
    },
    {
        "display_name": "Mehta Market Kitchen",
        "locality": "Paharganj",
        "ward_key": "W-02",
        "category_key": "Restaurant",
        "area_sqm": "210.00",
        "height_m": "6.00",
        "floor_count": 1,
        "occupancy_count": 80,
    },
]


def demo_policy_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "key": "DEMO-DEPARTMENT-REVIEW",
        "mode": "DEMO",
        "outcome_kind": "DEMO_CERTIFICATE",
        "jurisdiction_key": JURISDICTION_CODE,
        "timezone": "Asia/Kolkata",
        "calendar_key": "DEMO-WORKING-CALENDAR-V1",
        "allowed_categories": CATEGORIES,
        "form_schema_key": "premises-v1",
        "checklist_key": "demo-checklist-v1",
        "routing_key": "demo-routing-v1",
        "base_documents": ["ownership", "plan", "electrical"],
        "extra_documents": {
            "Hospital": ["evacuation"],
            "School": ["evacuation"],
            "Hotel": ["evacuation"],
        },
        "inspection_required": True,
        "reject_from": ["REVIEW_PENDING"],
        "withdraw_from": [
            "DRAFT",
            "SUBMITTED",
            "SCRUTINY",
            "INFO_REQUIRED",
            "INSPECTION_PENDING",
            "COMPLIANCE_PENDING",
        ],
        "separation_of_duties": {
            "inspector_cannot_decide": True,
            "preparer_cannot_approve_policy": True,
        },
        "internal_targets": {
            "scrutiny_working_minutes": 480,
            "inspection_calendar_minutes": 10080,
            "review_working_minutes": 480,
            "issuance_calendar_minutes": 1440,
        },
        "case_target_calendar_minutes": 43200,
        "applicant_response_calendar_minutes": 10080,
        "reminder_fractions": [0.75, 1.0],
        "escalation_minutes_after_due": [60, 1440],
        "permitted_pause_reasons": ["AUTHORIZED_ADMINISTRATIVE_HOLD"],
        "sample_validity_days": 365,
        "fees": {"enabled": False},
        "appeals": {
            "enabled": False,
            "referral_text": (
                "Contact the demonstration support desk; this is not a legal appeal service."
            ),
        },
        "external_registration": {"enabled": False},
        "public_fields": [
            "certificate_number",
            "status",
            "premises_display_name",
            "locality",
            "issued_at",
            "valid_until",
            "checked_at",
            "is_demo",
        ],
    }


def _seed_request_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"agni-setu:seed_demo:baseline:{label}")


class Command(BaseCommand):
    help = "DEMO ONLY: seed the synthetic baseline scenario (master data, personas, policy v1)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--scenario", choices=["baseline"], default="baseline")
        parser.add_argument(
            "--require-demo",
            action="store_true",
            help="Explicit acknowledgement that this seeds demo data (always enforced anyway).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.ENABLE_DEMO_CONTROLS or settings.APP_ENV == "production":
            raise CommandError(
                "Refused: seed_demo only runs with ENABLE_DEMO_CONTROLS=true outside production."
            )
        issuer = settings.OIDC_ISSUER
        if not issuer:
            raise CommandError("OIDC_ISSUER must be configured so staff personas map to Keycloak.")
        clock = get_clock()
        now = clock.now()
        report: list[str] = []

        with transaction.atomic():
            bootstrap = self._bootstrap()
            jurisdiction, _ = Jurisdiction.objects.get_or_create(
                code=JURISDICTION_CODE,
                defaults={"display_name": "Central pilot circle (synthetic demo)"},
            )
            queues = {
                key: DutyQueue.objects.get_or_create(
                    jurisdiction=jurisdiction,
                    service=None,
                    queue_key=key,
                    defaults={"display_name": title},
                )[0]
                for key, title in (
                    ("central-scrutiny", "Central scrutiny desk"),
                    ("central-inspection", "Central inspection roster"),
                    ("central-review", "Central review desk"),
                )
            }
            service, _ = Service.objects.get_or_create(
                key=SERVICE_KEY,
                defaults={
                    "title": "Demonstration fire safety certificate",
                    "mode": ServiceMode.DEMO,
                    "active": False,
                    "owner_queue": queues["central-scrutiny"],
                    "public_summary": (
                        "Synthetic demonstration service. Outcomes are sample certificates with "
                        "no legal effect."
                    ),
                },
            )
            staff = self._staff(issuer, jurisdiction, bootstrap, now)
            self._grants(staff, bootstrap, now)
            self._artifacts(jurisdiction, queues["central-scrutiny"])
            self._integrations(queues["central-review"])
            applicant = self._applicant(now)
            report.append(
                f"master data: jurisdiction={jurisdiction.code} queues={len(queues)} "
                f"service={service.key} staff={len(staff)} applicant={applicant.display_name}"
            )

        # Governance chain runs through the kernel (own transactions, audit, receipts, outbox).
        active = PolicyVersion.objects.filter(service=service, state=PolicyState.ACTIVE).first()
        if active is None:
            version = self._govern(service, staff, clock)
            report.append(f"policy v{version.number} {version.state} via kernel commands")
        else:
            report.append(f"policy v{active.number} already ACTIVE; governance chain skipped")

        for line in report:
            self.stdout.write(line)
        self.stdout.write("seed_demo baseline complete (all data synthetic, demo mode)")

    # ---- helpers -------------------------------------------------------------------------------

    def _bootstrap(self) -> Principal:
        bootstrap, _ = Principal.objects.get_or_create(
            login_key="service:demo-bootstrap",
            defaults={"kind": PrincipalKind.SERVICE, "display_name": "Demo bootstrap (synthetic)"},
        )
        PrincipalFence.objects.get_or_create(principal=bootstrap)
        return bootstrap

    def _staff(
        self, issuer: str, jurisdiction: Jurisdiction, bootstrap: Principal, now: datetime
    ) -> dict[str, Principal]:
        staff: dict[str, Principal] = {}
        for subject_key, name, role, scoped in STAFF_PERSONAS:
            subject = KEYCLOAK_SUBJECTS[subject_key]
            principal = Principal.objects.filter(
                external_issuer=issuer, external_subject=subject
            ).first()
            if principal is None:
                # Legacy dev mapping used the username as subject (B03 smoke); adopt it.
                legacy = Principal.objects.filter(
                    external_issuer=issuer, external_subject=subject_key
                ).first()
                if legacy is not None:
                    legacy.external_subject = subject
                    legacy.login_key = f"{issuer}|{subject}"
                    legacy.save(update_fields=["external_subject", "login_key", "updated_at"])
                    principal = legacy
            if principal is None:
                principal = Principal.objects.create_principal(
                    kind=PrincipalKind.STAFF,
                    display_name=name,
                    external_issuer=issuer,
                    external_subject=subject,
                )
            scope = jurisdiction if scoped else None
            if not RoleBinding.objects.filter(
                principal=principal, role_key=role, jurisdiction=scope, revoked_at__isnull=True
            ).exists():
                RoleBinding.objects.create(
                    principal=principal,
                    role_key=role,
                    jurisdiction=scope,
                    effective_from=POLICY_EFFECTIVE_FROM,
                    approved_by=bootstrap,
                )
            staff[subject_key] = principal
        return staff

    def _integrations(self, owner_queue: DutyQueue) -> None:
        """Provider rows for UI-25 (FR-29): a SIMULATED partner case source that accepts signed
        events, and the conditional external certificate source, DISABLED. Secret *references*
        only; the simulator secret lives in settings/environment, never in a row."""
        from agni.integrations.models import (
            Integration,
            IntegrationMode,
            IntegrationState,
            ProviderKind,
        )

        Integration.objects.get_or_create(
            key="demo-partner-case-source",
            defaults={
                "display_name": "Demo partner case source (simulated)",
                "mode": IntegrationMode.SIMULATED,
                "provider_kind": ProviderKind.PARTNER_CASE_SOURCE,
                "system_of_record_fields": [
                    "source_status",
                    "source_reference",
                    "source_updated_at",
                    "local_reference",
                ],
                "endpoint_allowlist": ["simulated://partner-case-source"],
                "capabilities": ["receive_event", "lookup_case"],
                "credential_secret_ref": "DEMO_PARTNER_SHARED_SECRET",
                "state": IntegrationState.ENABLED,
                "freshness_budget_seconds": 86400,
                "owner_queue": owner_queue,
            },
        )
        Integration.objects.get_or_create(
            key="demo-external-certificate-source",
            defaults={
                "display_name": "External certificate source (conditional, not enabled)",
                "mode": IntegrationMode.SIMULATED,
                "provider_kind": ProviderKind.EXTERNAL_CERTIFICATE_SOURCE,
                "system_of_record_fields": ["issuer", "instrument_status", "valid_until"],
                "endpoint_allowlist": [],
                "capabilities": ["verify_issuer", "lookup_instrument"],
                "credential_secret_ref": "",
                "state": IntegrationState.DISABLED,
                "freshness_budget_seconds": 86400,
                "owner_queue": owner_queue,
            },
        )

    def _grants(self, staff: dict[str, Principal], bootstrap: Principal, now: datetime) -> None:
        wanted = [
            # (subject, capability, approver): approver is never the subject or the preparer.
            (staff["meera"], Capability.POLICY_APPROVE, staff["arjun"]),
            (staff["anita"], Capability.POLICY_ACTIVATE, staff["meera"]),
            # Notice publication / finding verification (security s.5 "J plus capability").
            (staff["anita"], Capability.NOTICE_PUBLISH, staff["meera"]),
            # Explicit decision authority (docs/13 s.3 u-supervisor; FR-20). Officers never
            # receive it: the inspecting officer cannot decide.
            (staff["anita"], Capability.CASE_DECIDE, staff["meera"]),
            # Certificate lifecycle instruments (FR-24) need their own explicit authority.
            (staff["anita"], Capability.CERTIFICATE_STATUS, staff["meera"]),
            # Governance of powers (FR-02, UI-21): Meera approves / revokes grants that Arjun
            # prepares; Arjun provisions and reactivates staff from approved requests. Neither
            # can approve a grant they prepared or one that names them.
            (staff["meera"], Capability.GRANT_APPROVE, staff["arjun"]),
            (staff["arjun"], Capability.STAFF_PROVISION, staff["meera"]),
        ]
        for subject, capability, approver in wanted:
            exists = AuthorityGrant.objects.filter(
                subject=subject,
                capability=capability,
                state=GrantState.APPROVED,
                revoked_at__isnull=True,
            ).exists()
            if not exists:
                AuthorityGrant.objects.create(
                    subject=subject,
                    capability=capability,
                    scope_kind=ScopeKind.GLOBAL,
                    effective_from=POLICY_EFFECTIVE_FROM,
                    preparer=bootstrap,
                    approver=approver,
                    state=GrantState.APPROVED,
                    approval_basis="Demo baseline fixture (docs/13 s.3); synthetic authority",
                    approved_at=POLICY_EFFECTIVE_FROM,
                )

    def _artifacts(self, jurisdiction: Jurisdiction, queue: DutyQueue) -> None:
        def ensure(kind: str, key: str, payload: dict[str, Any]) -> PolicyArtifact:
            """Artifacts are immutable: if the latest published number carries different
            content, publish the next number instead of editing in place."""
            digest = canonical_sha256(payload)
            latest = PolicyArtifact.objects.filter(kind=kind, key=key).order_by("-number").first()
            if latest is not None and latest.sha256 == digest:
                return latest
            return PolicyArtifact.objects.create(
                kind=kind,
                key=key,
                number=(latest.number + 1) if latest else 1,
                schema_version="1.0",
                payload=payload,
                sha256=digest,
            )

        ensure(
            ArtifactKind.FORM,
            "premises-v1",
            {
                "fields": [
                    "display_name",
                    "address_line1",
                    "address_line2",
                    "locality",
                    "ward_key",
                    "postal_code",
                    "category_key",
                    "area_sqm",
                    "height_m",
                    "floor_count",
                    "occupancy_count",
                ]
            },
        )
        ensure(ArtifactKind.CHECKLIST, "demo-checklist-v1", {"items": CHECKLIST_ITEMS})
        ensure(
            ArtifactKind.CALENDAR,
            "DEMO-WORKING-CALENDAR-V1",
            # Workflow s.8: the demo working calendar is Monday-Friday 09:00-17:00
            # Asia/Kolkata with no holidays; explicitly synthetic.
            {
                "timezone": "Asia/Kolkata",
                "working_hours": {
                    d: ["09:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")
                },
                "holidays": [],
            },
        )
        entries = [
            {
                "ward_key": ward,
                "category_key": None,
                "target_jurisdiction": jurisdiction.code,
                "target_queue": queue.queue_key,
                "priority": 0,
            }
            for ward in WARDS
        ]
        routing = ensure(ArtifactKind.ROUTING, "demo-routing-v1", {"entries": entries})
        if not RoutingEntry.objects.filter(artifact=routing).exists():
            RoutingEntry.objects.bulk_create(
                [
                    RoutingEntry(
                        artifact=routing,
                        ward_key=ward,
                        category_key=None,
                        target_jurisdiction=jurisdiction,
                        target_queue=queue,
                        priority=0,
                    )
                    for ward in WARDS
                ]
            )

    def _applicant(self, now: datetime) -> Principal:
        contact = normalize_contact("EMAIL", "rakesh@example.test")
        existing = (
            ContactIdentity.objects.select_related("principal")
            .filter(
                channel=contact.channel, lookup_hmac=contact.lookup_hmac, replaced_at__isnull=True
            )
            .first()
        )
        if existing is not None:
            principal = existing.principal
        else:
            # Same login_key shape as OTP sign-in, so the persona signs in through the real path.
            principal = Principal.objects.create_principal(
                kind=PrincipalKind.APPLICANT,
                display_name="Rakesh Mehta",
                login_key=f"contact:{contact.lookup_hmac}",
            )
            otp.record_verified_contact(principal, contact, now)
        for spec in RAKESH_PREMISES:
            Premises.objects.get_or_create(
                owner=principal,
                display_name=spec["display_name"],
                defaults={
                    "address_line1": f"{spec['display_name']}, main road (synthetic)",
                    "locality": spec["locality"],
                    "ward_key": spec["ward_key"],
                    "postal_code": "110005",
                    "category_key": spec["category_key"],
                    "area_sqm": Decimal(spec["area_sqm"]),
                    "height_m": Decimal(spec["height_m"]),
                    "floor_count": spec["floor_count"],
                    "occupancy_count": spec["occupancy_count"],
                },
            )
        return principal

    def _govern(self, service: Service, staff: dict[str, Principal], clock: Any) -> PolicyVersion:
        def env(
            actor: Principal,
            command: str,
            target_type: str,
            target_id: UUID,
            payload: dict[str, Any],
            version: int | None,
        ) -> CommandEnvelope:
            return CommandEnvelope(
                actor=ActorContext(principal_id=actor.pk, request_id=_seed_request_id(command)),
                command_name=command,
                target_type=target_type,
                target_id=target_id,
                payload=payload,
                idempotency_key=f"seed-demo-baseline:{command}",
                expected_version=version,
            )

        arjun, meera, anita = staff["arjun"], staff["meera"], staff["anita"]
        prepared = execute(
            env(
                arjun,
                "prepare-policy",
                "prepare-policy:scope",
                arjun.pk,
                {
                    "service_id": str(service.pk),
                    "schema_version": "1.0",
                    "payload": demo_policy_payload(),
                    "source_references": ["docs/13 s.1-4 demo baseline (synthetic)"],
                    "reason": "Seed the synthetic baseline demonstration policy package",
                },
                None,
            ),
            PreparePolicyDraft(),
            clock=clock,
        )
        version = PolicyVersion.objects.get(pk=prepared.body["policy_version_id"])

        def step(actor: Principal, command: str, payload: dict[str, Any], handler: Any) -> None:
            nonlocal version
            execute(
                env(actor, command, "policy_version", version.pk, payload, version.version),
                handler,
                clock=clock,
            )
            version.refresh_from_db()

        step(
            arjun,
            "submit-policy-review",
            {"reason": "Baseline package ready for independent review"},
            SubmitPolicyForReview(),
        )
        step(
            arjun,
            "simulate-policy",
            {
                "candidate_sha256": version.payload_sha256,
                "fixture_suite_key": "demo-baseline-v1",
                "reason": "Pre-approval simulation of the baseline package",
            },
            RunPolicySimulation(),
        )
        step(
            meera,
            "approve-policy",
            {
                "candidate_sha256": version.payload_sha256,
                "effective_from": POLICY_EFFECTIVE_FROM.isoformat(),
                "effective_until": None,
                "reason": "Independent approval of the synthetic demo baseline (no legal effect)",
            },
            ApprovePolicy(),
        )
        step(
            anita,
            "activate-policy",
            {
                "approved_candidate_sha256": version.payload_sha256,
                "reason": "Activate the demo baseline for the CENTRAL-PILOT service",
            },
            ActivatePolicy(),
        )
        return version
