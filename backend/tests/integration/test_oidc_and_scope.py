"""Staff OIDC mapping (FR-02) with the provider exchange mocked, and scoped read selectors."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.test import Client

from agni.cases.models import Application, Premises
from agni.cases.selectors import visible_applications, visible_premises
from agni.identity import oidc
from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind, RoleBinding
from agni.platform.clock import FrozenClock
from agni.policies.models import Jurisdiction, Service
from agni.routing.models import DutyQueue

ISSUER = "http://localhost:8080/realms/agni-dev"


@pytest.fixture(autouse=True)
def _controlled_clock(monkeypatch: pytest.MonkeyPatch, clock: FrozenClock) -> None:
    monkeypatch.setattr("agni.identity.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.identity.authentication.get_clock", lambda: clock)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("/inspections", "/inspections"),
        ("//evil.example", "/"),
        ("https://evil.example/x", "/"),
        ("inspections", "/"),
    ],
)
def test_only_relative_return_paths_are_honoured(raw: str | None, expected: str) -> None:
    assert oidc.safe_next(raw) == expected


@pytest.mark.django_db
def test_oidc_callback_maps_provisioned_subject_and_establishes_session(
    staff: Principal, clock: FrozenClock
) -> None:
    client = Client()
    session = client.session
    session["agni_oidc_next"] = "/inspections"
    session.save()
    identity = oidc.StaffIdentity(issuer=ISSUER, subject="chitra", display_name="Chitra Clerk")
    with mock.patch.object(oidc, "complete", return_value=identity):
        response = client.get("/api/v1/auth/oidc/callback?code=x&state=y")
    assert response.status_code == 302 and response["Location"] == "/inspections"
    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["data"]["id"] == str(staff.pk)


@pytest.mark.django_db
def test_oidc_unknown_or_disabled_subject_is_refused_without_provisioning(
    staff: Principal, clock: FrozenClock
) -> None:
    client = Client()
    unknown = oidc.StaffIdentity(issuer=ISSUER, subject="stranger", display_name="Stranger")
    with mock.patch.object(oidc, "complete", return_value=unknown):
        response = client.get("/api/v1/auth/oidc/callback?code=x&state=y")
    assert response.status_code == 302 and response["Location"] == "/sign-in?error=forbidden"
    assert client.get("/api/v1/me").status_code == 401
    assert not Principal.objects.filter(external_subject="stranger").exists()

    staff.disable(clock.now())
    staff.save()
    with mock.patch.object(
        oidc, "complete", return_value=oidc.StaffIdentity(ISSUER, "chitra", "Chitra")
    ):
        response = client.get("/api/v1/auth/oidc/callback?code=x&state=y")
    assert response["Location"] == "/sign-in?error=authority_revoked"

    # Same subject from another issuer is a different identity (issuer+subject rule).
    with mock.patch.object(
        oidc,
        "complete",
        return_value=oidc.StaffIdentity("https://other.example", "chitra", "Chitra"),
    ):
        response = client.get("/api/v1/auth/oidc/callback?code=x&state=y")
    assert response["Location"] == "/sign-in?error=forbidden"


@pytest.mark.django_db
def test_oidc_start_with_unreachable_provider_is_503_not_500(clock: FrozenClock) -> None:
    import requests

    client = Client()
    with mock.patch.object(oidc, "start", side_effect=requests.ConnectionError("refused")):
        response = client.get("/api/v1/auth/oidc/start?next=/account")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.django_db
def test_oidc_provider_failure_never_creates_a_session(clock: FrozenClock) -> None:
    client = Client()
    with mock.patch.object(oidc, "complete", side_effect=RuntimeError("bad token")):
        response = client.get("/api/v1/auth/oidc/callback?code=x&state=y")
    assert response.status_code == 302 and response["Location"] == "/sign-in?error=oidc_failed"
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.django_db
def test_at_02_04_scope_selectors_hide_other_applicants_and_other_jurisdictions(
    applicant: Principal,
    other_applicant: Principal,
    premises: Premises,
    service: Service,
    duty_queue: DutyQueue,
    jurisdiction: Jurisdiction,
    clock: FrozenClock,
) -> None:
    own = Application.objects.create(
        draft_reference="DR-1",
        applicant=applicant,
        acting_operator=applicant,
        premises=premises,
        service=service,
        owner_queue=duty_queue,
    )
    submitted = Application.objects.create(
        draft_reference="DR-2",
        public_reference="AS-2026-0002",
        applicant=applicant,
        acting_operator=applicant,
        premises=premises,
        service=service,
        owner_queue=duty_queue,
        status="SUBMITTED",
        submitted_at=clock.now(),
    )
    snap_owner = load_snapshot(applicant, clock.now())
    snap_other = load_snapshot(other_applicant, clock.now())
    assert set(visible_applications(snap_owner)) == {own, submitted}
    assert set(visible_premises(snap_owner)) == {premises}
    assert (
        not visible_applications(snap_other).exists() and not visible_premises(snap_other).exists()
    )

    bootstrap = Principal.objects.create_principal(
        kind=PrincipalKind.STAFF, display_name="B", external_issuer=ISSUER, external_subject="b"
    )
    supervisor = Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name="Anita",
        external_issuer=ISSUER,
        external_subject="anita",
    )
    other_jurisdiction = Jurisdiction.objects.create(
        code="DEMO-CIRCLE-2", display_name="Demo Circle 2"
    )
    RoleBinding.objects.create(
        principal=supervisor,
        role_key=RoleKey.SUPERVISOR,
        jurisdiction=other_jurisdiction,
        effective_from=clock.now() - timedelta(days=1),
        approved_by=bootstrap,
    )
    assert not visible_applications(load_snapshot(supervisor, clock.now())).exists()

    RoleBinding.objects.create(
        principal=supervisor,
        role_key=RoleKey.SUPERVISOR,
        jurisdiction=jurisdiction,
        effective_from=clock.now() - timedelta(days=1),
        approved_by=bootstrap,
    )
    visible = set(visible_applications(load_snapshot(supervisor, clock.now())))
    assert visible == {submitted}  # drafts are never staff-visible; received cases in scope are

    unscoped = Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name="Global?",
        external_issuer=ISSUER,
        external_subject="g",
    )
    RoleBinding.objects.create(
        principal=unscoped,
        role_key=RoleKey.SUPERVISOR,
        effective_from=clock.now() - timedelta(days=1),
        approved_by=bootstrap,
    )
    assert not visible_applications(
        load_snapshot(unscoped, clock.now())
    ).exists()  # NULL scope is not global
