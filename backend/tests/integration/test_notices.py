"""FR-15 / AT-15 (itemised notices, supersession, authorisation), FR-16 / AT-16 (response
revisions never close anything) and FR-17 / AT-17 (verified closure, return, reinspection,
complete-corrections) through the HTTP API against real PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, Premises, StageInstance
from agni.documents.models import DocumentVersion
from agni.identity.models import Principal
from agni.inspections.models import Inspection
from agni.notices.models import Finding, Notice, NoticeItem, ResponseRevision
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, OutboxMessage
from agni.policies.models import Service

from .test_inspections import case_in_scrutiny
from .test_reports import (  # noqa: F401 - `visit` is a fixture used by the deficiency tests
    all_pass,
    clean_evidence,
    observation,
    submit,
    submit_body,
    visit,
)
from .test_submission import cmd
from .test_uploads import PDF, reserve, run_worker, sha

JSON = "application/json"
INFO_ITEMS = [
    {
        "code": "INFO-01",
        "title": "Ownership proof is illegible",
        "description": "Upload a legible copy of the ownership document (all pages).",
        "required": True,
        "acceptable_evidence_types": ["DOCUMENT"],
    },
    {
        "code": "INFO-02",
        "title": "Optional floor plan clarification",
        "description": "If available, mark the assembly points on the floor plan.",
        "required": False,
        "acceptable_evidence_types": ["DOCUMENT", "WRITTEN_EXPLANATION"],
        "public_guidance": "A hand-drawn sketch is acceptable for the demonstration.",
    },
]


def publish(
    client: Client, app_id: str, etag: str, body: dict[str, Any], *, key: str | None = None
) -> Any:
    return client.post(
        f"/api/v1/applications/{app_id}/notices",
        data=body,
        content_type=JSON,
        headers=cmd(etag=etag, key=key),
    )


def info_notice_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "INFORMATION",
        "public_reason": "The submitted ownership proof cannot be read; one clarification.",
        "internal_note": "Applicant called the desk on Monday; second copy expected.",
        "items": INFO_ITEMS,
    }
    body.update(over)
    return body


def upload_response_evidence(client: Client, notice_id: str, code: str, data: bytes) -> Any:
    reserved = reserve(
        client, notice_id, code, data, target_type="NOTICE_RESPONSE", original_name="reply.pdf"
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


def respond(
    client: Client,
    notice: dict[str, Any],
    etag: str,
    responses: list[dict[str, Any]],
    *,
    app_version: int | None = None,
    key: str | None = None,
) -> Any:
    return client.post(
        f"/api/v1/notices/{notice['notice_id']}/responses",
        data={
            "application_version": app_version
            if app_version is not None
            else notice["application_version"],
            "responses": responses,
            "declaration_accepted": True,
        },
        content_type=JSON,
        headers=cmd(etag=etag, key=key),
    )


def item_by_code(notice: dict[str, Any], code: str) -> dict[str, Any]:
    return next(i for i in notice["items"] if i["code"] == code)


@pytest.fixture
def info_round(
    applicant: Principal,
    supervisor: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> dict[str, Any]:
    """A case in SCRUTINY with one published INFORMATION notice (round 1)."""
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    detail = boss.get(f"/api/v1/applications/{app_id}")
    published = publish(boss, app_id, detail["ETag"], info_notice_body())
    assert published.status_code == 201, published.content
    notice = published.json()["data"]
    view = client.get(f"/api/v1/notices/{notice['notice_id']}")
    return {
        "applicant": client,
        "boss": boss,
        "app_id": app_id,
        "notice": view.json()["data"],
        "etag": view["ETag"],
        "case_etag": published["ETag"],
    }


@pytest.mark.django_db
def test_at_15_01_16_01_information_round_response_review_and_acceptance(
    info_round: dict[str, Any], clock: FrozenClock, supervisor: Principal
) -> None:
    r = info_round
    client, boss, app_id, notice = r["applicant"], r["boss"], r["app_id"], r["notice"]
    # TR-03: one published notice with actionable items; internal note hidden from the applicant.
    app = Application.objects.get(pk=app_id)
    assert app.status == "INFO_REQUIRED" and notice["round_number"] == 1
    assert notice["type"] == "INFORMATION" and notice["state"] == "PUBLISHED"
    assert "internal_note" not in notice and [i["code"] for i in notice["items"]] == [
        "INFO-01",
        "INFO-02",
    ]
    assert notice["due_at"] == (clock.now() + timedelta(minutes=10080)).isoformat()
    kinds = {o.kind: o for o in Obligation.objects.filter(application=app)}
    assert kinds["SCRUTINY_TASK"].state == "SATISFIED"
    assert (
        kinds["APPLICANT_RESPONSE"].state == "ACTIVE"
        and kinds["APPLICANT_RESPONSE"].responsible_principal_id == app.applicant_id
    )
    assert kinds["CASE_TARGET"].state == "ACTIVE"
    actions = {a["key"]: a for a in notice["allowed_actions"]}
    assert actions["respond"]["enabled"] is True and actions["review-item"]["enabled"] is False
    staff_view = boss.get(f"/api/v1/notices/{notice['notice_id']}").json()["data"]
    assert staff_view["internal_note"].startswith("Applicant called")
    listing = client.get(f"/api/v1/applications/{app_id}/notices").json()["data"]["items"]
    assert len(listing) == 1 and listing[0]["open_items"] == 2
    case = client.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert case["notices"][0]["state"] == "PUBLISHED" and case["findings_summary"] is None

    # FR-16: evidence through the NOTICE_RESPONSE target, scanned, then a per-item response.
    done = upload_response_evidence(client, notice["notice_id"], "response-info-01", PDF + b"own")
    assert done.status_code == 202
    run_worker(clock)
    doc_id = done.json()["data"]["document_version_id"]
    assert DocumentVersion.objects.get(pk=doc_id).scan_state == "CLEAN"
    info1 = item_by_code(notice, "INFO-01")
    first = respond(
        client,
        notice,
        r["etag"],
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "Attached a scanned, legible copy of all three pages.",
                "document_version_ids": [doc_id],
            }
        ],
    )
    assert first.status_code == 201, first.content
    receipt = first.json()["data"]
    assert receipt["responses"][0]["number"] == 1 and receipt["responses"][0]["item_state"] == (
        "RESPONSE_RECEIVED"
    )
    assert first["ETag"] == f'"notice:{notice["notice_id"]}:v2"'
    # A response never closes anything: the item waits for review, the case stays INFO_REQUIRED.
    assert Application.objects.get(pk=app_id).status == "INFO_REQUIRED"
    assert NoticeItem.objects.get(pk=info1["notice_item_id"]).state == "RESPONSE_RECEIVED"
    events = [
        e["event_type"]
        for e in client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "notice.published.v1" in events and "notice.response_received.v1" in events
    # A second revision is permitted and keeps the first one.
    second = respond(
        client,
        notice,
        first["ETag"],
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "Also adding the registry extract for completeness.",
                "document_version_ids": [doc_id],
            }
        ],
    )
    assert second.status_code == 201 and second.json()["data"]["responses"][0]["number"] == 2
    assert ResponseRevision.objects.filter(notice_item_id=info1["notice_item_id"]).count() == 2

    # TR-04 is blocked until the required item is reviewed and accepted.
    current = boss.get(f"/api/v1/notices/{notice['notice_id']}")
    blocked = boss.post(
        f"/api/v1/notices/{notice['notice_id']}/accept-information",
        data={"reason": "All information now on file"},
        content_type=JSON,
        headers=cmd(etag=current["ETag"]),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "RESPONSE_NOT_VERIFIED"
    assert blocked.json()["pending_items"] == ["INFO-01"]
    item = item_by_code(current.json()["data"], "INFO-01")
    stale = boss.post(
        f"/api/v1/notice-items/{item['notice_item_id']}/review",
        data={
            "application_version": current.json()["data"]["application_version"],
            "response_revision_id": item["responses"][0]["response_revision_id"],
            "outcome": "ACCEPTED",
            "reason": "Legible copy received and matches the registry",
        },
        content_type=JSON,
        headers=cmd(etag=f'"notice_item:{item["notice_item_id"]}:v{item["version"]}"'),
    )
    assert stale.status_code == 422 and stale.json()["violations"][0]["pointer"] == (
        "/response_revision_id"
    )
    accepted = boss.post(
        f"/api/v1/notice-items/{item['notice_item_id']}/review",
        data={
            "application_version": current.json()["data"]["application_version"],
            "response_revision_id": item["current_response_id"],
            "outcome": "ACCEPTED",
            "reason": "Legible copy received and matches the registry",
        },
        content_type=JSON,
        headers=cmd(etag=f'"notice_item:{item["notice_item_id"]}:v{item["version"]}"'),
    )
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["data"]["state"] == "ACCEPTED"
    current = boss.get(f"/api/v1/notices/{notice['notice_id']}")
    assert {a["key"]: a["enabled"] for a in current.json()["data"]["allowed_actions"]}[
        "accept-information"
    ] is True
    done_round = boss.post(
        f"/api/v1/notices/{notice['notice_id']}/accept-information",
        data={"reason": "All information now on file"},
        content_type=JSON,
        headers=cmd(etag=current["ETag"]),
    )
    assert done_round.status_code == 200, done_round.content
    body = done_round.json()["data"]
    assert body["state"] == "SATISFIED" and body["application_status"] == "SCRUTINY"
    app.refresh_from_db()
    assert app.status == "SCRUTINY"
    stages = list(
        StageInstance.objects.filter(application=app)
        .order_by("cycle_number")
        .values_list("state", flat=True)
    )
    assert stages[-3:] == ["SCRUTINY", "INFO_REQUIRED", "SCRUTINY"]
    obligations = list(Obligation.objects.filter(application=app).order_by("created_at"))
    by_kind: dict[str, list[Obligation]] = {}
    for o in obligations:
        by_kind.setdefault(o.kind, []).append(o)
    assert [o.state for o in by_kind["SCRUTINY_TASK"]] == ["SATISFIED", "ACTIVE"]
    assert by_kind["APPLICANT_RESPONSE"][0].state == "SATISFIED"
    assert by_kind["CASE_TARGET"][0].state == "ACTIVE"  # the case clock never restarted
    public = [
        e["event_type"]
        for e in client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "information.accepted.v1" in public and "notice.item_reviewed.v1" in public
    assert "scrutiny.note.v1" not in public
    assert AuditEvent.objects.filter(action="notice.published").exists()
    assert OutboxMessage.objects.filter(event_type="notice.response_received.v1").count() == 2
    # The satisfied notice refuses further responses.
    closed = respond(
        client,
        notice,
        done_round["ETag"],
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "One more document after the fact",
                "document_version_ids": [],
            }
        ],
        app_version=app.version,
    )
    assert closed.status_code == 409 and closed.json()["code"] == "NOTICE_NOT_OPEN"


@pytest.mark.django_db
def test_at_15_02_15_04_15_05_invalid_notices_authorisation_and_replay(
    applicant: Principal,
    other_applicant: Principal,
    supervisor: Principal,
    plain_supervisor: Principal,
    foreign_supervisor: Principal,
    staff: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    etag = boss.get(f"/api/v1/applications/{app_id}")["ETag"]

    def expect_422(body: dict[str, Any], pointer: str) -> None:
        response = publish(boss, app_id, etag, body)
        assert response.status_code == 422, response.content
        assert any(v["pointer"] == pointer for v in response.json()["violations"]), response.json()[
            "violations"
        ]

    expect_422(info_notice_body(items=[]), "/items")
    expect_422(info_notice_body(public_reason="short"), "/public_reason")
    expect_422(info_notice_body(items=[INFO_ITEMS[0], INFO_ITEMS[0]]), "/items/1/code")
    expect_422(
        info_notice_body(items=[{**INFO_ITEMS[0], "acceptable_evidence_types": ["MAGIC"]}]),
        "/items/0/acceptable_evidence_types",
    )
    expect_422(
        info_notice_body(items=[{**INFO_ITEMS[0], "finding_id": str(uuid4())}]),
        "/items/0/finding_id",
    )
    expect_422(
        info_notice_body(proposed_response_budget_minutes=99999999),
        ("/proposed_response_budget_minutes"),
    )
    expect_422(info_notice_body(type="DEFICIENCY"), "/items/0/finding_id")
    assert not Notice.objects.exists()
    # Authorisation: a supervisor without the capability, a foreign supervisor, a clerk without
    # roles and the applicant all fail without side effects.
    plain = signed_client(plain_supervisor)
    denied = publish(plain, app_id, etag, info_notice_body())
    assert denied.status_code == 403 and denied.json()["code"] in (
        "FORBIDDEN",
        "AUTHORITY_SCOPE_MISMATCH",
    )
    assert (
        publish(signed_client(foreign_supervisor), app_id, etag, info_notice_body()).status_code
        == 404
    )
    assert publish(signed_client(staff), app_id, etag, info_notice_body()).status_code == 403
    assert publish(client, app_id, etag, info_notice_body()).status_code == 403
    assert not Notice.objects.exists()
    # Replay: the same logical command yields one notice; a new key from INFO_REQUIRED is 409.
    key = str(uuid4())
    first = publish(boss, app_id, etag, info_notice_body(), key=key)
    again = publish(boss, app_id, etag, info_notice_body(), key=key)
    assert first.status_code == 201 and again.status_code == 201
    assert again.json()["data"]["replayed"] is True
    assert Notice.objects.filter(application_id=app_id).count() == 1
    second = publish(boss, app_id, first["ETag"], info_notice_body())
    assert second.status_code == 409 and second.json()["code"] == "INVALID_TRANSITION"
    stale = publish(boss, app_id, etag, info_notice_body())
    assert stale.status_code == 412
    # Reads are scoped: another applicant and the foreign supervisor see nothing.
    notice_id = first.json()["data"]["notice_id"]
    assert signed_client(other_applicant).get(f"/api/v1/notices/{notice_id}").status_code == 404
    assert signed_client(foreign_supervisor).get(f"/api/v1/notices/{notice_id}").status_code == 404
    assert (
        signed_client(other_applicant).get(f"/api/v1/applications/{app_id}/notices").status_code
        == 404
        or signed_client(other_applicant)
        .get(f"/api/v1/applications/{app_id}/notices")
        .json()["data"]["items"]
        == []
    )


@pytest.mark.django_db
def test_at_15_03_superseding_notice_retains_original_and_its_clock_disposition(
    info_round: dict[str, Any], clock: FrozenClock
) -> None:
    r = info_round
    boss, client, app_id, notice = r["boss"], r["applicant"], r["app_id"], r["notice"]
    corrected = publish(
        boss,
        app_id,
        r["case_etag"],
        info_notice_body(
            public_reason="Corrected notice: the second item was listed in error.",
            items=[INFO_ITEMS[0]],
            supersedes_notice_id=notice["notice_id"],
        ),
    )
    assert corrected.status_code == 201, corrected.content
    body = corrected.json()["data"]
    assert body["round_number"] == 2 and body["supersedes_id"] == notice["notice_id"]
    assert body["application_status"] == "INFO_REQUIRED"
    original = Notice.objects.get(pk=notice["notice_id"])
    assert original.state == "SUPERSEDED" and original.public_reason == notice["public_reason"]
    assert original.due_obligation is not None and original.due_obligation.state == "CANCELLED"
    successor = Notice.objects.get(pk=body["notice_id"])
    assert successor.due_obligation is not None and successor.due_obligation.state == "ACTIVE"
    view = client.get(f"/api/v1/notices/{notice['notice_id']}").json()["data"]
    assert view["superseded_by_id"] == body["notice_id"]
    assert {a["key"]: a for a in view["allowed_actions"]}["respond"]["reason_code"] == (
        "NOTICE_NOT_OPEN"
    )
    # Responding to the superseded round is refused; the new round accepts.
    old_item = item_by_code(notice, "INFO-01")
    refused = respond(
        client,
        {**notice, "application_version": body["application_version"]},
        f'"notice:{notice["notice_id"]}:v{original.version}"',
        [
            {
                "notice_item_id": old_item["notice_item_id"],
                "explanation": "Responding to the withdrawn notice",
                "document_version_ids": [],
            }
        ],
    )
    assert refused.status_code == 409 and refused.json()["code"] == "NOTICE_NOT_OPEN"
    new_view = client.get(f"/api/v1/notices/{body['notice_id']}")
    new_item = item_by_code(new_view.json()["data"], "INFO-01")
    ok = respond(
        client,
        new_view.json()["data"],
        new_view["ETag"],
        [
            {
                "notice_item_id": new_item["notice_item_id"],
                "explanation": "Written explanation: the deed is held by the bank.",
                "document_version_ids": [],
            }
        ],
    )
    assert ok.status_code == 201, ok.content
    assert Notice.objects.filter(application_id=app_id).count() == 2


@pytest.mark.django_db
def test_at_16_02_16_04_unrelated_or_quarantined_evidence_and_wrong_actors_are_refused(
    info_round: dict[str, Any],
    other_applicant: Principal,
    supervisor: Principal,
    service: Service,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    r = info_round
    client, boss, app_id, notice = r["applicant"], r["boss"], r["app_id"], r["notice"]
    info1 = item_by_code(notice, "INFO-01")

    def expect_422(responses: list[dict[str, Any]], pointer: str, code: str) -> None:
        response = respond(client, notice, r["etag"], responses)
        assert response.status_code == 422, response.content
        assert any(
            v["pointer"] == pointer and v["code"] == code for v in response.json()["violations"]
        ), response.json()["violations"]

    quarantined = upload_response_evidence(
        client, notice["notice_id"], "response-info-01", PDF + b"pending"
    ).json()["data"]["document_version_id"]
    expect_422(
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "Attached before the scan finished",
                "document_version_ids": [quarantined],
            }
        ],
        "/responses/0/document_version_ids/0",
        "not_clean_case_evidence",
    )
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
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "Evidence borrowed from another case",
                "document_version_ids": [foreign_doc],
            }
        ],
        "/responses/0/document_version_ids/0",
        "not_clean_case_evidence",
    )
    expect_422(
        [
            {
                "notice_item_id": str(uuid4()),
                "explanation": "Not an item of this notice at all",
                "document_version_ids": [],
            }
        ],
        "/responses/0/notice_item_id",
        "unknown",
    )
    expect_422(
        [
            {
                "notice_item_id": info1["notice_item_id"],
                "explanation": "short",
                "document_version_ids": [],
            }
        ],
        "/responses/0/explanation",
        "length",
    )
    # Upload targets: the wrong item code and a stranger's notice are refused.
    bad_code = reserve(
        client, notice["notice_id"], "response-zzz", PDF, target_type="NOTICE_RESPONSE"
    )
    assert bad_code.status_code == 422
    assert (
        upload_response_evidence(
            signed_client(other_applicant), notice["notice_id"], "response-info-01", PDF
        ).status_code
        == 404
    )
    # Wrong actors: staff cannot respond; another applicant learns nothing.
    payload = [
        {
            "notice_item_id": info1["notice_item_id"],
            "explanation": "Attempt by the wrong actor",
            "document_version_ids": [],
        }
    ]
    assert respond(boss, notice, r["etag"], payload).status_code == 403
    assert respond(signed_client(other_applicant), notice, r["etag"], payload).status_code == 404
    assert respond(client, notice, '"notice:x:v9"', payload).status_code == 412
    assert not ResponseRevision.objects.exists()
    assert Application.objects.get(pk=app_id).status == "INFO_REQUIRED"


@pytest.mark.django_db
def test_at_17_01_17_02_deficiency_cycle_verified_closure_and_complete_corrections(
    visit: dict[str, Any],  # noqa: F811 - pytest fixture imported from test_reports
    clock: FrozenClock,
    officers: dict[str, Principal],
) -> None:
    v = visit
    priya, boss, client, app_id = v["priya"], v["boss"], v["applicant"], v["app_id"]
    evidence = clean_evidence(v, clock)
    observations = [
        observation(
            "C01", "FAIL", "Rear escape route padlocked and stacked with cartons", docs=[evidence]
        ),
        observation("C02", "PASS", docs=[evidence]),
        observation("C07", "FAIL", "Access lane partly blocked by a parked skip"),
    ]
    accepted = submit(
        priya,
        v,
        submit_body(v["detail"], observations, summary="Two failures recorded; see items."),
    )
    assert accepted.status_code == 201, accepted.content
    report_id = accepted.json()["data"]["receipt"]["report_id"]
    # Findings were materialised with the accepted report.
    findings = boss.get(f"/api/v1/applications/{app_id}/findings").json()["data"]["items"]
    by_code = {f["checklist_item_code"]: f for f in findings}
    assert by_code["C01"]["severity"] == "MANDATORY" and by_code["C07"]["severity"] == "ADVISORY"
    assert all(f["state"] == "OPEN" for f in findings) and len(findings) == 2
    applicant_findings = client.get(f"/api/v1/applications/{app_id}/findings").json()["data"][
        "items"
    ]
    assert applicant_findings and "closure_evidence" not in applicant_findings[0]

    # TR-07: deficiency notice itemising the findings.
    case = boss.get(f"/api/v1/applications/{app_id}")
    assert {a["key"]: a["enabled"] for a in case.json()["data"]["allowed_actions"]}[
        "issue-deficiencies"
    ] is True
    deficiency = publish(
        boss,
        app_id,
        case["ETag"],
        {
            "type": "DEFICIENCY",
            "public_reason": "The site inspection recorded two deficiencies that need correction.",
            "items": [
                {
                    "code": "DEF-C01",
                    "title": "Clear and unlock the rear escape route",
                    "description": "Remove stored cartons; keep the rear exit unlocked.",
                    "required": True,
                    "finding_id": by_code["C01"]["finding_id"],
                    "acceptable_evidence_types": ["PHOTOGRAPH", "WRITTEN_EXPLANATION"],
                },
                {
                    "code": "DEF-C07",
                    "title": "Keep the access lane clear",
                    "description": "Arrange removal of the skip or move it off the access lane.",
                    "required": False,
                    "finding_id": by_code["C07"]["finding_id"],
                    "acceptable_evidence_types": ["PHOTOGRAPH"],
                },
            ],
        },
    )
    assert deficiency.status_code == 201, deficiency.content
    notice = deficiency.json()["data"]
    assert notice["type"] == "DEFICIENCY" and notice["application_status"] == "COMPLIANCE_PENDING"
    app = Application.objects.get(pk=app_id)
    kinds = {o.kind: o for o in Obligation.objects.filter(application=app)}
    assert (
        kinds["REVIEW_TASK"].state == "SATISFIED" and kinds["APPLICANT_RESPONSE"].state == "ACTIVE"
    )
    case_due = kinds["CASE_TARGET"].due_at

    # AT-17-02: the applicant's response alone does not close the mandatory finding.
    view = client.get(f"/api/v1/notices/{notice['notice_id']}")
    item_c01 = item_by_code(view.json()["data"], "DEF-C01")
    photo = upload_response_evidence(
        client, notice["notice_id"], "response-def-c01", PDF + b"photo"
    )
    run_worker(clock)
    photo_id = photo.json()["data"]["document_version_id"]
    responded = respond(
        client,
        view.json()["data"],
        view["ETag"],
        [
            {
                "notice_item_id": item_c01["notice_item_id"],
                "explanation": "Cartons removed and padlock taken off; photo attached.",
                "document_version_ids": [photo_id],
            }
        ],
    )
    assert responded.status_code == 201, responded.content
    finding = Finding.objects.get(pk=by_code["C01"]["finding_id"])
    assert finding.state == "RESPONSE_RECEIVED" and finding.closed_at is None
    blocked = boss.post(
        f"/api/v1/applications/{app_id}/complete-corrections",
        data={"reason": "Applicant says it is fixed"},
        content_type=JSON,
        headers=cmd(etag=boss.get(f"/api/v1/applications/{app_id}")["ETag"]),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "MANDATORY_FINDINGS_OPEN"
    assert blocked.json()["open_mandatory"] == ["C01"]
    # Accepting the item directly is refused while its finding is unverified.
    current = boss.get(f"/api/v1/notices/{notice['notice_id']}").json()["data"]
    item_c01 = item_by_code(current, "DEF-C01")
    early = boss.post(
        f"/api/v1/notice-items/{item_c01['notice_item_id']}/review",
        data={
            "application_version": current["application_version"],
            "response_revision_id": item_c01["current_response_id"],
            "outcome": "ACCEPTED",
            "reason": "Looks fixed on the photo",
        },
        content_type=JSON,
        headers=cmd(etag=f'"notice_item:{item_c01["notice_item_id"]}:v{item_c01["version"]}"'),
    )
    assert early.status_code == 409 and early.json()["code"] == "RESPONSE_NOT_VERIFIED"
    # The inspecting officer cannot verify (not a supervisor -> 404); a checkbox-only closure of a
    # MANDATORY finding is refused; reviewer-cited evidence closes it.
    finding_view = next(
        f
        for f in boss.get(f"/api/v1/applications/{app_id}/findings").json()["data"]["items"]
        if f["checklist_item_code"] == "C01"
    )
    verify_url = f"/api/v1/findings/{finding_view['finding_id']}/verify"
    base = {
        "application_version": current["application_version"],
        "response_revision_id": item_c01["current_response_id"],
        "reason": "Photo shows the rear exit clear and unlocked; verified against the report.",
    }
    assert (
        priya.post(
            verify_url,
            data={**base, "outcome": "VERIFIED_CLOSED"},
            content_type=JSON,
            headers=cmd(etag=finding_view["etag"]),
        ).status_code
        == 403
    )
    checkbox_only = boss.post(
        verify_url,
        data={**base, "outcome": "VERIFIED_CLOSED"},
        content_type=JSON,
        headers=cmd(etag=finding_view["etag"]),
    )
    assert checkbox_only.status_code == 422
    assert checkbox_only.json()["violations"][0]["code"] == "verification_basis_required"
    # Return with a public reason keeps the reply and reopens the finding.
    returned = boss.post(
        verify_url,
        data={
            **base,
            "outcome": "RETURNED",
            "reason": "Photo does not show the padlock removed; please re-shoot.",
        },
        content_type=JSON,
        headers=cmd(etag=finding_view["etag"]),
    )
    assert returned.status_code == 200 and returned.json()["data"]["state"] == "OPEN"
    item_state = NoticeItem.objects.get(pk=item_c01["notice_item_id"])
    assert item_state.state == "RETURNED" and item_state.reviewer_feedback.startswith(
        "Photo does not"
    )
    assert ResponseRevision.objects.filter(notice_item_id=item_c01["notice_item_id"]).count() == 1
    # New response revision, then verified closure citing the reviewer-checked evidence.
    view = client.get(f"/api/v1/notices/{notice['notice_id']}")
    again = respond(
        client,
        view.json()["data"],
        view["ETag"],
        [
            {
                "notice_item_id": item_c01["notice_item_id"],
                "explanation": "Second photo from the corridor showing the open, unlocked door.",
                "document_version_ids": [photo_id],
            }
        ],
    )
    assert again.status_code == 201 and again.json()["data"]["responses"][0]["number"] == 2
    finding_view = next(
        f
        for f in boss.get(f"/api/v1/applications/{app_id}/findings").json()["data"]["items"]
        if f["checklist_item_code"] == "C01"
    )
    closed = boss.post(
        verify_url,
        data={
            **base,
            "application_version": Application.objects.get(pk=app_id).version,
            "response_revision_id": finding_view["current_response_id"],
            "outcome": "VERIFIED_CLOSED",
            "evidence_document_ids": [photo_id],
        },
        content_type=JSON,
        headers=cmd(etag=finding_view["etag"]),
    )
    assert closed.status_code == 200, closed.content
    body = closed.json()["data"]
    assert (
        body["state"] == "VERIFIED_CLOSED"
        and body["closure_evidence"]["evidence_documents"][0]["document_version_id"] == photo_id
    )
    assert NoticeItem.objects.get(pk=item_c01["notice_item_id"]).state == "ACCEPTED"
    twice = boss.post(
        verify_url,
        data={
            **base,
            "application_version": Application.objects.get(pk=app_id).version,
            "response_revision_id": finding_view["current_response_id"],
            "outcome": "VERIFIED_CLOSED",
            "evidence_document_ids": [photo_id],
        },
        content_type=JSON,
        headers=cmd(etag=closed["ETag"]),
    )
    assert twice.status_code == 409, twice.content
    # TR-08 with the advisory finding still open: allowed (only MANDATORY findings gate it).
    case = boss.get(f"/api/v1/applications/{app_id}")
    assert {a["key"]: a["enabled"] for a in case.json()["data"]["allowed_actions"]}[
        "complete-corrections"
    ] is True
    completed = boss.post(
        f"/api/v1/applications/{app_id}/complete-corrections",
        data={"reason": "Mandatory deficiency verified closed on site photos"},
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert completed.status_code == 200, completed.content
    assert completed.json()["data"]["status"] == "REVIEW_PENDING"
    app.refresh_from_db()
    assert app.status == "REVIEW_PENDING"
    assert Notice.objects.get(pk=notice["notice_id"]).state == "SATISFIED"
    kinds_after: dict[str, list[str]] = {}
    for o in Obligation.objects.filter(application=app).order_by("created_at"):
        kinds_after.setdefault(o.kind, []).append(o.state)
    assert kinds_after["REVIEW_TASK"] == ["SATISFIED", "ACTIVE"]
    assert kinds_after["APPLICANT_RESPONSE"] == ["SATISFIED"]
    assert Obligation.objects.get(application=app, kind="CASE_TARGET").due_at == case_due
    public = [
        e["event_type"]
        for e in client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "deficiencies.published.v1" in public and "finding.reviewed.v1" in public
    assert "compliance.verified.v1" in public
    staff_case = boss.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert staff_case["findings_summary"] == {
        "open_mandatory": 0,
        "open_advisory": 1,
        "verified_closed": 1,
        "reinspection_outstanding": [],
    }
    assert Finding.objects.get(
        pk=by_code["C01"]["finding_id"]
    ).originating_report_id.hex == report_id.replace("-", "")


@pytest.mark.django_db
def test_at_17_03_reinspection_creates_linked_attempt_and_blocks_completion(
    visit: dict[str, Any],  # noqa: F811
    clock: FrozenClock,
    officers: dict[str, Principal],
) -> None:
    v = visit
    priya, boss, app_id = v["priya"], v["boss"], v["app_id"]
    evidence = clean_evidence(v, clock)
    accepted = submit(
        priya,
        v,
        submit_body(
            v["detail"],
            [
                observation(
                    "C01", "FAIL", "Escape route obstructed by stored stock", docs=[evidence]
                ),
                *all_pass(evidence)[1:],
            ],
            summary="One mandatory failure; reinspection likely.",
        ),
    )
    assert accepted.status_code == 201, accepted.content
    finding = Finding.objects.get(application_id=app_id, checklist_item_code="C01")
    case = boss.get(f"/api/v1/applications/{app_id}")
    deficiency = publish(
        boss,
        app_id,
        case["ETag"],
        {
            "type": "DEFICIENCY",
            "public_reason": "Escape route must be cleared before a certificate is considered.",
            "items": [
                {
                    "code": "DEF-C01",
                    "title": "Clear the escape route",
                    "description": "Remove stored stock from the rear escape route permanently.",
                    "required": True,
                    "finding_id": str(finding.pk),
                    "acceptable_evidence_types": ["PHOTOGRAPH"],
                }
            ],
        },
    )
    assert deficiency.status_code == 201, deficiency.content
    case_due = Obligation.objects.get(application_id=app_id, kind="CASE_TARGET").due_at
    # Reviewer decides a physical reinspection is needed (API-060) then requires it (TR-09).
    finding_view = boss.get(f"/api/v1/applications/{app_id}/findings").json()["data"]["items"][0]
    flagged = boss.post(
        f"/api/v1/findings/{finding.pk}/verify",
        data={
            "application_version": Application.objects.get(pk=app_id).version,
            "response_revision_id": None,
            "outcome": "REINSPECTION_REQUIRED",
            "reason": "Structural change to the corridor must be seen on site.",
        },
        content_type=JSON,
        headers=cmd(etag=finding_view["etag"]),
    )
    assert flagged.status_code == 200 and flagged.json()["data"]["reinspection_required"] is True
    case = boss.get(f"/api/v1/applications/{app_id}")
    blocked = boss.post(
        f"/api/v1/applications/{app_id}/complete-corrections",
        data={"reason": "Trying to skip the reinspection"},
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert blocked.status_code == 409 and blocked.json()["reinspection_outstanding"] == ["C01"]
    bad = boss.post(
        f"/api/v1/applications/{app_id}/reinspect",
        data={
            "finding_ids": [str(uuid4())],
            "reason": "Unknown finding reference",
            "previous_inspection_id": v["inspection_id"],
        },
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert bad.status_code == 422
    reinspect = boss.post(
        f"/api/v1/applications/{app_id}/reinspect",
        data={
            "finding_ids": [str(finding.pk)],
            "reason": "Reinspection of the rear escape route after the corridor works.",
            "previous_inspection_id": v["inspection_id"],
        },
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert reinspect.status_code == 201, reinspect.content
    attempt = reinspect.json()["data"]
    assert attempt["purpose"] == "REINSPECTION" and attempt["attempt_number"] == 2
    assert (
        attempt["parent_inspection_id"] == v["inspection_id"] and attempt["status"] == "REQUESTED"
    )
    assert attempt["checklist_ref"] == v["detail"]["checklist_ref"]
    app = Application.objects.get(pk=app_id)
    assert app.status == "INSPECTION_PENDING"
    assert Inspection.objects.filter(application=app).count() == 2
    assert Obligation.objects.get(application=app, kind="CASE_TARGET").due_at == case_due
    assert (
        Obligation.objects.filter(application=app, kind="INSPECTION_TASK", state="ACTIVE").count()
        == 1
    )
    assert Notice.objects.get(pk=deficiency.json()["data"]["notice_id"]).state == "PUBLISHED"
    public = [
        e["event_type"]
        for e in v["applicant"]
        .get(f"/api/v1/applications/{app_id}/timeline")
        .json()["data"]["items"]
    ]
    assert "inspection.reinspection_requested.v1" in public
    # A second reinspection request from INSPECTION_PENDING is refused; nothing duplicated.
    again = boss.post(
        f"/api/v1/applications/{app_id}/reinspect",
        data={
            "finding_ids": [str(finding.pk)],
            "reason": "Duplicate reinspection request",
            "previous_inspection_id": v["inspection_id"],
        },
        content_type=JSON,
        headers=cmd(etag=reinspect["ETag"]),
    )
    assert again.status_code == 409 and Inspection.objects.filter(application=app).count() == 2
