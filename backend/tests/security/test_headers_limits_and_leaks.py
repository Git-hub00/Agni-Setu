"""Response headers, cookie flags, request limits, stored-XSS neutrality, CSRF on business
commands, verification rate limiting and secret/OTP leakage into logs (security s.4, s.9,
s.10)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client

from agni.identity.contacts import normalize_contact
from agni.identity.models import Principal
from agni.notifications.models import DemoOutboundMessage
from agni.platform.clock import FrozenClock
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture import
from tests.integration.test_submission import cmd

JSON = "application/json"
CONTACT = "security.drill@example.test"
XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'


@pytest.fixture(autouse=True)
def _controlled_clock(monkeypatch: pytest.MonkeyPatch, clock: FrozenClock) -> None:
    monkeypatch.setattr("agni.identity.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.identity.authentication.get_clock", lambda: clock)
    cache.clear()


def _sign_in_over_http(client: Client) -> tuple[Any, str]:
    token = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    started = client.post(
        "/api/v1/auth/otp/challenges",
        data={"channel": "EMAIL", "contact": CONTACT},
        content_type=JSON,
        headers=headers,
    )
    assert started.status_code == 202, started.content
    lookup = normalize_contact("EMAIL", CONTACT).lookup_hmac
    message = DemoOutboundMessage.objects.filter(destination_lookup_hmac=lookup).latest(
        "created_at"
    )
    match = re.search(r"\b(\d{6})\b", message.body)
    assert match
    code = match.group(1)
    verified = client.post(
        "/api/v1/auth/otp/verify",
        data={
            "challenge_id": started.json()["data"]["challenge_id"],
            "code": code,
            "channel": "EMAIL",
            "contact": CONTACT,
        },
        content_type=JSON,
        headers=headers,
    )
    assert verified.status_code == 200, verified.content
    return verified, code


@pytest.mark.django_db
def test_api_responses_carry_the_security_headers_and_no_store(
    visit: dict[str, Any],  # noqa: F811
) -> None:
    owner = visit["applicant"]
    me = owner.get("/api/v1/me")
    assert me.status_code == 200
    assert me["Content-Security-Policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in me["Content-Security-Policy"]
    assert me["X-Content-Type-Options"] == "nosniff"
    assert me["X-Frame-Options"] == "DENY"
    assert me["Referrer-Policy"] == "same-origin"
    assert "camera=()" in me["Permissions-Policy"]
    assert me["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "no-store" in me["Cache-Control"]
    case = owner.get(f"/api/v1/applications/{visit['app_id']}")
    assert "no-store" in case["Cache-Control"]
    # Public and error responses carry the same policy headers.
    anonymous = Client()
    ready = anonymous.get("/api/v1/health/ready")
    assert ready["X-Content-Type-Options"] == "nosniff" and "Content-Security-Policy" in ready
    missing = anonymous.get("/api/v1/applications")
    assert missing.status_code == 401 and missing["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
def test_session_cookie_flags_and_login_csrf(caplog: pytest.LogCaptureFixture) -> None:
    client = Client(enforce_csrf_checks=True)
    with caplog.at_level(logging.DEBUG):
        verified, code = _sign_in_over_http(client)
    cookie = verified.cookies["sessionid"]
    assert cookie["httponly"] and cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    # The one-time code appears in no response and in no log line.
    assert code not in verified.content.decode()
    assert code not in caplog.text
    # A business command without the CSRF header is refused even with a valid session.
    plain = Client(enforce_csrf_checks=True)
    plain.cookies["sessionid"] = cookie.value
    refused = plain.post(
        "/api/v1/tickets",
        data={"category": "HOW_TO", "subject": "csrf drill", "description": "x" * 12},
        content_type=JSON,
        headers={"Idempotency-Key": "csrf-drill"},
    )
    assert refused.status_code == 403 and refused.json()["code"] == "CSRF_FAILED"
    # Sign-in without the CSRF token is refused too (login CSRF).
    fresh = Client(enforce_csrf_checks=True)
    assert (
        fresh.post(
            "/api/v1/auth/otp/challenges",
            data={"channel": "EMAIL", "contact": CONTACT},
            content_type=JSON,
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_oversized_json_bodies_are_refused_before_any_handler(
    visit: dict[str, Any],  # noqa: F811
    settings: Any,
) -> None:
    owner = visit["applicant"]
    huge = "x" * (settings.API_MAX_JSON_BODY_BYTES + 1024)
    response = owner.post(
        "/api/v1/tickets",
        data={"category": "HOW_TO", "subject": "big", "description": huge},
        content_type=JSON,
        headers=cmd(),
    )
    assert response.status_code == 413, response.status_code
    body = response.json()
    assert (
        body["code"] == "MALFORMED_REQUEST"
        and body["max_bytes"] == settings.API_MAX_JSON_BODY_BYTES
    )
    assert response["Content-Type"].startswith("application/problem+json")
    assert response["Content-Security-Policy"].startswith("default-src 'none'")
    # The file transfer endpoint is exempt from the JSON cap (bounded by its reservation).
    reserved = owner.post(
        "/api/v1/uploads",
        data={
            "target_type": "APPLICATION_DRAFT",
            "target_id": visit["app_id"],
            "original_name": "x.pdf",
            "media_type": "application/pdf",
            "size_bytes": 10,
            "sha256": "0" * 64,
            "requirement_code": "ownership",
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert reserved.status_code in (201, 409, 422)  # state-dependent; the cap never bites here


@pytest.mark.django_db
def test_user_text_is_stored_and_returned_as_data_never_as_markup(
    visit: dict[str, Any],  # noqa: F811
) -> None:
    owner = visit["applicant"]
    created = owner.post(
        "/api/v1/tickets",
        data={
            "category": "TECHNICAL",
            "subject": XSS[:160],
            "description": f"{XSS} and a very ordinary description of a problem.",
            "application_id": visit["app_id"],
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert created.status_code == 201, created.content
    ticket_id = created.json()["data"]["ticket_id"]
    fetched = owner.get(f"/api/v1/tickets/{ticket_id}")
    assert fetched["Content-Type"].startswith("application/json")
    assert fetched["X-Content-Type-Options"] == "nosniff"
    body = fetched.json()["data"]
    assert body["subject"] == XSS[:160]  # exact string, no server-side HTML interpretation
    raw = fetched.content.decode()
    assert "<script>" not in raw  # JSON escapes the tag characters on the wire
    assert "\\u003cscript\\u003e" in raw or "\\u003c" in raw
    staff = visit["boss"].get(f"/api/v1/tickets/{ticket_id}")
    assert staff.status_code == 200 and staff.json()["data"]["subject"] == XSS[:160]


@pytest.mark.django_db
# Cases: AT-22-04 (anonymous lookups are throttled per client; no enumeration)
def test_public_verification_is_rate_limited_per_client(settings: Any) -> None:
    client = Client()
    limit = int(settings.PUBLIC_VERIFY_RATE_LIMIT)
    statuses = [
        client.get("/api/v1/public/certificates/AGNI-NOPE-1").status_code for _ in range(limit)
    ]
    assert set(statuses) == {404}
    throttled = client.get("/api/v1/public/certificates/AGNI-NOPE-1")
    assert throttled.status_code == 429 and throttled.json()["code"] == "RATE_LIMITED"
    assert throttled["Retry-After"]
    assert throttled["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_problem_responses_never_echo_secrets_or_stack_traces(
    visit: dict[str, Any],  # noqa: F811
    signed_client: Callable[[Principal], Client],
    governance_actors: dict[str, Principal],
    settings: Any,
) -> None:
    admin = signed_client(governance_actors["admin"])
    listing = admin.get("/api/v1/integrations").content.decode()
    for secret in settings.INTEGRATION_DEMO_SECRETS.values():
        assert secret not in listing
    assert settings.SECRET_KEY not in listing
    broken = visit["applicant"].post(
        "/api/v1/tickets", data="{not json", content_type=JSON, headers=cmd()
    )
    assert broken.status_code == 400
    text = broken.content.decode()
    assert "Traceback" not in text and 'File "' not in text
    assert broken.json()["code"] == "MALFORMED_REQUEST"
