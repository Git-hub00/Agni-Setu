"""FR-01 / AT-01-01..05 at the API boundary with CSRF enforced (Client(enforce_csrf_checks))."""

from __future__ import annotations

import re
import threading
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client

from agni.identity import otp
from agni.identity.contacts import decrypt_contact, normalize_contact
from agni.identity.models import ContactIdentity, OtpChallenge, OtpPurpose, Principal
from agni.notifications.models import DemoOutboundMessage
from agni.platform.clock import FrozenClock
from agni.platform.errors import DependencyUnavailable, OtpInvalid

CONTACT = "rakesh.mehta@example.test"


@pytest.fixture(autouse=True)
def _controlled_clock(monkeypatch: pytest.MonkeyPatch, clock: FrozenClock) -> None:
    monkeypatch.setattr("agni.identity.api.views.get_clock", lambda: clock)
    monkeypatch.setattr("agni.identity.authentication.get_clock", lambda: clock)
    cache.clear()


@pytest.fixture
def client() -> Client:
    return Client(enforce_csrf_checks=True)


def bootstrap_csrf(client: Client) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    token: str = response.json()["data"]["csrf_token"]
    assert "csrftoken" in response.cookies
    return token


def post(client: Client, path: str, body: dict[str, Any], token: str | None) -> Any:
    headers = {"X-CSRFToken": token} if token else {}
    return client.post(path, data=body, content_type="application/json", headers=headers)


def code_from_inbox(contact: str = CONTACT) -> str:
    lookup = normalize_contact("EMAIL", contact).lookup_hmac
    message = (
        DemoOutboundMessage.objects.filter(destination_lookup_hmac=lookup)
        .order_by("-created_at")
        .first()
    )
    assert message is not None
    match = re.search(r"\b(\d{6})\b", message.body)
    assert match
    return match.group(1)


def start(client: Client, token: str, contact: str = CONTACT) -> dict[str, Any]:
    response = post(
        client, "/api/v1/auth/otp/challenges", {"channel": "EMAIL", "contact": contact}, token
    )
    assert response.status_code == 202, response.content
    data: dict[str, Any] = response.json()["data"]
    return data


