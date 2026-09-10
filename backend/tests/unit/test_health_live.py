"""API-121 liveness: answers without touching the database and never dumps configuration."""

from __future__ import annotations

from django.test import Client
from django.urls import reverse


def test_live_returns_ok_without_database(anonymous_client: Client) -> None:
    response = anonymous_client.get(reverse("api:health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_rejects_unsafe_methods(anonymous_client: Client) -> None:
    response = anonymous_client.post(reverse("api:health-live"))
    assert response.status_code == 405


def test_health_routes_live_under_api_v1() -> None:
    assert reverse("api:health-live") == "/api/v1/health/live"
    assert reverse("api:health-ready") == "/api/v1/health/ready"
