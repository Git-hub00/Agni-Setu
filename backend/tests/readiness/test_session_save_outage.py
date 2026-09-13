"""OPS-1188 / invariant 31 - the database disappears while the session row is being saved at the
end of a request (observed live on 2026-09-12 when PostgreSQL crashed during an OTP sign-in). The
answer must be the uniform 503 DEPENDENCY_UNAVAILABLE problem with a small body - never a 400
"malformed request" - while a genuine concurrent logout keeps its 400."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.backends.db import SessionStore
from django.db import DatabaseError, OperationalError
from django.test import Client

from agni.identity.models import Principal
from agni.platform.session_middleware import connection_level_failure


def _lost_connection(self: SessionStore, must_create: bool = False) -> None:
    # Mirrors django.contrib.sessions.backends.db.SessionStore.save: the backend converts the
    # DatabaseError into UpdateError from inside the except block, so the chain is preserved.
    try:
        raise OperationalError("consuming input failed: server closed the connection unexpectedly")
    except OperationalError:
        raise UpdateError from None


def _connection_gone(self: SessionStore, must_create: bool = False) -> None:
    # PostgreSQL in crash recovery (observed live 2026-09-13 02:11Z): the session row cannot even
    # be loaded or saved because connecting fails. Django wraps the driver error in
    # django.db.OperationalError and nothing converts it to UpdateError, so it escapes
    # process_response. With DEBUG on (the dev stack) Django then renders its technical 500 page;
    # with production settings the `handler500` fallback (`fallbacks.server_error`) must turn it
    # into the same 503 problem. This test pins that production contract.
    raise OperationalError(
        'connection failed: connection to server at "db", port 5432 failed: '
        "FATAL:  the database system is in recovery mode"
    )


def _row_gone(self: SessionStore, must_create: bool = False) -> None:
    try:
        raise DatabaseError("Forced update did not affect any rows.")
    except DatabaseError:
        raise UpdateError from None


def _browser(client: Client) -> Client:
    browser = Client(enforce_csrf_checks=True, raise_request_exception=False)
    browser.cookies["sessionid"] = client.cookies["sessionid"].value
    browser.cookies["csrftoken"] = client.cookies["csrftoken"].value
    browser.defaults["HTTP_X_CSRFTOKEN"] = client.defaults["HTTP_X_CSRFTOKEN"]
    return browser


def test_connection_level_failures_are_recognised_through_the_chain() -> None:
    try:
        try:
            raise OperationalError("lost")
        except OperationalError:
            raise UpdateError from None
    except UpdateError as exc:
        assert connection_level_failure(exc) is True
    try:
        try:
            raise DatabaseError("Forced update did not affect any rows.")
        except DatabaseError:
            raise UpdateError from None
    except UpdateError as exc:
        assert connection_level_failure(exc) is False
    assert connection_level_failure(UpdateError()) is False


@pytest.mark.django_db
def test_database_loss_during_session_save_is_a_503_problem(
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(signed_client(applicant))
    # The view itself succeeds; the session save at the end of the request hits the lost database.
    monkeypatch.setattr(SessionStore, "save", _lost_connection)
    response: Any = browser.get("/api/v1/me")
    assert response.status_code == 503, (response.status_code, response.content[:300])
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE" and body["request_id"]
    assert response["Retry-After"] == "30"
    assert len(response.content) < 2048
    assert b"Traceback" not in response.content and b"deleted" not in response.content


@pytest.mark.django_db
def test_connection_loss_during_session_save_is_a_503_problem(
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(signed_client(applicant))
    monkeypatch.setattr(SessionStore, "save", _connection_gone)
    response: Any = browser.get("/api/v1/me")
    assert response.status_code == 503, (response.status_code, response.content[:300])
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE" and body["request_id"]
    assert response["Retry-After"] == "30"
    assert len(response.content) < 2048
    assert b"Traceback" not in response.content and b"recovery mode" not in response.content


@pytest.mark.django_db
def test_concurrent_logout_during_session_save_stays_a_small_400(
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(signed_client(applicant))
    monkeypatch.setattr(SessionStore, "save", _row_gone)
    response: Any = browser.get("/api/v1/me")
    assert response.status_code == 400, (response.status_code, response.content[:300])
    body = response.json()
    assert body["code"] == "MALFORMED_REQUEST" and body["request_id"]
    assert len(response.content) < 2048
    assert b"Traceback" not in response.content
