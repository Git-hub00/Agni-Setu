"""SEC-1096..1098 / G-05 - the costly endpoints are rate limited per principal: over the limit
answers 429 RATE_LIMITED with Retry-After, other principals and other endpoints are unaffected,
and an outage of the rate-limit store fails closed (503), never open and never 500."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings

from agni.cases.models import Premises
from agni.identity.models import Principal
from agni.platform.api.throttles import FailClosedScopedRateThrottle
from agni.policies.models import Service
from tests.integration.test_drafts import create_draft
from tests.integration.test_submission import cmd

JSON = "application/json"
TIGHT_RATES = {"search": "3/min", "upload-reserve": "2/min", "export-request": "1/min"}
TIGHT = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": TIGHT_RATES}


@pytest.fixture(autouse=True)
def _clean_throttle_history() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@override_settings(REST_FRAMEWORK=TIGHT)
@pytest.mark.django_db
def test_search_is_limited_per_principal_with_retry_guidance(
    applicant: Principal,
    other_applicant: Principal,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    for _ in range(3):
        assert client.get("/api/v1/applications", {"q": "demo"}).status_code == 200
    limited = client.get("/api/v1/applications", {"q": "demo"})
    assert limited.status_code == 429, limited.content
    body = limited.json()
    assert body["code"] == "RATE_LIMITED" and body["request_id"]
    assert int(limited["Retry-After"]) >= 1 and body["retry_after_seconds"] >= 1
    # Another principal keeps its own budget; endpoints without a scope are untouched.
    assert signed_client(other_applicant).get("/api/v1/applications").status_code == 200
    for _ in range(5):
        assert client.get("/api/v1/me").status_code == 200


@override_settings(REST_FRAMEWORK=TIGHT)
@pytest.mark.django_db
def test_upload_reservations_and_export_requests_are_limited(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    app_id = create_draft(client, premises, service).json()["data"]["application_id"]
    reservation = {
        "target_type": "APPLICATION_DRAFT",
        "target_id": app_id,
        "original_name": "plan.pdf",
        "media_type": "application/pdf",
        "size_bytes": 10,
        "requirement_code": "plan",
    }
    codes = [
        client.post(
            "/api/v1/uploads", data=reservation, content_type=JSON, headers=cmd()
        ).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429], codes
    export = {"kind": "CASES", "field_set_key": "case-summary", "purpose": "Throttle probe export."}
    first = client.post("/api/v1/exports", data=export, content_type=JSON, headers=cmd())
    second = client.post("/api/v1/exports", data=export, content_type=JSON, headers=cmd())
    assert first.status_code == 202, first.content
    assert second.status_code == 429 and second.json()["code"] == "RATE_LIMITED"


class _DownStore:
    def get(self, key: str, default: Any = None) -> Any:
        raise ConnectionError("valkey down (fault drill)")

    def set(self, key: str, value: Any, timeout: Any = None) -> None:
        raise ConnectionError("valkey down (fault drill)")


@pytest.mark.django_db
def test_rate_limit_store_outage_fails_closed_as_503(
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = signed_client(applicant)
    monkeypatch.setattr(FailClosedScopedRateThrottle, "cache", _DownStore())
    response = client.get("/api/v1/applications")
    assert response.status_code == 503, response.content
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE" and response["Retry-After"] == "30"
    assert b"Traceback" not in response.content
    # Routes without a throttle scope do not depend on the store at all.
    assert client.get("/api/v1/me").status_code == 200