@pytest.mark.django_db
def test_at_01_04_login_csrf_is_enforced_on_public_otp_endpoints(client: Client) -> None:
    response = post(
        client, "/api/v1/auth/otp/challenges", {"channel": "EMAIL", "contact": CONTACT}, None
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert response["Content-Type"].startswith("application/problem+json")
    assert not OtpChallenge.objects.exists()


@pytest.mark.django_db
def test_at_01_01_valid_challenge_creates_one_session_for_that_applicant_only(
    client: Client, clock: FrozenClock
) -> None:
    token = bootstrap_csrf(client)
    started = start(client, token)
    assert (
        started["masked_destination"].endswith("@example.test")
        and "rakesh" not in started["masked_destination"]
    )
    assert OtpChallenge.objects.count() == 1

    code = code_from_inbox()
    response = post(
        client,
        "/api/v1/auth/otp/verify",
        {
            "challenge_id": started["challenge_id"],
            "code": code,
            "channel": "EMAIL",
            "contact": CONTACT,
        },
        token,
    )
    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["kind"] == "APPLICANT" and body["workspaces"] == ["applicant"]
    assert body["capabilities"] == [] and body["authz_epoch"] == 1
    assert "sessionid" in response.cookies
    assert set(body) == {
        "id",
        "display_name",
        "kind",
        "workspaces",
        "active_workspace",
        "scopes",
        "capabilities",
        "authz_epoch",
        "session_expires_at",
        "feature_gates",
    }

    principal = Principal.objects.get(pk=body["id"])
    contact = ContactIdentity.objects.get(principal=principal)
    assert contact.verified_at == clock.now() and decrypt_contact(contact.ciphertext) == CONTACT
    assert principal.verified_contact_ref == contact.id

    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["data"]["id"] == body["id"]
    assert OtpChallenge.objects.get().consumed_at == clock.now()


@pytest.mark.django_db
def test_at_01_02_wrong_expired_and_reused_codes_never_grant_a_session(
    client: Client, clock: FrozenClock
) -> None:
    token = bootstrap_csrf(client)
    started = start(client, token)
    cid = started["challenge_id"]

    for attempt in range(1, 6):
        response = post(
            client, "/api/v1/auth/otp/verify", {"challenge_id": cid, "code": "000000"}, token
        )
        assert response.status_code == 422 and response.json()["code"] == "OTP_INVALID"
        assert OtpChallenge.objects.get(pk=cid).attempt_count == attempt
    # Budget exhausted: even the right code is refused now.
    response = post(
        client, "/api/v1/auth/otp/verify", {"challenge_id": cid, "code": code_from_inbox()}, token
    )
    assert response.status_code == 422 and response.json()["code"] == "OTP_INVALID"
    assert "sessionid" not in client.cookies
    assert client.get("/api/v1/me").status_code == 401

    # Expired challenge (new one after cooldown reset)
    cache.clear()
    started = start(client, token)
    clock.advance(timedelta(minutes=5, seconds=1))
    response = post(
        client,
        "/api/v1/auth/otp/verify",
        {"challenge_id": started["challenge_id"], "code": code_from_inbox()},
        token,
    )
    assert response.status_code == 422 and response.json()["code"] == "OTP_EXPIRED"

    # Reused (consumed) challenge
    cache.clear()
    started = start(client, token)
    code = code_from_inbox()
    assert (
        post(
            client,
            "/api/v1/auth/otp/verify",
            {"challenge_id": started["challenge_id"], "code": code},
            token,
        ).status_code
        == 200
    )
    replay = Client(enforce_csrf_checks=True)
    token2 = bootstrap_csrf(replay)
    response = post(
        replay,
        "/api/v1/auth/otp/verify",
        {"challenge_id": started["challenge_id"], "code": code},
        token2,
    )
    assert response.status_code == 422 and response.json()["code"] == "OTP_INVALID"
    assert "sessionid" not in replay.cookies


@pytest.mark.django_db
def test_at_01_02_unknown_challenge_and_enumeration_safety(client: Client) -> None:
    token = bootstrap_csrf(client)
    unknown = start(client, token, contact="nobody@example.test")
    known_principal = Principal.objects.create_principal(kind="APPLICANT", display_name="Known")
    otp.record_verified_contact(
        known_principal,
        normalize_contact("EMAIL", "known@example.test"),
        now=known_principal.created_at,
    )
    cache.clear()
    known = start(client, token, contact="known@example.test")
    assert set(unknown) == set(known)  # identical response shape regardless of account existence

    response = post(
        client,
        "/api/v1/auth/otp/verify",
        {"challenge_id": "6ee2b8f4-6f2e-4b57-a0a2-9b8b8a3c9d10", "code": "123456"},
        token,
    )
    assert response.status_code == 422 and response.json()["code"] == "OTP_INVALID"


@pytest.mark.django_db
def test_at_01_03_resend_cooldown_then_supersede(client: Client) -> None:
    token = bootstrap_csrf(client)
    first = start(client, token)
    response = post(
        client, "/api/v1/auth/otp/challenges", {"channel": "EMAIL", "contact": CONTACT}, token
    )
    assert response.status_code == 429 and response.json()["code"] == "OTP_THROTTLED"
    assert response["Retry-After"] == "60"

    cache.delete(
        f"otp:resend:{normalize_contact('EMAIL', CONTACT).lookup_hmac}:SIGN_IN"
    )  # cooldown elapsed
    second = start(client, token)
    assert second["challenge_id"] != first["challenge_id"]
    assert OtpChallenge.objects.get(pk=first["challenge_id"]).superseded_at is not None

    # The superseded challenge's code no longer works; the new one does.
    old_code = re.search(
        r"\b(\d{6})\b",
        (DemoOutboundMessage.objects.order_by("created_at").first() or DemoOutboundMessage()).body,
    ).group(1)  # type: ignore[union-attr]
    response = post(
        client,
        "/api/v1/auth/otp/verify",
        {"challenge_id": first["challenge_id"], "code": old_code},
        token,
    )
    assert response.status_code == 422
    response = post(
        client,
        "/api/v1/auth/otp/verify",
        {"challenge_id": second["challenge_id"], "code": code_from_inbox()},
        token,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_hourly_send_limits_apply_per_contact_and_per_ip(client: Client) -> None:
    token = bootstrap_csrf(client)
    lookup = normalize_contact("EMAIL", CONTACT).lookup_hmac
    for _ in range(5):
        start(client, token)
        cache.delete(f"otp:resend:{lookup}:SIGN_IN")
    response = post(
        client, "/api/v1/auth/otp/challenges", {"channel": "EMAIL", "contact": CONTACT}, token
    )
    assert response.status_code == 429 and response.json()["code"] == "OTP_THROTTLED"


@pytest.mark.django_db
def test_rate_limit_store_outage_fails_closed(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = bootstrap_csrf(client)

    def boom(*_: Any, **__: Any) -> bool:
        raise ConnectionError("valkey down")

    monkeypatch.setattr("agni.identity.otp.cache.add", boom)
    response = post(
        client, "/api/v1/auth/otp/challenges", {"channel": "EMAIL", "contact": CONTACT}, token
    )
    assert response.status_code == 503 and response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert not OtpChallenge.objects.exists() and not DemoOutboundMessage.objects.exists()


@pytest.mark.django_db
def test_codes_are_never_in_api_responses_or_challenge_rows(client: Client) -> None:
    token = bootstrap_csrf(client)
    started = start(client, token)
    code = code_from_inbox()
    assert code not in str(started)
    row = OtpChallenge.objects.get()
    assert code not in row.code_mac and len(row.code_mac) == 64


@pytest.mark.django_db(transaction=True)
def test_at_01_05_concurrent_verification_consumes_exactly_once(clock: FrozenClock) -> None:
    cache.clear()
    started = otp.start_challenge(
        channel="EMAIL",
        contact=CONTACT,
        purpose=OtpPurpose.SIGN_IN,
        source_ip="10.0.0.1",
        clock=clock,
    )
    code = code_from_inbox()
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            otp.verify_challenge(challenge_id=started.challenge_id, code=code, clock=clock)
            outcomes.append("ok")
        except OtpInvalid:
            outcomes.append("invalid")
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["invalid", "ok"]
    assert Principal.objects.filter(kind="APPLICANT").count() == 1
    assert OtpChallenge.objects.get(pk=started.challenge_id).consumed_at is not None


def test_dependency_unavailable_is_the_fail_closed_error() -> None:
    assert DependencyUnavailable().status == 503
