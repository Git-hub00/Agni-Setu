"""FR-04 / AT-04-01..05: server drafts, autosave with version preconditions, stale-tab conflict
and recovery, scope (other applicant, delegate, staff) and replay."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, DraftRevision, Premises
from agni.identity.models import Delegation, Principal
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent
from agni.policies.models import Service

JSON = "application/json"


def create_draft(
    client: Client, premises: Premises, service: Service, key: str | None = None
) -> Any:
    response = client.post(
        "/api/v1/applications",
        data={"premises_id": str(premises.pk), "service_id": str(service.pk)},
        content_type=JSON,
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == 201, response.content
    return response


def patch_draft(
    client: Client, app_id: str, etag: str, body: dict[str, Any], key: str | None = None
) -> Any:
    return client.patch(
        f"/api/v1/applications/{app_id}/draft",
        data=body,
        content_type=JSON,
        headers={"Idempotency-Key": key or str(uuid4()), "If-Match": etag},
    )


@pytest.mark.django_db
def test_at_04_01_draft_is_prefilled_saved_and_preserved_on_reload(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    created = create_draft(client, premises, service)
    app_id = created.json()["data"]["application_id"]
    assert created["ETag"] == f'"application:{app_id}:v1"'

    detail = client.get(f"/api/v1/applications/{app_id}")
    body = detail.json()["data"]
    assert body["status"] == "DRAFT" and body["draft"]["draft_revision"] == 1
    assert body["draft"]["fields"]["display_name"] == premises.display_name
    assert body["draft"]["fields"]["application_type"] == "NEW"
    assert body["draft"]["form_schema_ref"] == "premises-v1#1"
    codes = {r["code"]: r for r in body["draft"]["requirements"]}
    assert {"ownership", "plan", "electrical"} <= set(codes)  # WAREHOUSE: base documents only
    assert all(r["status"] == "MISSING" for r in codes.values())
    assert body["policy"]["policy_number"] == 1
    submit = next(a for a in body["allowed_actions"] if a["key"] == "submit")
    assert submit["enabled"] is False and submit["reason_code"] == "DRAFT_INCOMPLETE"
    assert {"code": "DECLARATION_MISSING", "pointer": "/declaration_drafts/D01"} in body["draft"][
        "blockers"
    ]

    saved = patch_draft(
        client,
        app_id,
        detail["ETag"],
        {
            "draft_revision": 1,
            "fields": {"category_key": "Hospital", "beneficiary_name": "Asha Applicant"},
            "declaration_drafts": [{"code": "D01", "version": "1", "accepted": True}],
        },
    )
    assert saved.status_code == 200, saved.content
    data = saved.json()["data"]
    assert data["draft_revision"] == 2 and saved["ETag"] == f'"application:{app_id}:v2"'
    assert data["fields"]["category_key"] == "Hospital"
    assert data["fields"]["display_name"] == premises.display_name  # untouched fields preserved
    # Requirements follow the declared category: a hospital now needs the evacuation plan.
    assert "evacuation" in {r["code"] for r in data["requirements"] if r["required"]}

    reloaded = client.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert reloaded["draft"]["fields"]["category_key"] == "Hospital"
    assert reloaded["draft"]["declaration_drafts"] == [
        {"code": "D01", "version": "1", "accepted": True}
    ]
    assert DraftRevision.objects.filter(application_id=app_id).count() == 2
    assert Application.objects.get(pk=app_id).status == "DRAFT"  # saving never transitions
    assert (
        AuditEvent.objects.filter(entity_id=app_id, action="application.draft_saved").count() == 1
    )


@pytest.mark.django_db
def test_at_04_02_03_stale_second_tab_conflicts_then_recovers(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
) -> None:
    tab_a, tab_b = signed_client(applicant), signed_client(applicant)
    app_id = create_draft(tab_a, premises, service).json()["data"]["application_id"]
    etag_v1 = tab_a.get(f"/api/v1/applications/{app_id}")["ETag"]

    first = patch_draft(
        tab_a, app_id, etag_v1, {"draft_revision": 1, "fields": {"locality": "Karol Bagh"}}
    )
    assert first.status_code == 200
    # Tab B still holds revision 1 / version 1 and tries to save a different field.
    stale = patch_draft(
        tab_b, app_id, etag_v1, {"draft_revision": 1, "fields": {"locality": "Elsewhere"}}
    )
    assert stale.status_code == 412
    problem = stale.json()
    assert problem["code"] == "VERSION_CONFLICT" and problem["current_version"] == 2
    current = DraftRevision.objects.get(application_id=app_id, revision_number=2)
    assert current.editable_payload["fields"]["locality"] == "Karol Bagh"

    # Even with a fresh If-Match, a stale draft revision is refused with the current fields.
    stale_rev = patch_draft(
        tab_b, app_id, first["ETag"], {"draft_revision": 1, "fields": {"locality": "Elsewhere"}}
    )
    assert stale_rev.status_code == 412
    assert stale_rev.json()["current_draft_revision"] == 2
    assert stale_rev.json()["current_fields"]["locality"] == "Karol Bagh"

    # Recovery: reapply the chosen edit against the current revision with a new command key.
    retry_key = str(uuid4())
    reapplied = patch_draft(
        tab_b,
        app_id,
        first["ETag"],
        {"draft_revision": 2, "fields": {"locality": "Elsewhere"}},
        key=retry_key,
    )
    assert reapplied.status_code == 200 and reapplied.json()["data"]["draft_revision"] == 3
    # An ambiguous save retried with its original key replays instead of creating revision 4.
    replay = patch_draft(
        tab_b,
        app_id,
        first["ETag"],
        {"draft_revision": 2, "fields": {"locality": "Elsewhere"}},
        key=retry_key,
    )
    assert replay.status_code == 200 and replay.json()["data"]["replayed"] is True
    assert DraftRevision.objects.filter(application_id=app_id).count() == 3


@pytest.mark.django_db
def test_draft_patch_validation_pointers(
    applicant: Principal,
    premises: Premises,
    service: Service,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    created = create_draft(client, premises, service)
    app_id = created.json()["data"]["application_id"]
    bad = patch_draft(
        client,
        app_id,
        created["ETag"],
        {
            "draft_revision": 1,
            "status": "SUBMITTED",
            "fields": {"postal_code": "12", "application_type": "MAGIC", "colour": "red"},
            "declaration_drafts": [{"code": "D99", "version": "1", "accepted": True}],
            "attachment_links": [str(uuid4())],
        },
    )
    assert bad.status_code == 422, bad.content
    pointers = {v["pointer"] for v in bad.json()["violations"]}
    assert {
        "/status",
        "/fields/postal_code",
        "/fields/application_type",
        "/fields/colour",
        "/declaration_drafts/0/code",
        "/attachment_links/0",
    } <= pointers
    assert Application.objects.get(pk=app_id).status == "DRAFT"
    assert DraftRevision.objects.filter(application_id=app_id).count() == 1


@pytest.mark.django_db
def test_at_04_04_scope_other_applicant_staff_and_delegate(
    applicant: Principal,
    other_applicant: Principal,
    staff: Principal,
    premises: Premises,
    service: Service,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    owner = signed_client(applicant)
    created = create_draft(owner, premises, service)
    app_id = created.json()["data"]["application_id"]

    stranger = signed_client(other_applicant)
    assert stranger.get(f"/api/v1/applications/{app_id}").status_code == 404
    assert (
        patch_draft(
            stranger, app_id, created["ETag"], {"draft_revision": 1, "fields": {"locality": "X"}}
        ).status_code
        == 404
    )
    assert stranger.get("/api/v1/applications").json()["data"]["items"] == []

    officer = signed_client(staff)
    assert officer.get(f"/api/v1/applications/{app_id}").status_code == 404
    assert (
        patch_draft(
            officer, app_id, created["ETag"], {"draft_revision": 1, "fields": {"locality": "X"}}
        ).status_code
        == 403
    )

    # A delegate with case.read only can see, not edit; draft.edit unlocks editing.
    delegation = Delegation.objects.create(
        beneficiary=applicant,
        delegate=other_applicant,
        proposed_by=other_applicant,
        premises=premises,
        capabilities=["case.read"],
        effective_from=clock.now() - timedelta(days=1),
        effective_until=clock.now() + timedelta(days=10),
        state="ACTIVE",
        reason="Consultant reading access for the test",
        confirmed_at=clock.now(),
    )
    detail = stranger.get(f"/api/v1/applications/{app_id}")
    assert detail.status_code == 200
    assert (
        next(a for a in detail.json()["data"]["allowed_actions"] if a["key"] == "edit-draft")[
            "enabled"
        ]
        is False
    )
    assert (
        patch_draft(
            stranger, app_id, created["ETag"], {"draft_revision": 1, "fields": {"locality": "X"}}
        ).status_code
        == 404
    )
    Delegation.objects.filter(pk=delegation.pk).update(capabilities=["case.read", "draft.edit"])
    ok = patch_draft(
        stranger,
        app_id,
        created["ETag"],
        {"draft_revision": 1, "fields": {"locality": "Delegate Nagar"}},
    )
    assert ok.status_code == 200
    assert (
        DraftRevision.objects.get(application_id=app_id, revision_number=2).saved_by
        == other_applicant
    )
    # Revoked -> access gone immediately.
    Delegation.objects.filter(pk=delegation.pk).update(state="REVOKED", revoked_at=clock.now())
    assert stranger.get(f"/api/v1/applications/{app_id}").status_code == 404


@pytest.mark.django_db
def test_at_04_05_same_command_key_replays_and_list_is_scoped_and_paged(
    applicant: Principal,
    premises: Premises,
    service: Service,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    key = str(uuid4())
    first = create_draft(client, premises, service, key=key)
    second = create_draft(client, premises, service, key=key)
    assert first.json()["data"]["application_id"] == second.json()["data"]["application_id"]
    assert second.json()["data"]["replayed"] is True
    assert Application.objects.filter(applicant=applicant).count() == 1
    for _ in range(21):
        create_draft(client, premises, service)
    page = client.get("/api/v1/applications").json()["data"]
    assert len(page["items"]) == 20 and page["has_more"] is True and page["next_cursor"]
    rest = client.get(f"/api/v1/applications?cursor={page['next_cursor']}").json()["data"]
    assert len(rest["items"]) == 2 and rest["has_more"] is False
    ids = {i["application_id"] for i in page["items"]} | {
        i["application_id"] for i in rest["items"]
    }
    assert len(ids) == 22
    assert client.get("/api/v1/applications?status=BOGUS").status_code == 400
    filtered = client.get(
        f"/api/v1/applications?q={premises.display_name[:6]}&status=DRAFT"
    ).json()["data"]
    assert filtered["items"] and all(i["status"] == "DRAFT" for i in filtered["items"])
