"""API-010..013 premises endpoints with real sessions, CSRF, idempotency and If-Match."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Premises
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.platform.models import CommandReceipt

VALID: dict[str, Any] = {
    "display_name": "Demo Mall",
    "address_line1": "12 Market Street",
    "locality": "Demo Nagar",
    "ward_key": "W-07",
    "postal_code": "560002",
    "category_key": "Office",
    "area_sqm": "4500.00",
    "height_m": "18.50",
    "floor_count": 4,
    "occupancy_count": 800,
}


@pytest.mark.django_db
def test_premises_crud_with_idempotency_and_preconditions(
    applicant: Principal,
    other_applicant: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    key = str(uuid4())
    created = client.post(
        "/api/v1/premises",
        data=VALID,
        content_type="application/json",
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 201, created.content
    body = created.json()["data"]
    premises_id = body["premises_id"]
    assert body["replayed"] is False and created["ETag"] == f'"premises:{premises_id}:v1"'

    replay = client.post(
        "/api/v1/premises",
        data=VALID,
        content_type="application/json",
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201 and replay.json()["data"]["replayed"] is True
    assert Premises.objects.count() == 1 and CommandReceipt.objects.count() == 1

    conflict = client.post(
        "/api/v1/premises",
        data={**VALID, "display_name": "Other"},
        content_type="application/json",
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    no_key = client.post("/api/v1/premises", data=VALID, content_type="application/json")
    assert no_key.status_code == 400 and no_key.json()["code"] == "MALFORMED_REQUEST"

    listing = client.get("/api/v1/premises").json()["data"]
    assert [p["premises_id"] for p in listing["items"]] == [premises_id]
    detail = client.get(f"/api/v1/premises/{premises_id}")
    assert detail.status_code == 200 and detail["ETag"] == f'"premises:{premises_id}:v1"'

    patch_no_precondition = client.patch(
        f"/api/v1/premises/{premises_id}",
        data={"display_name": "Demo Mall East"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert patch_no_precondition.status_code == 428
    patched = client.patch(
        f"/api/v1/premises/{premises_id}",
        data={"display_name": "Demo Mall East"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4()), "If-Match": detail["ETag"]},
    )
    assert patched.status_code == 200 and patched["ETag"] == f'"premises:{premises_id}:v2"'
    stale = client.patch(
        f"/api/v1/premises/{premises_id}",
        data={"display_name": "Again"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4()), "If-Match": detail["ETag"]},
    )
    assert stale.status_code == 412 and stale.json()["current_version"] == 2
    bad = client.patch(
        f"/api/v1/premises/{premises_id}",
        data={"owner_id": str(other_applicant.pk), "area_sqm": "0"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4()), "If-Match": patched["ETag"]},
    )
    assert bad.status_code == 422 and {v["pointer"] for v in bad.json()["violations"]} >= {
        "/owner_id",
        "/area_sqm",
    }

    # AT-03-04: another applicant sees nothing and cannot edit; same response as nonexistent.
    other = signed_client(other_applicant)
    assert other.get("/api/v1/premises").json()["data"]["items"] == []
    assert other.get(f"/api/v1/premises/{premises_id}").status_code == 404
    assert (
        other.patch(
            f"/api/v1/premises/{premises_id}",
            data={"display_name": "Hijack"},
            content_type="application/json",
            headers={"Idempotency-Key": str(uuid4()), "If-Match": patched["ETag"]},
        ).status_code
        == 404
    )
    assert Premises.objects.get(pk=premises_id).display_name == "Demo Mall East"


@pytest.mark.django_db
def test_anonymous_premises_access_is_refused(anonymous_client: Client) -> None:
    assert anonymous_client.get("/api/v1/premises").status_code == 401
    # Unauthenticated writes are refused before any command runs; nothing is persisted.
    assert (
        anonymous_client.post(
            "/api/v1/premises", data=VALID, content_type="application/json"
        ).status_code
        == 401
    )
    assert Premises.objects.count() == 0
