"""FR-12 / AT-12 (offline package, one accepted synchronisation, replay, changed payload,
stale assignment, lost receipt, failed-visit operation, report-vs-failure race) and the
reviewed conflict proposal (API-051/052) against real PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, Premises
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, RoleBinding
from agni.inspections.models import Inspection, InspectionReport
from agni.offline.models import ReportConflict, SyncOperation
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent
from agni.policies.models import Service

from .test_inspections import SLOT_END, SLOT_START, case_in_scrutiny, require_inspection, schedule
from .test_reports import all_pass, clean_evidence, visit  # noqa: F401 - pytest fixture import
from .test_submission import cmd

JSON = "application/json"


@pytest.fixture
def scheduled_visit(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> dict[str, Any]:
    """Attempt 1 scheduled for Priya but not started: she downloads the package the evening
    before the visit, and the assignment can still change while her device is offline."""
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    scheduled = schedule(boss, inspection, officers["priya"], SLOT_START, SLOT_END)
    assert scheduled.status_code == 200, scheduled.content
    priya = signed_client(officers["priya"])
    detail = priya.get(f"/api/v1/inspections/{inspection['inspection_id']}")
    return {
        "applicant": client,
        "boss": boss,
        "priya": priya,
        "app_id": app_id,
        "inspection_id": inspection["inspection_id"],
        "detail": detail.json()["data"],
        "etag": detail["ETag"],
    }


def manifest(v: dict[str, Any], observations: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    d = v["detail"]
    body: dict[str, Any] = {
        "operation_id": str(uuid4()),
        "operation_type": "SUBMIT_INSPECTION_REPORT",
        "inspection_id": v["inspection_id"],
        "application_version": d["application_version"],
        "base_inspection_version": d["version"],
        "assignment_version": d["current_assignment"]["version"],
        "schema_version": "1.0",
        "captured_at": "2026-09-14T06:10:00+00:00",
        "checklist_version": d["checklist_ref"],
        "observations": observations,
        "summary": "Offline report captured on the device and synchronised later.",
        "declaration_accepted": True,
    }
    body.update(over)
    return body


def sync(
    client: Client, body: dict[str, Any], *, etag: str | None = None, key: str | None = None
) -> Any:
    return client.post(
        "/api/v1/sync/operations",
        data=body,
        content_type=JSON,
        headers=cmd(etag=etag, key=key or body["operation_id"]),
    )


@pytest.mark.django_db
# Cases: AT-12-03 (lost receipt -> same operation id replayed -> one canonical receipt); DS-07
def test_at_12_01_offline_package_then_one_accepted_sync_with_replay_and_lost_receipt(
    visit: dict[str, Any],  # noqa: F811
    clock: FrozenClock,
) -> None:
    v = visit
    priya = v["priya"]
    # API-048: the assignee downloads a minimal package with expiry and versions.
    package = priya.get(f"/api/v1/inspections/{v['inspection_id']}/offline-package")
    assert package.status_code == 200, package.content
    pkg = package.json()["data"]
    assert datetime.fromisoformat(pkg["issued_at"]) == clock.now()
    assert pkg["expires_at"] == (clock.now() + timedelta(hours=24)).isoformat()
    assert pkg["schema_version"] == "1.0"
    assert pkg["versions"]["inspection_version"] == v["detail"]["version"]
    assert pkg["versions"]["assignment_version"] == v["detail"]["current_assignment"]["version"]
    assert [i["code"] for i in pkg["checklist_items"]] == ["C01", "C02", "C07"]
    assert package["Cache-Control"] == "no-store"
    assert (
        v["boss"].get(f"/api/v1/inspections/{v['inspection_id']}/offline-package").status_code
        == 404
    )
    # Evidence is uploaded through the normal pipeline before the manifest is frozen.
    evidence = clean_evidence(v, clock)
    body = manifest(v, all_pass(evidence))
    accepted = sync(priya, body, etag=v["etag"])
    assert accepted.status_code == 200, accepted.content
    receipt = accepted.json()["data"]
    assert receipt["state"] == "ACCEPTED" and receipt["accepted_entity_kind"] == "REPORT"
    assert receipt["returned_application_version"] == v["detail"]["application_version"] + 1
    assert receipt["returned_inspection_version"] == v["detail"]["version"] + 1
    assert accepted["ETag"] == f'"inspection:{v["inspection_id"]}:v{v["detail"]["version"] + 1}"'
    report = InspectionReport.objects.get(pk=receipt["accepted_entity_id"])
    assert str(report.source_operation_id) == body["operation_id"]
    assert Application.objects.get(pk=v["app_id"]).status == "REVIEW_PENDING"
    # Lost response: the same manifest (same id, same hash) replays the stored receipt.
    again = sync(priya, body, etag=v["etag"])
    assert again.status_code == 200 and again.json()["data"]["replayed"] is True
    assert again.json()["data"]["accepted_entity_id"] == receipt["accepted_entity_id"]
    assert InspectionReport.objects.filter(inspection_id=v["inspection_id"]).count() == 1
    # API-050: owner-scoped receipt; another officer sees nothing.
    looked_up = priya.get(f"/api/v1/sync/operations/{body['operation_id']}")
    assert looked_up.status_code == 200 and looked_up.json()["data"]["state"] == "ACCEPTED"
    assert v["boss"].get(f"/api/v1/sync/operations/{body['operation_id']}").status_code == 404
    # Same id, different content -> refused; the original operation stands.
    tampered = sync(
        priya, {**body, "summary": "Edited after acceptance behind the same id."}, etag=v["etag"]
    )
    assert tampered.status_code == 409 and tampered.json()["code"] == "SYNC_PAYLOAD_CONFLICT"
    assert SyncOperation.objects.filter(operation_id=body["operation_id"]).count() == 1
    assert AuditEvent.objects.filter(action="inspection.report_accepted").count() == 1


@pytest.mark.django_db
def test_at_12_02_12_04_stale_assignment_schema_and_stranger_are_refused_and_recorded(
    scheduled_visit: dict[str, Any],
    officers: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = scheduled_visit
    priya, boss = v["priya"], v["boss"]
    assert priya.get(f"/api/v1/inspections/{v['inspection_id']}/offline-package").status_code == 200
    evidence = clean_evidence(v, clock)
    # Unsupported client schema pauses the queue (422) without recording an operation.
    old_schema = sync(priya, manifest(v, all_pass(evidence), schema_version="0.9"), etag=v["etag"])
    assert old_schema.status_code == 422 and old_schema.json()["code"] == "SYNC_SCHEMA_UNSUPPORTED"
    assert not SyncOperation.objects.exists()
    # A stranger who never held a package learns nothing.
    stranger = sync(
        signed_client(officers["suresh"]), manifest(v, all_pass(evidence)), etag=v["etag"]
    )
    assert stranger.status_code == 404
    # The supervisor reassigns the attempt while the device is offline (assignment superseded).
    reassigned = boss.post(
        f"/api/v1/inspections/{v['inspection_id']}/reassign",
        data={
            "new_officer_id": str(officers["suresh"].pk),
            "reason": "Priya unreachable; Suresh takes over the visit",
            "application_version": v["detail"]["application_version"],
        },
        content_type=JSON,
        headers=cmd(etag=v["etag"]),
    )
    assert reassigned.status_code == 200, reassigned.content
    stale = manifest(v, all_pass(evidence))
    refused = sync(priya, stale, etag=v["etag"])
    assert refused.status_code == 409, refused.content
    problem = refused.json()
    assert problem["code"] == "ASSIGNMENT_CHANGED" and problem["sync_state"] == "CONFLICT"
    assert problem["server"]["assigned_to_you"] is False
    recorded = SyncOperation.objects.get(operation_id=stale["operation_id"])
    assert (
        recorded.state == "CONFLICT" and recorded.result["problem"]["code"] == "ASSIGNMENT_CHANGED"
    )
    assert not InspectionReport.objects.exists()
    assert Application.objects.get(pk=v["app_id"]).status == "INSPECTION_PENDING"
    # The device asks for the recorded outcome and gets the conflict, never a receipt.
    lookup = priya.get(f"/api/v1/sync/operations/{stale['operation_id']}").json()["data"]
    assert lookup["state"] == "CONFLICT" and "accepted_entity_id" not in lookup
    # Retrying the identical manifest replays the recorded conflict (409) - no second attempt.
    retry = sync(priya, stale, etag=v["etag"])
    assert retry.status_code == 409 and retry.json()["data"]["replayed"] is True
    # Reviewed proposal (API-051) by the former assignee; supervisor resolves (API-052).
    proposal = priya.post(
        f"/api/v1/inspections/{v['inspection_id']}/conflicts",
        data={
            "application_version": v["detail"]["application_version"],
            "operation_id": stale["operation_id"],
            "local_manifest": stale,
            "safe_local_summary": (
                "Complete eight-item report captured on site at 10:40 with two photos."
            ),
            "reason": (
                "Assignment was superseded while I was offline; evidence is attributable to "
                "my visit."
            ),
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert proposal.status_code == 201, proposal.content
    conflict = proposal.json()["data"]
    assert (
        conflict["state"] == "OPEN" and conflict["server_snapshot"]["assigned_to_proposer"] is False
    )
    assert conflict["server_snapshot"]["sync_state"] == "CONFLICT"
    listing = boss.get("/api/v1/conflicts?state=OPEN").json()["data"]["items"]
    assert [c["conflict_id"] for c in listing] == [conflict["conflict_id"]]
    resolved = boss.post(
        f"/api/v1/conflicts/{conflict['conflict_id']}/resolve",
        data={
            "outcome": "REINSPECTION_REQUIRED",
            "reason": (
                "Recovered evidence is attributable but a current assignee must re-verify on site"
            ),
            "selected_evidence_ids": [evidence],
        },
        content_type=JSON,
        headers=cmd(etag=listing[0]["etag"]),
    )
    assert resolved.status_code == 200, resolved.content
    assert (
        resolved.json()["data"]["state"] == "RESOLVED"
        and resolved.json()["data"]["outcome"] == "REINSPECTION_REQUIRED"
    )
    stored = ReportConflict.objects.get(pk=conflict["conflict_id"])
    assert stored.state == "RESOLVED" and stored.resolved_by_id is not None
    assert stored.resolved_by_id != officers["priya"].pk  # proposer never resolves own proposal
    assert stored.local_manifest == stale and stored.selected_evidence_ids == [evidence]
    twice = boss.post(
        f"/api/v1/conflicts/{conflict['conflict_id']}/resolve",
        data={"outcome": "DECLINE", "reason": "Second resolution must be refused"},
        content_type=JSON,
        headers=cmd(etag=resolved["ETag"]),
    )
    assert twice.status_code == 409
    # The proposal never became a report or reinstated the assignment.
    assert not InspectionReport.objects.exists()
    inspection = Inspection.objects.get(pk=v["inspection_id"])
    assert inspection.current_assignment is not None
    assert inspection.current_assignment.officer_id == officers["suresh"].pk


@pytest.mark.django_db
def test_at_12_02_revoked_authority_blocks_synchronisation_and_is_recorded(
    visit: dict[str, Any],  # noqa: F811
    officers: dict[str, Principal],
    clock: FrozenClock,
) -> None:
    """Task card B11 proof: authority revoked while the device was offline blocks the local
    submission. The assignment is still ACTIVE - an assignment is not authority."""
    v = visit
    priya = v["priya"]
    assert priya.get(f"/api/v1/inspections/{v['inspection_id']}/offline-package").status_code == 200
    evidence = clean_evidence(v, clock)
    body = manifest(v, all_pass(evidence))
    # The officer role binding is revoked (no epoch bump here, so the session itself stays valid
    # and the refusal is a structured, recorded conflict rather than a sign-in prompt).
    RoleBinding.objects.filter(principal=officers["priya"], role_key=RoleKey.OFFICER.value).update(
        revoked_at=clock.now()
    )
    refused = sync(priya, body, etag=v["etag"])
    assert refused.status_code == 403, refused.content
    problem = refused.json()
    assert problem["code"] == "AUTHORITY_REVOKED" and problem["sync_state"] == "CONFLICT"
    recorded = SyncOperation.objects.get(operation_id=body["operation_id"])
    assert recorded.state == "CONFLICT"
    assert recorded.result["problem"]["code"] == "AUTHORITY_REVOKED"
    assert not InspectionReport.objects.exists()
    inspection = Inspection.objects.get(pk=v["inspection_id"])
    assert inspection.status == "IN_PROGRESS" and inspection.current_assignment is not None
    assert inspection.current_assignment.state == "ACTIVE"  # supervisors reassign; nothing implicit
    # The package is no longer served and the online submission path is fenced identically.
    assert priya.get(f"/api/v1/inspections/{v['inspection_id']}/offline-package").status_code == 403
    online = priya.post(
        f"/api/v1/inspections/{v['inspection_id']}/reports",
        data={**{k: body[k] for k in ("application_version", "assignment_version")}},
        content_type=JSON,
        headers=cmd(etag=v["etag"]),
    )
    assert online.status_code == 403 and online.json()["code"] == "AUTHORITY_REVOKED"
    # A disabled account (epoch bump) is stopped at the session boundary: nothing more is recorded.
    principal = Principal.objects.get(pk=officers["priya"].pk)
    principal.disable(clock.now())
    principal.save(update_fields=["is_active", "disabled_at", "authz_epoch", "updated_at"])
    again = sync(priya, manifest(v, all_pass(evidence)), etag=v["etag"])
    assert again.status_code == 401, again.content
    assert SyncOperation.objects.count() == 1


@pytest.mark.django_db
# AT-X-01 (offline failed visit synchronised twice -> one outcome) AT-X-02 (report vs failed-visit
# race -> one terminal outcome); DS-08
def test_at_12_05_failed_visit_operation_and_report_versus_failure_race(
    visit: dict[str, Any],  # noqa: F811
    clock: FrozenClock,
) -> None:
    v = visit
    priya = v["priya"]
    d = v["detail"]
    failed = {
        "operation_id": str(uuid4()),
        "operation_type": "RECORD_FAILED_VISIT",
        "inspection_id": v["inspection_id"],
        "application_version": d["application_version"],
        "base_inspection_version": d["version"],
        "assignment_version": d["current_assignment"]["version"],
        "schema_version": "1.0",
        "captured_at": "2026-09-14T04:45:00+00:00",
        "reason_code": "SITE_INACCESSIBLE",
        "reason": "Premises locked; caretaker absent; gate photographed",
    }
    # Observations are forbidden on a failed-visit operation.
    invalid = sync(
        priya, {**failed, "observations": [{"item_code": "C01", "result": "PASS"}]}, etag=v["etag"]
    )
    assert invalid.status_code == 422 and any(
        x["pointer"] == "/observations" for x in invalid.json()["violations"]
    )
    accepted = sync(priya, failed, etag=v["etag"])
    assert accepted.status_code == 200, accepted.content
    receipt = accepted.json()["data"]
    assert (
        receipt["accepted_entity_kind"] == "VISIT_OUTCOME"
        and receipt["accepted_entity_id"] == v["inspection_id"]
    )
    assert (
        receipt["returned_application_version"] == d["application_version"]
    )  # case clock untouched
    attempts = list(
        Inspection.objects.filter(application_id=v["app_id"]).order_by("attempt_number")
    )
    assert [a.status for a in attempts] == ["FAILED", "REQUESTED"]
    assert Application.objects.get(pk=v["app_id"]).status == "INSPECTION_PENDING"
    # Report after the failure already closed the attempt: a structured conflict, local data kept.
    evidence_body = manifest(
        v,
        [
            {"item_code": "C01", "result": "PASS", "note": "", "document_version_ids": []},
            {"item_code": "C02", "result": "PASS", "note": "", "document_version_ids": []},
            {"item_code": "C07", "result": "PASS", "note": "", "document_version_ids": []},
        ],
    )
    race = sync(priya, evidence_body, etag=v["etag"])
    assert race.status_code in (409, 412), race.content
    assert race.json()["sync_state"] == "CONFLICT"
    assert SyncOperation.objects.get(operation_id=evidence_body["operation_id"]).state == "CONFLICT"
    assert not InspectionReport.objects.exists()
    assert SyncOperation.objects.filter(state="ACCEPTED").count() == 1
