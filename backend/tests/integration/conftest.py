"""Integration fixtures: real PostgreSQL rows for principals, master data, premises, policy
artifacts and a signed-in test client helper."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import Client, RequestFactory

from agni.cases.models import Premises
from agni.identity.domain.roles import Capability, RoleKey, ScopeKind
from agni.identity.models import AuthorityGrant, GrantState, Principal, PrincipalKind, RoleBinding
from agni.identity.sessions import establish_session
from agni.platform.canonical import canonical_sha256
from agni.platform.clock import FrozenClock
from agni.policies.models import Jurisdiction, PolicyArtifact, Service
from agni.routing.models import DutyQueue

ISSUER = "http://localhost:8080/realms/agni-dev"


@pytest.fixture
def applicant(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT, display_name="Asha Applicant"
    )


@pytest.fixture
def other_applicant(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT, display_name="Bala Bystander"
    )


@pytest.fixture
def staff(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name="Chitra Clerk",
        external_issuer=ISSUER,
        external_subject="chitra",
    )


@pytest.fixture
def jurisdiction(db: None) -> Jurisdiction:
    return Jurisdiction.objects.create(code="DEMO-CIRCLE-1", display_name="Demo Circle 1")


@pytest.fixture
def duty_queue(jurisdiction: Jurisdiction) -> DutyQueue:
    return DutyQueue.objects.create(
        jurisdiction=jurisdiction,
        queue_key="demo-central-review",
        display_name="Demo central review",
    )


@pytest.fixture
def service(duty_queue: DutyQueue) -> Service:
    return Service.objects.create(
        key="demo-fire-noc",
        title="Demo fire safety certificate",
        active=True,
        owner_queue=duty_queue,
        public_summary="Demonstration fire-safety certificate service (synthetic).",
    )


@pytest.fixture
def inactive_service(duty_queue: DutyQueue) -> Service:
    return Service.objects.create(
        key="demo-dormant", title="Dormant demo service", active=False, owner_queue=duty_queue
    )


@pytest.fixture
def premises(applicant: Principal) -> Premises:
    return Premises.objects.create(
        owner=applicant,
        display_name="Demo Warehouse A",
        address_line1="1 Demo Road",
        locality="Demo Nagar",
        ward_key="W-01",
        postal_code="560001",
        category_key="WAREHOUSE",
        area_sqm=Decimal("1200.50"),
        height_m=Decimal("9.50"),
        floor_count=2,
    )


# ---- policy fixtures -------------------------------------------------------------------------


def make_artifact(kind: str, key: str, number: int, payload: dict[str, Any]) -> PolicyArtifact:
    return PolicyArtifact.objects.create(
        kind=kind,
        key=key,
        number=number,
        schema_version="1.0",
        payload=payload,
        sha256=canonical_sha256(payload),
    )


@pytest.fixture
def artifacts(
    db: None, jurisdiction: Jurisdiction, duty_queue: DutyQueue
) -> dict[str, PolicyArtifact]:
    form = make_artifact(
        "FORM", "premises-v1", 1, {"fields": ["display_name", "address_line1", "category_key"]}
    )
    checklist = make_artifact(
        "CHECKLIST",
        "demo-checklist-v1",
        1,
        {
            "items": [
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
                    "code": "C07",
                    "title": "Emergency access observations",
                    "mandatory": False,
                    "evidence_required": False,
                    "na_permitted": True,
                },
            ]
        },
    )
    calendar = make_artifact(
        "CALENDAR",
        "DEMO-WORKING-CALENDAR-V1",
        1,
        {
            "timezone": "Asia/Kolkata",
            "working_hours": {d: ["09:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")},
            "holidays": [],
        },
    )
    routing = make_artifact(
        "ROUTING",
        "demo-routing-v1",
        1,
        {
            "entries": [
                {
                    "ward_key": "W-01",
                    "category_key": None,
                    "target_jurisdiction": jurisdiction.code,
                    "target_queue": duty_queue.queue_key,
                    "priority": 0,
                },
                {
                    "ward_key": "W-07",
                    "category_key": None,
                    "target_jurisdiction": jurisdiction.code,
                    "target_queue": duty_queue.queue_key,
                    "priority": 0,
                },
            ]
        },
    )
    return {"FORM": form, "CHECKLIST": checklist, "CALENDAR": calendar, "ROUTING": routing}


def demo_policy_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "key": "DEMO-DEPARTMENT-REVIEW",
        "mode": "DEMO",
        "outcome_kind": "DEMO_CERTIFICATE",
        "jurisdiction_key": "DEMO-CIRCLE-1",
        "timezone": "Asia/Kolkata",
        "calendar_key": "DEMO-WORKING-CALENDAR-V1",
        "allowed_categories": [
            "Restaurant",
            "Office",
            "Hospital",
            "School",
            "Residential",
            "Hotel",
            "Warehouse",
        ],
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
    payload.update(overrides)
    return payload


def make_staff(name: str, subject: str) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name=name,
        external_issuer=ISSUER,
        external_subject=subject,
    )


def bind_role(
    principal: Principal,
    role: RoleKey,
    approved_by: Principal,
    clock: FrozenClock,
    jurisdiction: Jurisdiction | None = None,
) -> RoleBinding:
    return RoleBinding.objects.create(
        principal=principal,
        role_key=role,
        jurisdiction=jurisdiction,
        effective_from=clock.now() - timedelta(days=1),
        approved_by=approved_by,
    )


def grant(
    subject: Principal,
    capability: Capability,
    preparer: Principal,
    approver: Principal,
    clock: FrozenClock,
    **kw: Any,
) -> AuthorityGrant:
    return AuthorityGrant.objects.create(
        subject=subject,
        capability=capability,
        scope_kind=kw.pop("scope_kind", ScopeKind.GLOBAL),
        effective_from=kw.pop("effective_from", clock.now() - timedelta(days=1)),
        preparer=preparer,
        approver=approver,
        state=GrantState.APPROVED,
        approval_basis="bootstrap fixture",
        approved_at=clock.now() - timedelta(days=1),
        **kw,
    )


@pytest.fixture
def governance_actors(db: None, clock: FrozenClock) -> dict[str, Principal]:
    """Synthetic governance cast (demo 13 s.3): bootstrap ceremony, admin preparer (Arjun),
    second admin editor, independent policy approver (Meera) and an activator."""
    bootstrap = make_staff("Bootstrap Ceremony", "bootstrap")
    admin = make_staff("Arjun Rao", "arjun")
    editor = make_staff("Second Admin", "second-admin")
    approver = make_staff("Meera Shah", "meera")
    activator = make_staff("Activation Authority", "activator")
    bind_role(admin, RoleKey.ADMIN, bootstrap, clock)
    bind_role(editor, RoleKey.ADMIN, bootstrap, clock)
    bind_role(approver, RoleKey.POLICY_APPROVER, bootstrap, clock)
    grant(approver, Capability.POLICY_APPROVE, bootstrap, admin, clock)
    grant(activator, Capability.POLICY_ACTIVATE, bootstrap, approver, clock)
    return {
        "bootstrap": bootstrap,
        "admin": admin,
        "editor": editor,
        "approver": approver,
        "activator": activator,
    }


# ---- signed-in client -----------------------------------------------------------------------


@pytest.fixture
def signed_client(
    clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> Callable[[Principal], Client]:
    """Return a Client with a real server session for the principal (same code path as OTP/OIDC
    sign-in) and the CSRF token pre-attached to every request header."""
    monkeypatch.setattr("agni.identity.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.identity.authentication.get_clock", lambda: clock)
    monkeypatch.setattr("agni.platform.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.policies.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.cases.api.views.get_clock", lambda: clock)

    def factory(principal: Principal) -> Client:
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: HttpResponse()).process_request(request)
        request.session.save()
        establish_session(request, principal, method="test", clock=clock)
        request.session.save()
        client = Client(enforce_csrf_checks=True)
        client.cookies["sessionid"] = request.session.session_key or ""
        token = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
        client.defaults["HTTP_X_CSRFTOKEN"] = token
        return client

    return factory
