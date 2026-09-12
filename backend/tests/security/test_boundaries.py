"""Authorization boundary matrix (docs/06 s.10; security s.5 / s.9): anonymous, wrong role,
right role / wrong scope, substituted identifiers, caller-supplied authority and disallowed
methods across the sensitive endpoints. Every refusal must leave no side effect."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture import
from tests.integration.test_submission import cmd

JSON = "application/json"
REASON = "Security boundary drill; synthetic demonstration data only."


def _sensitive_reads(app_id: str, inspection_id: str) -> list[str]:
    return [
        f"/api/v1/applications/{app_id}",
        f"/api/v1/applications/{app_id}/timeline",
        f"/api/v1/inspections/{inspection_id}",
        "/api/v1/me",
        "/api/v1/applications",
        "/api/v1/certificates",
        "/api/v1/tickets",
        "/api/v1/exports",
        "/api/v1/reports/summary",
        "/api/v1/audit-events",
        "/api/v1/jobs",
        "/api/v1/staff",
        "/api/v1/authority-grants",
        "/api/v1/integrations",
        "/api/v1/integration-conflicts",
        "/api/v1/notifications",
    ]


STAFF_ONLY = [
    "/api/v1/audit-events",
    "/api/v1/jobs",
    "/api/v1/staff",
    "/api/v1/authority-grants",
    "/api/v1/integrations",
    "/api/v1/integration-conflicts",
]
ADMIN_ONLY = ["/api/v1/jobs", "/api/v1/integrations"]


def _problem(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    assert response["Content-Type"].startswith("application/problem+json"), response.content
    assert body["request_id"]
    return body


@pytest.mark.django_db
def test_anonymous_requests_are_refused_uniformly(
    visit: dict[str, Any],  # noqa: F811
) -> None:
    anonymous = Client(enforce_csrf_checks=True)
    for path in _sensitive_reads(visit["app_id"], visit["inspection_id"]):
        response = anonymous.get(path)
        assert response.status_code == 401, path
        body = _problem(response)
        assert body["code"] == "AUTHENTICATION_REQUIRED"
        assert "Demo Warehouse" not in response.content.decode()
    # Unsafe methods without a session or CSRF token never reach a handler.
    for path in (
        f"/api/v1/applications/{visit['app_id']}/withdraw",
        f"/api/v1/applications/{visit['app_id']}/decisions",
        "/api/v1/exports",
        "/api/v1/authority-grants",
    ):
        response = anonymous.post(path, data={"reason": REASON}, content_type=JSON)
        assert response.status_code in (401, 403), path
    assert AuditEvent.objects.filter(action__in=("export.requested", "grant.proposed")).count() == 0


@pytest.mark.django_db
# Cases: AT-21-04 (applicants cannot reach issuance / job recovery or staff reads) and the
# cross-applicant scope cases of every FR (see the module docstring)
def test_applicants_cannot_reach_staff_functions_or_others_cases(
    visit: dict[str, Any],  # noqa: F811
    other_applicant: Principal,
    signed_client: Callable[[Principal], Client],
) -> None:
    owner, app_id = visit["applicant"], visit["app_id"]
    for path in STAFF_ONLY:
        response = owner.get(path)
        assert response.status_code == 403, path
        assert _problem(response)["code"] == "FORBIDDEN"
    # Reports exist for applicants but only over their own cases (permission matrix "O limited").
    own_metrics = owner.get("/api/v1/reports/summary").json()["data"]
    assert own_metrics["scope"] == {"kind": "OWN_CASES"} and own_metrics["metrics"]["received"] == 1
    etag = owner.get(f"/api/v1/applications/{app_id}")["ETag"]
    forbidden_commands = [
        (f"/api/v1/applications/{app_id}/decisions", {"kind": "APPROVE", "reason": REASON}),
        (f"/api/v1/applications/{app_id}/holds", {"kind": "ADMINISTRATIVE", "reason": REASON}),
        (f"/api/v1/applications/{app_id}/require-inspection", {"reason": REASON}),
        (f"/api/v1/jobs/{uuid4()}/retry", {"reason": REASON}),
        ("/api/v1/authority-grants", {"subject_id": str(uuid4()), "reason": REASON}),
        (f"/api/v1/staff/{uuid4()}/deactivate", {"reason": REASON}),
        (
            f"/api/v1/integrations/{uuid4()}/test",
            {"test_case_key": "connectivity", "reason": REASON},
        ),
    ]
    for path, payload in forbidden_commands:
        response = owner.post(path, data=payload, content_type=JSON, headers=cmd(etag=etag))
        assert response.status_code in (403, 404), (path, response.content)
    # Another applicant learns nothing about this case through any identifier.
    stranger = signed_client(other_applicant)
    for path in (
        f"/api/v1/applications/{app_id}",
        f"/api/v1/applications/{app_id}/timeline",
        f"/api/v1/applications/{app_id}/revisions",
    ):
        response = stranger.get(path)
        assert response.status_code == 404, path
        assert "Demo Warehouse" not in response.content.decode()
    # Inspections are a staff resource: applicants get the same 403 for real and unknown ids.
    real = stranger.get(f"/api/v1/inspections/{visit['inspection_id']}")
    fake = stranger.get(f"/api/v1/inspections/{uuid4()}")
    assert real.status_code == fake.status_code == 403
    assert "Demo Warehouse" not in real.content.decode()
    assert stranger.get("/api/v1/applications").json()["data"]["items"] == []
    withdraw = stranger.post(
        f"/api/v1/applications/{app_id}/withdraw",
        data={"reason": REASON},
        content_type=JSON,
        headers=cmd(etag=etag),
    )
    assert withdraw.status_code == 404
    assert Application.objects.get(pk=app_id).status == "INSPECTION_PENDING"


@pytest.mark.django_db
def test_staff_roles_stop_at_their_scope(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    foreign_supervisor: Principal,
    leadership: Principal,
    governance_actors: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
) -> None:
    app_id = visit["app_id"]
    # Assigned officer: the case, not the management planes.
    officer = visit["priya"]
    assert officer.get(f"/api/v1/applications/{app_id}").status_code == 200
    for path in [*STAFF_ONLY, "/api/v1/reports/summary"]:
        assert officer.get(path).status_code == 403, path
    # Supervisor of the jurisdiction: case + reports, never operations.
    boss = visit["boss"]
    assert boss.get(f"/api/v1/applications/{app_id}").status_code == 200
    assert boss.get("/api/v1/reports/summary").status_code == 200
    for path in ADMIN_ONLY:
        assert boss.get(path).status_code == 403, path
    # Supervisor of another jurisdiction: nothing of this case, empty lists, no conflicts.
    foreign = signed_client(foreign_supervisor)
    assert foreign.get(f"/api/v1/applications/{app_id}").status_code == 404
    assert foreign.get("/api/v1/applications").json()["data"]["items"] == []
    assert foreign.get("/api/v1/reports/summary").json()["data"]["metrics"]["received"] == 0
    assert foreign.get("/api/v1/audit-events", {"entity_id": app_id}).json()["data"]["items"] == []
    # Leadership reads its region; it cannot command a case.
    neha = signed_client(leadership)
    assert neha.get(f"/api/v1/applications/{app_id}").status_code == 200
    detail_etag = neha.get(f"/api/v1/applications/{app_id}")["ETag"]
    decide = neha.post(
        f"/api/v1/applications/{app_id}/decisions",
        data={"kind": "APPROVE", "reason": REASON},
        content_type=JSON,
        headers=cmd(etag=detail_etag),
    )
    assert decide.status_code in (403, 404)
    # Operations administrator: management planes yes, case content and decisions no.
    admin = signed_client(governance_actors["admin"])
    assert admin.get("/api/v1/jobs").status_code == 200
    case = admin.get(f"/api/v1/applications/{app_id}")
    assert case.status_code in (403, 404)
    assert "Demo Warehouse" not in case.content.decode()
    assert admin.get("/api/v1/applications").json()["data"]["items"] == []
    decide = admin.post(
        f"/api/v1/applications/{app_id}/decisions",
        data={"kind": "APPROVE", "reason": REASON},
        content_type=JSON,
        headers=cmd(etag=detail_etag),
    )
    assert decide.status_code in (403, 404)
    # Policy approver: no operations, no case content.
    meera = signed_client(governance_actors["approver"])
    assert meera.get("/api/v1/jobs").status_code == 403
    assert meera.get(f"/api/v1/applications/{app_id}").status_code in (403, 404)
    assert Application.objects.get(pk=app_id).status == "INSPECTION_PENDING"
    assert AuditEvent.objects.filter(entity_id=app_id, action__startswith="decision.").count() == 0


@pytest.mark.django_db
def test_substituted_identifiers_and_forbidden_methods_learn_nothing(
    visit: dict[str, Any],  # noqa: F811
    governance_actors: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
) -> None:
    owner = visit["applicant"]
    unknown = uuid4()
    for path in (
        f"/api/v1/applications/{unknown}",
        f"/api/v1/documents/{unknown}",
        f"/api/v1/certificates/{unknown}",
        f"/api/v1/exports/{unknown}",
        f"/api/v1/tickets/{unknown}",
        f"/api/v1/notices/{unknown}",
    ):
        response = owner.get(path)
        assert response.status_code == 404, path
        assert _problem(response)["code"] == "RESOURCE_NOT_FOUND"
    assert owner.get(f"/api/v1/inspections/{unknown}").status_code == 403  # staff resource
    admin = signed_client(governance_actors["admin"])
    for path in (
        f"/api/v1/jobs/{unknown}",
        f"/api/v1/staff/{unknown}",
        f"/api/v1/integrations/{unknown}",
        f"/api/v1/integration-conflicts/{unknown}",
        f"/api/v1/audit-events/{unknown}",
    ):
        assert admin.get(path).status_code == 404, path
    # Methods outside the contract are refused, not silently ignored.
    for method in ("delete", "put", "patch"):
        response = getattr(owner, method)(f"/api/v1/applications/{visit['app_id']}")
        assert response.status_code == 405, method
        assert _problem(response)["code"] == "MALFORMED_REQUEST"
    # Malformed identifiers never reach a handler as SQL.
    assert owner.get("/api/v1/applications/not-a-uuid").status_code == 404
    assert admin.get("/api/v1/jobs", {"state": "' OR 1=1 --"}).status_code == 400
    assert admin.get("/api/v1/audit-events", {"limit": "1;DROP TABLE"}).status_code == 422
    assert owner.get("/api/v1/reports/summary", {"jurisdiction_id": "1 OR 1=1"}).status_code == 422


@pytest.mark.django_db
def test_caller_supplied_authority_is_ignored_or_refused(
    visit: dict[str, Any],  # noqa: F811
    premises: Any,
    service: Any,
    supervisor: Principal,
    clock: FrozenClock,
) -> None:
    owner, boss, app_id = visit["applicant"], visit["boss"], visit["app_id"]
    # Payload fields naming status, actor or certificate number are contract violations.
    detail = boss.get(f"/api/v1/applications/{app_id}")
    forged = boss.post(
        f"/api/v1/applications/{app_id}/decisions",
        data={
            "kind": "APPROVE",
            "reason": REASON,
            "public_reason": REASON,
            "review_acknowledged": True,
            "actor_id": str(supervisor.pk),
            "certificate_number": "AGNI-FORGED-1",
            "status": "COMPLETED",
        },
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )
    assert forged.status_code in (403, 409, 422), forged.content
    assert Application.objects.get(pk=app_id).status == "INSPECTION_PENDING"
    # A draft cannot be created in a non-draft state or with an owner queue chosen by the caller.
    created = owner.post(
        "/api/v1/applications",
        data={
            "premises_id": str(premises.pk),
            "service_id": str(service.pk),
            "status": "COMPLETED",
            "owner_queue_id": str(uuid4()),
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert created.status_code in (201, 422)
    if created.status_code == 201:
        assert created.json()["data"]["status"] == "DRAFT"
    # A session carries no client-chosen role: /me reports server-derived workspaces only.
    me = owner.get("/api/v1/me").json()["data"]
    assert me["workspaces"] == ["applicant"] and me["capabilities"] == []
