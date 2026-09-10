"""API-122 readiness against a real PostgreSQL test database (deployment s.3).

Requires DATABASE_URL pointing at a reachable PostgreSQL server; pytest-django creates the
dedicated test database named by TEST_DATABASE_NAME.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse

from agni.platform import health


@pytest.mark.django_db
def test_ready_reports_pass_for_every_check(anonymous_client: Client) -> None:
    response = anonymous_client.get(reverse("api:health-ready"))
    body: dict[str, Any] = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "pass", "schema": "pass", "configuration": "pass"}
    assert body["service_mode"] in {"DEMO", "LIVE"}
    # No environment or credential dump.
    assert set(body) == {"status", "checks", "service_mode"}


@pytest.mark.django_db
def test_ready_returns_503_when_database_is_unavailable(anonymous_client: Client) -> None:
    with mock.patch.object(health, "_database_ready", return_value=False):
        response = anonymous_client.get(reverse("api:health-ready"))
    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "fail"
    assert body["checks"]["schema"] == "fail"


@pytest.mark.django_db
def test_ready_returns_503_when_migrations_are_pending(anonymous_client: Client) -> None:
    with mock.patch.object(health, "_schema_ready", return_value=False):
        response = anonymous_client.get(reverse("api:health-ready"))
    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": "pass",
        "schema": "fail",
        "configuration": "pass",
    }


def test_database_probe_swallows_database_errors_only() -> None:
    with mock.patch("agni.platform.health.connection") as connection:
        connection.cursor.side_effect = DatabaseError("boom")
        assert health._database_ready() is False
