"""Session policy (security s.3): idle/absolute lifetimes, epoch recheck, disable, logout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.http import HttpResponse
from django.test import Client

from agni.identity.models import Principal
from agni.identity.sessions import establish_session
from agni.platform.clock import FrozenClock


@pytest.fixture(autouse=True)
def _controlled_clock(monkeypatch: pytest.MonkeyPatch, clock: FrozenClock) -> None:
    monkeypatch.setattr("agni.identity.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.identity.authentication.get_clock", lambda: clock)


def sign_in(client: Client, principal: Principal, clock: FrozenClock) -> None:
    """Establish a session exactly as the OTP/OIDC endpoints do, without a provider round trip."""
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    request.session.save()
    establish_session(request, principal, method="test", clock=clock)
    request.session.save()
    client.cookies["sessionid"] = request.session.session_key or ""


@pytest.mark.django_db
def test_me_requires_authentication(anonymous_client: Client) -> None:
    response = anonymous_client.get("/api/v1/me")
    assert response.status_code == 401 and response.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.django_db
def test_idle_timeout_and_absolute_lifetime_expire_sessions(
    applicant: Principal, clock: FrozenClock
) -> None:
    client = Client()
    sign_in(client, applicant, clock)
    assert client.get("/api/v1/me").status_code == 200

    clock.advance(timedelta(minutes=29))
    assert client.get("/api/v1/me").status_code == 200  # sliding idle window renewed
    clock.advance(timedelta(minutes=31))
    response = client.get("/api/v1/me")
    assert response.status_code == 401 and response.json()["code"] == "SESSION_EXPIRED"
    assert response.json()["reason"] == "idle timeout"

    client = Client()
    sign_in(client, applicant, clock)
    for _ in range(16):  # stay active every 29 minutes: 464 min, still inside the 8 h limit
        clock.advance(timedelta(minutes=29))
        assert client.get("/api/v1/me").status_code == 200
    clock.advance(timedelta(minutes=29))  # 493 min: absolute lifetime exceeded despite activity
    response = client.get("/api/v1/me")
    assert response.status_code == 401 and response.json()["reason"] == "absolute lifetime exceeded"


@pytest.mark.django_db
def test_disabling_or_epoch_change_revokes_existing_sessions(
    applicant: Principal, clock: FrozenClock
) -> None:
    client = Client()
    sign_in(client, applicant, clock)
    assert client.get("/api/v1/me").status_code == 200

    applicant.bump_epoch()
    applicant.save(update_fields=["authz_epoch"])
    response = client.get("/api/v1/me")
    assert (
        response.status_code == 401 and response.json()["reason"] == "authorization epoch changed"
    )
    # The session was flushed: even restoring the epoch does not resurrect it.
    applicant.authz_epoch -= 1
    applicant.save(update_fields=["authz_epoch"])
    assert client.get("/api/v1/me").status_code == 401

    client = Client()
    sign_in(client, applicant, clock)
    applicant.disable(clock.now())
    applicant.save()
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.django_db
def test_logout_requires_csrf_and_flushes_the_session(
    applicant: Principal, clock: FrozenClock
) -> None:
    client = Client(enforce_csrf_checks=True)
    sign_in(client, applicant, clock)
    token = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]

    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/me").status_code == 200

    response = client.post("/api/v1/auth/logout", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 204
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.django_db
def test_me_projection_for_staff_lists_only_granted_workspaces(
    staff: Principal, clock: FrozenClock
) -> None:
    client = Client()
    sign_in(client, staff, clock)
    body = client.get("/api/v1/me").json()["data"]
    assert (
        body["kind"] == "STAFF"
        and body["workspaces"] == []
        and body["active_workspace"] == "public"
    )
    assert body["feature_gates"]["service_mode"] == "DEMO"
