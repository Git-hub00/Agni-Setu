"""FR-13 / AT-13-01..06 (report drafts, assigned-actor-only submission, one immutable report,
evidence provenance) and FR-14 / AT-14-01..06 (checklist evaluation: mandatory blockers, policy
NA, no score) through the HTTP API against real PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, Premises, StageInstance
from agni.documents.models import DocumentVersion
from agni.identity.models import Principal
from agni.inspections.models import Assignment, Inspection, InspectionDraft, InspectionReport
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, OutboxMessage
from agni.policies.models import Service

from .test_inspections import SLOT_END, SLOT_START, case_in_scrutiny, require_inspection, schedule
from .test_submission import cmd
from .test_uploads import PDF, reserve, run_worker, sha

JSON = "application/json"


def upload_evidence(client: Client, inspection_id: str, code: str, data: bytes) -> Any:
    """Officer evidence: INSPECTION_EVIDENCE reservation -> PUT bytes -> complete."""
    reserved = reserve(
        client,
        inspection_id,
        code,
        data,
        target_type="INSPECTION_EVIDENCE",
        original_name="photo.pdf",
    )
    if reserved.status_code != 201:
        return reserved
    ticket = reserved.json()["data"]
    put = client.put(ticket["upload_url"], data=data, content_type="application/pdf")
    assert put.status_code == 200, put.content
    done = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data={"sha256": sha(data), "size_bytes": len(data)},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": reserved["ETag"]},
    )
    assert done.status_code == 202, done.content
    return done


@pytest.fixture
def visit(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> dict[str, Any]:
    """A case in INSPECTION_PENDING whose attempt 1 is scheduled for Priya and checked in."""
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    scheduled = schedule(boss, inspection, officers["priya"], SLOT_START, SLOT_END)
    assert scheduled.status_code == 200, scheduled.content
    priya = signed_client(officers["priya"])
    body = scheduled.json()["data"]
    checked = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/check-in",
        data={
            "application_version": body["application_version"],
            "assignment_version": body["current_assignment"]["version"],
            "captured_at": "2026-09-14T04:32:00+00:00",
            "location_unavailable_reason": "GPS denied on the device",
        },
        content_type=JSON,
        headers=cmd(etag=scheduled["ETag"]),
    )
    assert checked.status_code == 200, checked.content
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


def base(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "application_version": detail["application_version"],
        "assignment_version": detail["current_assignment"]["version"],
        "checklist_version": detail["checklist_ref"],
    }


def observation(
    code: str, result: str, note: str = "", docs: list[str] | None = None
) -> dict[str, Any]:
    return {"item_code": code, "result": result, "note": note, "document_version_ids": docs or []}


def all_pass(evidence: str) -> list[dict[str, Any]]:
    return [
        observation("C01", "PASS", docs=[evidence]),
        observation("C02", "PASS", "Six extinguishers in date", docs=[evidence]),
        observation("C07", "PASS", "Two access points clear"),
    ]


def submit_body(
    detail: dict[str, Any], observations: list[dict[str, Any]], **over: Any
) -> dict[str, Any]:
    body = {
        **base(detail),
        "observations": observations,
        "summary": "Visit completed; all items verified on site.",
        "captured_at": "2026-09-14T06:10:00+00:00",
        "declaration_accepted": True,
    }
    body.update(over)
    return body


def submit(
    client: Client,
    v: dict[str, Any],
    body: dict[str, Any],
    *,
    key: str | None = None,
    etag: str | None = None,
) -> Any:
    return client.post(
        f"/api/v1/inspections/{v['inspection_id']}/reports",
        data=body,
        content_type=JSON,
        headers=cmd(etag=etag or v["etag"], key=key),
    )


def clean_evidence(v: dict[str, Any], clock: FrozenClock, code: str = "inspection-c01") -> str:
    done = upload_evidence(v["priya"], v["inspection_id"], code, PDF + b"site-photo")
    assert done.status_code == 202, done.content
    run_worker(clock)
    doc_id = done.json()["data"]["document_version_id"]
    assert DocumentVersion.objects.get(pk=doc_id).scan_state == "CLEAN"
    return str(doc_id)


@pytest.mark.django_db
def test_at_13_01_14_01_draft_then_accepted_report_moves_case_to_review(
    visit: dict[str, Any], clock: FrozenClock
) -> None:
    v = visit
    priya, detail = v["priya"], v["detail"]
    assert {a["key"]: a["enabled"] for a in detail["allowed_actions"]}["submit-report"] is True

    # Officer evidence belongs to the case and is scanned like every file.
    evidence = clean_evidence(v, clock)
    doc = DocumentVersion.objects.get(pk=evidence)
    assert str(doc.application_id) == v["app_id"] and doc.requirement_code == "inspection-c01"

    # API-045: partial draft, guarded by the inspection ETag; the inspection version stays put.
    saved = priya.put(
        f"/api/v1/inspections/{v['inspection_id']}/draft",
        data={
            **base(detail),
            "observations": [observation("C01", "PASS", docs=[evidence])],
            "summary": "in progress",
            "local_revision": 3,
        },
        content_type=JSON,
        headers=cmd(etag=v["etag"]),
    )
    assert saved.status_code == 200, saved.content
    draft = saved.json()["data"]
    assert draft["local_revision"] == 3 and draft["inspection_version"] == detail["version"]
    assert saved["ETag"].startswith('"draft:')
    again = priya.get(f"/api/v1/inspections/{v['inspection_id']}")
    assert (
        again["ETag"] == v["etag"]
        and again.json()["data"]["draft"]["observations"][0]["item_code"] == "C01"
    )
    # A second save updates the same draft row (one active draft per inspection/officer).
    saved2 = priya.put(
        f"/api/v1/inspections/{v['inspection_id']}/draft",
        data={**base(detail), "observations": all_pass(evidence), "local_revision": 4},
        content_type=JSON,
        headers=cmd(etag=v["etag"]),
    )
    assert (
        saved2.status_code == 200
        and InspectionDraft.objects.filter(inspection_id=v["inspection_id"]).count() == 1
    )

    # API-047: the complete report is accepted once; TR-06 moves the case.
    accepted = submit(priya, v, submit_body(detail, all_pass(evidence)))
    assert accepted.status_code == 201, accepted.content
    body = accepted.json()["data"]
    receipt = body["receipt"]
    assert body["status"] == "COMPLETED" and receipt["revision_number"] == 1
    assert receipt["application_status"] == "REVIEW_PENDING" and len(receipt["sha256"]) == 64
    assert body["report"]["evaluation"]["eligible_for_review"] is True
    assert (
        body["report"]["evaluation"]["blockers"] == []
        and "score" not in body["report"]["evaluation"]
    )
    assert [e["item_code"] for e in body["report"]["evidence"]] == ["C01", "C02"]
    assert body["report"]["evidence"][0]["sha256"] == doc.sha256
    assert accepted["ETag"] == f'"inspection:{v["inspection_id"]}:v{detail["version"] + 1}"'

    app = Application.objects.get(pk=v["app_id"])
    assert app.status == "REVIEW_PENDING" and app.version == detail["application_version"] + 1
    stages = list(
        StageInstance.objects.filter(application=app)
        .order_by("cycle_number")
        .values_list("state", flat=True)
    )
    assert stages[-2:] == ["INSPECTION_PENDING", "REVIEW_PENDING"]
    kinds = {o.kind: o for o in Obligation.objects.filter(application=app)}
    assert kinds["INSPECTION_TASK"].state == "SATISFIED" and kinds["CASE_TARGET"].state == "ACTIVE"
    review = kinds["REVIEW_TASK"]
    assert (
        review.state == "ACTIVE" and review.time_basis == "WORKING" and review.budget_minutes == 480
    )
    assert review.due_at is not None and review.due_at > clock.now()
    inspection = Inspection.objects.get(pk=v["inspection_id"])
    assert inspection.status == "COMPLETED" and inspection.current_report_id is not None
    assert (
        Assignment.objects.get(pk=detail["current_assignment"]["assignment_id"]).state
        == "FULFILLED"
    )
    assert not InspectionDraft.objects.filter(inspection=inspection).exists()
    report = InspectionReport.objects.get(pk=receipt["report_id"])
    assert inspection.current_assignment is not None
    assert report.submitted_by_id == inspection.current_assignment.officer_id
    assert report.evidence.count() == 2 and report.sha256 == receipt["sha256"]
    # Audience: applicant sees acceptance, not the internal evaluation event or blockers.
    public = [
        e["event_type"]
        for e in v["applicant"]
        .get(f"/api/v1/applications/{v['app_id']}/timeline")
        .json()["data"]["items"]
    ]
    assert (
        "inspection.report_accepted.v1" in public and "inspection.report_evaluated.v1" not in public
    )
    staff_events = [
        e["event_type"]
        for e in v["boss"]
        .get(f"/api/v1/applications/{v['app_id']}/timeline")
        .json()["data"]["items"]
    ]
    assert "inspection.report_evaluated.v1" in staff_events
    applicant_case = v["applicant"].get(f"/api/v1/applications/{v['app_id']}").json()["data"]
    assert applicant_case["status"] == "REVIEW_PENDING" and applicant_case["inspections"][0][
        "report"
    ] == {
        "revision_number": 1,
        "accepted_at": report.accepted_at.isoformat(),
    }
    staff_case = v["boss"].get(f"/api/v1/applications/{v['app_id']}").json()["data"]
    assert staff_case["inspections"][0]["report"]["eligible_for_review"] is True
    # Supervisor reads the accepted report through the attempt.
    boss_view = v["boss"].get(f"/api/v1/inspections/{v['inspection_id']}").json()["data"]
    assert boss_view["report"]["revision_number"] == 1 and boss_view["draft"] is None
    assert AuditEvent.objects.filter(action="inspection.report_accepted").exists()
    assert OutboxMessage.objects.filter(event_type="inspection.report_accepted.v1").count() == 1


@pytest.mark.django_db
def test_at_13_02_13_04_only_the_current_assignee_submits_and_a_duplicate_yields_one_report(
    visit: dict[str, Any],
    officers: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    detail = v["detail"]
    evidence = clean_evidence(v, clock)
    body = submit_body(detail, all_pass(evidence))
    # Another eligible officer (never assigned) learns nothing.
    suresh = signed_client(officers["suresh"])
    assert submit(suresh, v, body).status_code == 404
    assert (
        suresh.put(
            f"/api/v1/inspections/{v['inspection_id']}/draft",
            data={**base(detail), "observations": []},
            content_type=JSON,
            headers=cmd(etag=v["etag"]),
        ).status_code
        == 404
    )
    # The supervisor cannot author the report either; applicants are refused outright.
    assert submit(v["boss"], v, body).status_code == 404
    assert submit(v["applicant"], v, body).status_code == 403
    # Stale assignment version -> ASSIGNMENT_CHANGED; stale inspection ETag -> 412.
    stale = submit(v["priya"], v, {**body, "assignment_version": 42})
    assert stale.status_code == 409 and stale.json()["code"] == "ASSIGNMENT_CHANGED"
    old = submit(v["priya"], v, body, etag=f'"inspection:{v["inspection_id"]}:v1"')
    assert old.status_code == 412
    # Same command twice (retry with the same key) -> one report, replayed receipt.
    key = str(uuid4())
    first = submit(v["priya"], v, body, key=key)
    second = submit(v["priya"], v, body, key=key)
    assert first.status_code == 201 and second.status_code == 201
    assert second.json()["data"]["replayed"] is True
    assert (
        first.json()["data"]["receipt"]["report_id"]
        == second.json()["data"]["receipt"]["report_id"]
    )
    assert InspectionReport.objects.filter(inspection_id=v["inspection_id"]).count() == 1
    # A fresh submit on the completed attempt is refused; no second revision appears.
    closed = submit(v["priya"], v, body, etag=first["ETag"])
    assert closed.status_code == 409 and closed.json()["code"] == "INVALID_TRANSITION"
    assert InspectionReport.objects.filter(inspection_id=v["inspection_id"]).count() == 1
    # Immutability: the accepted row cannot be edited through the model.
    report = InspectionReport.objects.get(inspection_id=v["inspection_id"])
    report.summary = "tampered"
    with pytest.raises(Exception, match="append-only|immutable|cannot"):
        report.save()


@pytest.mark.django_db
def test_at_14_02_14_03_mandatory_fail_blocks_eligibility_but_is_recorded_faithfully(
    visit: dict[str, Any], clock: FrozenClock
) -> None:
    v = visit
    detail = v["detail"]
    evidence = clean_evidence(v, clock)
    observations = [
        observation(
            "C01", "FAIL", "Rear escape route padlocked and stacked with cartons", docs=[evidence]
        ),
        observation("C02", "PASS", docs=[evidence]),
        observation("C07", "NOT_APPLICABLE", "Single frontage; no separate access question"),
    ]
    accepted = submit(
        v["priya"],
        v,
        submit_body(
            detail, observations, summary="Escape route blocked; everything else in order."
        ),
    )
    assert accepted.status_code == 201, accepted.content
    evaluation = accepted.json()["data"]["report"]["evaluation"]
    assert evaluation["eligible_for_review"] is False
    assert [b["code"] for b in evaluation["blockers"]] == ["MANDATORY_FAIL"]
    assert evaluation["findings"][0] == {
        "item_code": "C01",
        "severity": "MANDATORY",
        "result": "FAIL",
        "note": "Rear escape route padlocked and stacked with cartons",
    }
    assert evaluation["na_requiring_review"] == ["C07"]
    assert evaluation["counts"] == {"PASS": 1, "FAIL": 1, "NOT_VERIFIED": 0, "NOT_APPLICABLE": 1}
    # The report is still the accepted record and the case proceeds to review; nothing
    # auto-rejects and no score exists to offset the blocker.
    assert Application.objects.get(pk=v["app_id"]).status == "REVIEW_PENDING"
    staff_case = v["boss"].get(f"/api/v1/applications/{v['app_id']}").json()["data"]
    assert staff_case["inspections"][0]["report"]["blockers"][0]["item_code"] == "C01"
    assert "score" not in staff_case["inspections"][0]["report"]


@pytest.mark.django_db
def test_at_13_03_14_04_invalid_observations_and_foreign_or_unscanned_evidence_are_refused(
    visit: dict[str, Any],
    other_applicant: Principal,
    supervisor: Principal,
    service: Service,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    detail = v["detail"]
    evidence = clean_evidence(v, clock)

    def expect_422(body: dict[str, Any], pointer: str, code: str | None = None) -> None:
        response = submit(v["priya"], v, body)
        assert response.status_code == 422, response.content
        violations = response.json()["violations"]
        assert any(
            x["pointer"] == pointer and (code is None or x["code"] == code) for x in violations
        ), violations

    # Incomplete set, invented code, duplicate, NA where not permitted, missing notes.
    expect_422(submit_body(detail, all_pass(evidence)[:2]), "/observations", "missing")
    expect_422(
        submit_body(detail, [*all_pass(evidence), observation("C99", "PASS")]),
        "/observations/3/item_code",
        "unknown",
    )
    expect_422(
        submit_body(detail, [*all_pass(evidence), observation("C07", "PASS")]),
        "/observations/3/item_code",
        "duplicate",
    )
    expect_422(
        submit_body(
            detail,
            [
                observation("C01", "NOT_APPLICABLE", "not applicable in my opinion"),
                *all_pass(evidence)[1:],
            ],
        ),
        "/observations/0/result",
        "na_not_permitted",
    )
    expect_422(
        submit_body(
            detail, [observation("C01", "FAIL", "bad", docs=[evidence]), *all_pass(evidence)[1:]]
        ),
        "/observations/0/note",
        "required",
    )
    # Declaration, summary and capture time rules.
    expect_422(
        submit_body(detail, all_pass(evidence), declaration_accepted=False), "/declaration_accepted"
    )
    expect_422(submit_body(detail, all_pass(evidence), summary="short"), "/summary")
    expect_422(submit_body(detail, all_pass(evidence), captured_at=None), "/captured_at")
    expect_422(
        submit_body(detail, all_pass(evidence), checklist_version="demo-checklist-v1#99"),
        "/checklist_version",
        "stale",
    )
    # Wrong-case evidence: a CLEAN file of another applicant's case is not this case's evidence.
    other_premises = Premises.objects.create(
        owner=other_applicant,
        display_name="Other Hall",
        address_line1="9 Demo Road",
        locality="Demo Nagar",
        ward_key="W-01",
        postal_code="560001",
        category_key="Office",
        area_sqm=200,
        height_m=5,
        floor_count=1,
    )
    _, _, other_app = case_in_scrutiny(
        other_applicant, supervisor, other_premises, service, signed_client, clock
    )
    foreign_doc = str(
        DocumentVersion.objects.filter(application_id=other_app, scan_state="CLEAN")
        .values_list("pk", flat=True)
        .first()
    )
    expect_422(
        submit_body(
            detail, [observation("C01", "PASS", docs=[foreign_doc]), *all_pass(evidence)[1:]]
        ),
        "/observations/0/document_version_ids/0",
        "not_clean_case_evidence",
    )
    # Quarantined (not yet scanned) evidence of this case is refused too.
    pending = upload_evidence(
        v["priya"], v["inspection_id"], "inspection-c02", PDF + b"unscanned"
    ).json()["data"]["document_version_id"]
    expect_422(
        submit_body(detail, [observation("C01", "PASS", docs=[pending]), *all_pass(evidence)[1:]]),
        "/observations/0/document_version_ids/0",
        "not_clean_case_evidence",
    )
    # Nothing was accepted along the way.
    assert not InspectionReport.objects.filter(inspection_id=v["inspection_id"]).exists()
    assert Inspection.objects.get(pk=v["inspection_id"]).status == "IN_PROGRESS"
    assert Application.objects.get(pk=v["app_id"]).status == "INSPECTION_PENDING"


@pytest.mark.django_db
def test_at_13_05_evidence_uploads_are_scoped_to_the_assigned_officer_and_pinned_checklist(
    visit: dict[str, Any],
    officers: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
) -> None:
    v = visit
    # Applicants cannot use the evidence target; unassigned officers learn nothing.
    denied = reserve(
        v["applicant"], v["inspection_id"], "inspection-c01", PDF, target_type="INSPECTION_EVIDENCE"
    )
    assert denied.status_code == 422 and denied.json()["violations"][0]["pointer"] == "/target_type"
    assert (
        upload_evidence(
            signed_client(officers["suresh"]), v["inspection_id"], "inspection-c01", PDF
        ).status_code
        == 404
    )
    # Item codes must exist in the pinned checklist and use the evidence naming.
    bad_code = reserve(
        v["priya"], v["inspection_id"], "inspection-c99", PDF, target_type="INSPECTION_EVIDENCE"
    )
    assert (
        bad_code.status_code == 422
        and bad_code.json()["violations"][0]["pointer"] == "/requirement_code"
    )
    plain = reserve(v["priya"], v["inspection_id"], "plan", PDF, target_type="INSPECTION_EVIDENCE")
    assert plain.status_code == 422
    # Officers cannot add files to the applicant's draft target.
    assert reserve(v["priya"], v["app_id"], "plan", PDF).status_code == 422


@pytest.mark.django_db
def test_at_13_06_report_needs_check_in_and_draft_needs_current_inspection_version(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    _, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    scheduled = schedule(boss, inspection, officers["priya"], SLOT_START, SLOT_END)
    priya = signed_client(officers["priya"])
    detail = priya.get(f"/api/v1/inspections/{inspection['inspection_id']}")
    d = detail.json()["data"]
    actions = {a["key"]: a for a in d["allowed_actions"]}
    assert actions["save-draft"]["enabled"] is True and actions["submit-report"] == {
        "key": "submit-report",
        "enabled": False,
        "reason_code": "CHECK_IN_REQUIRED",
    }
    # Drafting before check-in is allowed (preparation); submitting is not.
    no_etag = priya.put(
        f"/api/v1/inspections/{d['inspection_id']}/draft",
        data={**base(d), "observations": []},
        content_type=JSON,
        headers=cmd(),
    )
    assert no_etag.status_code == 428
    stale = priya.put(
        f"/api/v1/inspections/{d['inspection_id']}/draft",
        data={**base(d), "observations": []},
        content_type=JSON,
        headers=cmd(etag=f'"inspection:{d["inspection_id"]}:v1"'),
    )
    assert stale.status_code == 412 and stale.json()["current_version"] == d["version"]
    ok = priya.put(
        f"/api/v1/inspections/{d['inspection_id']}/draft",
        data={
            **base(d),
            "observations": [
                observation("C07", "NOT_VERIFIED", "Will check the rear lane on arrival")
            ],
        },
        content_type=JSON,
        headers=cmd(etag=scheduled["ETag"]),
    )
    assert ok.status_code == 200, ok.content
    early = priya.post(
        f"/api/v1/inspections/{d['inspection_id']}/reports",
        data=submit_body(
            d, [observation("C01", "PASS"), observation("C02", "PASS"), observation("C07", "PASS")]
        ),
        content_type=JSON,
        headers=cmd(etag=scheduled["ETag"]),
    )
    assert early.status_code == 409 and early.json()["code"] == "INVALID_TRANSITION"
    assert not InspectionReport.objects.exists()
