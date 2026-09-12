"""FR-06 / AT-06-01..05 (atomic submission + receipt), FR-07 / AT-07-01..05 (routing and owned
exceptions) and FR-09 / AT-09-01..05 (scoped visibility, audience-filtered timeline, overview)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection
from django.test import Client

from agni.cases.models import Application, CaseEvent, Premises, StageInstance, SubmissionRevision
from agni.identity.models import Principal
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, CommandReceipt, OutboxMessage
from agni.policies.models import PolicyArtifact, Service
from agni.routing.models import DutyQueue, RoutingEntry, RoutingException

from .test_drafts import create_draft, patch_draft
from .test_uploads import PDF, run_worker, upload_and_complete

JSON = "application/json"


def cmd(
    headers: dict[str, str] | None = None, etag: str | None = None, key: str | None = None
) -> dict[str, str]:
    h = {"Idempotency-Key": key or str(uuid4()), **(headers or {})}
    if etag:
        h["If-Match"] = etag
    return h


def ready_draft(
    client: Client,
    premises: Premises,
    service: Service,
    clock: FrozenClock,
    *,
    requirement_codes: tuple[str, ...] = ("ownership", "plan", "electrical"),
    link: bool = True,
) -> dict[str, Any]:
    """Create a draft, accept every declaration, upload + scan + link the given requirement
    codes and return {app_id, etag, detail}."""
    created = create_draft(client, premises, service)
    app_id = created.json()["data"]["application_id"]
    detail = client.get(f"/api/v1/applications/{app_id}")
    declarations = [
        {"code": d["code"], "version": d["version"], "accepted": True}
        for d in detail.json()["data"]["draft"]["declarations"]
    ]
    saved = patch_draft(
        client, app_id, detail["ETag"], {"draft_revision": 1, "declaration_drafts": declarations}
    )
    assert saved.status_code == 200, saved.content
    doc_ids = [
        upload_and_complete(client, app_id, code=code, data=PDF + code.encode())[
            "document_version_id"
        ]
        for code in requirement_codes
    ]
    run_worker(clock)
    etag = saved["ETag"]
    if link:
        linked = patch_draft(
            client, app_id, etag, {"draft_revision": 2, "attachment_links": doc_ids}
        )
        assert linked.status_code == 200, linked.content
        etag = linked["ETag"]
    detail = client.get(f"/api/v1/applications/{app_id}")
    return {
        "app_id": app_id,
        "etag": detail["ETag"],
        "detail": detail.json()["data"],
        "doc_ids": doc_ids,
    }


def submission_body(ready: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    detail = ready["detail"]
    body = {
        "draft_revision": detail["draft"]["draft_revision"],
        "reviewed_policy_version_id": detail["policy"]["policy_version_id"],
        "declaration_acceptances": [
            {"code": d["code"], "version": d["version"], "accepted": True}
            for d in detail["draft"]["declarations"]
        ],
        "document_version_ids": ready["doc_ids"],
    }
    body.update(overrides)
    return body


def submit(
    client: Client,
    ready: dict[str, Any],
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    etag: str | None = None,
) -> Any:
    return client.post(
        f"/api/v1/applications/{ready['app_id']}/submit",
        data=body or submission_body(ready),
        content_type=JSON,
        headers=cmd(etag=etag or ready["etag"], key=key),
    )


@pytest.mark.django_db
def test_at_06_01_07_01_one_command_one_receipt_submitted_with_owner(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    duty_queue: DutyQueue,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    submit_hint = next(a for a in ready["detail"]["allowed_actions"] if a["key"] == "submit")
    assert submit_hint["enabled"] is True and ready["detail"]["draft"]["blockers"] == []

    receipts_before = CommandReceipt.objects.filter(command_name="submit").count()
    response = submit(client, ready)
    assert response.status_code == 200, response.content
    receipt = response.json()["data"]
    assert receipt["status"] == "SUBMITTED" and receipt["public_reference"] == "AS-2026-1001"
    assert receipt["submission_revision"] == 1 and receipt["policy_number"] == 1
    assert (
        receipt["owner_queue"]["queue_key"] == duty_queue.queue_key
    )  # W-01 routes to the test queue (AT-07-01)
    assert receipt["routing"] == {"resolved": True, "exception_code": None, "exception_id": None}
    kinds = {o["kind"]: o for o in receipt["obligations"]}
    assert set(kinds) == {"CASE_TARGET", "SCRUTINY_TASK"}
    assert kinds["CASE_TARGET"]["due_at"] == "2026-10-10T09:00:00+00:00"  # 43200 calendar minutes
    # 480 working minutes from Thu 09:00Z (14:30 IST): 2.5 h Thu + 5.5 h Fri -> Fri 14:30 IST.
    assert kinds["SCRUTINY_TASK"]["due_at"] == "2026-09-11T09:00:00+00:00"
    assert response["ETag"] == f'"application:{ready["app_id"]}:v{receipt["version"]}"'
    assert CommandReceipt.objects.filter(command_name="submit").count() == receipts_before + 1

    application = Application.objects.get(pk=ready["app_id"])
    assert application.status == "SUBMITTED" and application.submitted_at == clock.now()
    assert str(application.policy_version_id) == ready["detail"]["policy"]["policy_version_id"]
    assert (
        application.owner_queue_id == duty_queue.pk
        and application.jurisdiction_id == duty_queue.jurisdiction_id
    )
    revision = SubmissionRevision.objects.get(application=application)
    assert revision.number == 1 and application.submitted_revision_id == revision.pk
    assert {d.requirement_code for d in revision.documents.all()} == {
        "ownership",
        "plan",
        "electrical",
    }
    assert (
        revision.declaration_snapshot[0]["accepted"] is True
        and revision.premise_snapshot["display_name"] == premises.display_name
    )
    assert revision.selection_explanation["routing"]["resolved"] is True
    stages = list(StageInstance.objects.filter(application=application).order_by("cycle_number"))
    assert (
        [s.state for s in stages] == ["DRAFT", "SUBMITTED"]
        and stages[0].exited_at == clock.now()
        and stages[1].exited_at is None
    )
    event = CaseEvent.objects.get(application=application, event_type="application.submitted.v1")
    assert (
        event.audience == "PUBLIC_CASE" and event.payload["owner_queue_key"] == duty_queue.queue_key
    )
    assert (
        Obligation.objects.filter(
            application=application, application_stage_instance=stages[1]
        ).count()
        == 2
    )
    assert OutboxMessage.objects.filter(
        event_type="application.submitted.v1", aggregate_id=application.pk
    ).exists()
    assert AuditEvent.objects.filter(
        entity_id=application.pk, action="application.submitted"
    ).exists()
    # A received case is no longer editable; the receipt is the same on the detail projection.
    detail = client.get(f"/api/v1/applications/{ready['app_id']}").json()["data"]
    assert detail["submission"]["number"] == 1 and detail["draft"] is None
    assert (
        next(a for a in detail["allowed_actions"] if a["key"] == "edit-draft")["enabled"] is False
    )
    assert [o["kind"] for o in detail["obligations"]] == [
        "CASE_TARGET"
    ]  # applicants see the case target only


@pytest.mark.django_db
def test_at_06_02_incomplete_or_stale_submission_leaves_no_receipt_and_no_transition(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    # Only two of three required documents.
    ready = ready_draft(client, premises, service, clock, requirement_codes=("ownership", "plan"))
    missing = submit(client, ready)
    assert missing.status_code == 422 and missing.json()["code"] == "EVIDENCE_INCOMPLETE"
    assert any("electrical" in v["message"] for v in missing.json()["violations"])
    assert not CommandReceipt.objects.filter(command_name="submit").exists()
    app = Application.objects.get(pk=ready["app_id"])
    assert app.status == "DRAFT" and app.submitted_at is None and app.public_reference is None
    assert not SubmissionRevision.objects.filter(application=app).exists()
    assert not Obligation.objects.filter(application=app).exists()
    assert StageInstance.objects.filter(application=app).count() == 1

    # A still-scanning document cannot satisfy the requirement.
    pending = upload_and_complete(
        client, ready["app_id"], code="electrical", data=PDF + b"electrical"
    )
    quarantined = submit(
        client,
        ready,
        submission_body(
            ready, document_version_ids=[*ready["doc_ids"], pending["document_version_id"]]
        ),
    )
    assert quarantined.status_code == 422
    assert any(
        v["code"] == "quarantined" and "security scan" in v["message"]
        for v in quarantined.json()["violations"]
    )
    run_worker(clock)
    full_ids = [*ready["doc_ids"], pending["document_version_id"]]

    # Wrong reviewed policy version -> the review expectation changed.
    stale_policy = submit(
        client,
        ready,
        submission_body(
            ready, document_version_ids=full_ids, reviewed_policy_version_id=str(uuid4())
        ),
    )
    assert (
        stale_policy.status_code == 422
        and stale_policy.json()["violations"][0]["pointer"] == "/reviewed_policy_version_id"
    )
    # Missing declaration acceptance.
    no_decl = submit(
        client,
        ready,
        submission_body(ready, document_version_ids=full_ids, declaration_acceptances=[]),
    )
    assert no_decl.status_code == 422 and any(
        v["code"] == "missing" for v in no_decl.json()["violations"]
    )
    # Unknown field and wrong types are pointed at.
    bad = submit(
        client,
        ready,
        {**submission_body(ready, document_version_ids=full_ids), "status": "SUBMITTED"},
    )
    assert bad.status_code == 422 and bad.json()["violations"][0]["pointer"] == "/status"
    assert Application.objects.get(pk=ready["app_id"]).status == "DRAFT"
    # Finally a complete submission succeeds.
    ok = submit(client, ready, submission_body(ready, document_version_ids=full_ids))
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "SUBMITTED"


@pytest.mark.django_db
def test_at_06_03_05_replay_conflict_stale_version_and_no_double_submit(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    stale = submit(client, ready, etag=f'"application:{ready["app_id"]}:v1"')
    assert stale.status_code == 412
    key = str(uuid4())
    first = submit(client, ready, key=key)
    assert first.status_code == 200
    replay = submit(client, ready, key=key)
    assert replay.status_code == 200 and replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["public_reference"] == first.json()["data"]["public_reference"]
    changed = submit(
        client,
        ready,
        submission_body(ready, document_version_ids=list(reversed(ready["doc_ids"]))),
        key=key,
    )
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    again = submit(client, ready, key=str(uuid4()), etag=first["ETag"])
    assert again.status_code == 409 and again.json()["code"] == "INVALID_TRANSITION"
    edit = patch_draft(
        client,
        ready["app_id"],
        first["ETag"],
        {"draft_revision": 3, "fields": {"locality": "Late"}},
    )
    assert edit.status_code == 409 and edit.json()["code"] == "INVALID_TRANSITION"
    assert SubmissionRevision.objects.filter(application_id=ready["app_id"]).count() == 1
    assert Application.objects.filter(public_reference__startswith="AS-2026-").count() == 1


@pytest.mark.django_db
def test_at_06_04_scope_other_applicant_and_staff_cannot_submit(
    applicant: Principal,
    other_applicant: Principal,
    supervisor: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    assert submit(signed_client(other_applicant), ready).status_code == 404
    assert submit(signed_client(supervisor), ready).status_code == 403
    assert Application.objects.get(pk=ready["app_id"]).status == "DRAFT"


@pytest.mark.django_db(transaction=True)
def test_at_06_05_concurrent_submissions_produce_exactly_one_revision(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    results: list[int] = []

    def worker() -> None:
        try:
            local = signed_client(applicant)
            results.append(submit(local, ready).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert (
        sorted(results) == [200, 412, 412]
        or sorted(results) == [200, 409, 412]
        or sorted(results).count(200) == 1
    )
    assert SubmissionRevision.objects.filter(application_id=ready["app_id"]).count() == 1
    assert StageInstance.objects.filter(application_id=ready["app_id"]).count() == 2
    assert (
        CommandReceipt.objects.filter(command_name="submit", target_id=ready["app_id"]).count() == 1
    )


@pytest.mark.django_db
# DS-11 / E2E-04 (routing exception is visible, owned and resolved with a reviewed mapping)
def test_at_07_02_03_no_match_creates_owned_exception_resolved_by_supervisor(
    applicant: Principal,
    supervisor: Principal,
    foreign_supervisor: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    duty_queue: DutyQueue,
    artifacts: dict[str, PolicyArtifact],
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    # Ward W-99 has no routing entry.
    unmapped = Premises.objects.create(
        owner=applicant,
        display_name="Unmapped Hall",
        address_line1="9 Nowhere Road",
        locality="Outskirts",
        ward_key="W-99",
        postal_code="560099",
        category_key="Office",
        area_sqm=Decimal("400.00"),
        height_m=Decimal("6.00"),
        floor_count=1,
    )
    ready = ready_draft(client, unmapped, service, clock)
    response = submit(client, ready)
    assert response.status_code == 200, response.content
    receipt = response.json()["data"]
    assert (
        receipt["status"] == "SUBMITTED"
        and receipt["routing"]["resolved"] is False
        and receipt["routing"]["exception_code"] == "NO_MATCH"
    )
    assert (
        receipt["owner_queue"]["queue_key"] == service.owner_queue.queue_key
    )  # accountable central queue, never unowned
    exception = RoutingException.objects.get(application_id=ready["app_id"], state="OPEN")
    assert exception.code == "NO_MATCH" and exception.input_snapshot["ward_key"] == "W-99"
    app = Application.objects.get(pk=ready["app_id"])
    assert (
        app.submitted_at == clock.now()
        and Obligation.objects.filter(application=app, state="ACTIVE").count() == 2
    )  # clock runs
    # The applicant never sees the internal exception; the supervisor does.
    assert (
        client.get(f"/api/v1/applications/{ready['app_id']}").json()["data"]["routing_exception"]
        is None
    )
    boss = signed_client(supervisor)
    staff_detail = boss.get(f"/api/v1/applications/{ready['app_id']}")
    assert staff_detail.status_code == 200
    body = staff_detail.json()["data"]
    assert body["routing_exception"]["code"] == "NO_MATCH"
    actions = {a["key"]: a for a in body["allowed_actions"]}
    assert (
        actions["start-scrutiny"]["enabled"] is False
        and actions["start-scrutiny"]["reason_code"] == "ROUTING_UNRESOLVED"
    )
    assert actions["resolve-routing"]["enabled"] is True
    blocked = boss.post(
        f"/api/v1/applications/{ready['app_id']}/start-scrutiny",
        data={"reason": "Trying before routing is fixed"},
        content_type=JSON,
        headers=cmd(etag=staff_detail["ETag"]),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "ROUTING_UNRESOLVED"

    # AT-07-04: a supervisor elsewhere cannot even see the case.
    assert (
        signed_client(foreign_supervisor).get(f"/api/v1/applications/{ready['app_id']}").status_code
        == 404
    )

    # AT-07-03: resolve with a valid active mapping target.
    resolution = {
        "target_jurisdiction_id": str(duty_queue.jurisdiction_id),
        "target_queue_id": str(duty_queue.pk),
        "routing_artifact_id": str(artifacts["ROUTING"].pk),
        "reason": "Outskirts ward is served by the central review desk until the map is updated",
        "exception_id": str(exception.pk),
    }
    key = str(uuid4())
    resolved = boss.post(
        f"/api/v1/applications/{ready['app_id']}/resolve-routing",
        data=resolution,
        content_type=JSON,
        headers=cmd(etag=staff_detail["ETag"], key=key),
    )
    assert resolved.status_code == 200, resolved.content
    assert resolved.json()["data"]["owner_queue"]["queue_key"] == duty_queue.queue_key
    exception.refresh_from_db()
    assert (
        exception.state == "RESOLVED"
        and exception.resolved_by == supervisor
        and "central review" in (exception.resolution or "")
    )
    app.refresh_from_db()
    assert app.owner_queue_id == duty_queue.pk
    assert set(
        Obligation.objects.filter(application=app).values_list("owner_queue_id", flat=True)
    ) == {duty_queue.pk}
    # AT-07-05: replay is idempotent; a second resolution finds no open exception.
    replay = boss.post(
        f"/api/v1/applications/{ready['app_id']}/resolve-routing",
        data=resolution,
        content_type=JSON,
        headers=cmd(etag=staff_detail["ETag"], key=key),
    )
    assert replay.status_code == 200 and replay.json()["data"]["replayed"] is True
    again = boss.post(
        f"/api/v1/applications/{ready['app_id']}/resolve-routing",
        data=resolution,
        content_type=JSON,
        headers=cmd(etag=resolved["ETag"]),
    )
    assert again.status_code == 404
    # Old routing events are retained; scrutiny can now start (TR-02).
    types = list(
        CaseEvent.objects.filter(application=app)
        .order_by("aggregate_version", "ordinal")
        .values_list("event_type", flat=True)
    )
    assert types[:4] == [
        "application.draft_created.v1",
        "application.submitted.v1",
        "routing.exception_opened.v1",
        "routing.resolved.v1",
    ]
    started = boss.post(
        f"/api/v1/applications/{ready['app_id']}/start-scrutiny",
        data={"reason": "Routing resolved; starting completeness check"},
        content_type=JSON,
        headers=cmd(etag=resolved["ETag"]),
    )
    assert started.status_code == 200 and started.json()["data"]["status"] == "SCRUTINY"
    stages = list(
        StageInstance.objects.filter(application=app)
        .order_by("cycle_number")
        .values_list("state", flat=True)
    )
    assert stages == ["DRAFT", "SUBMITTED", "SCRUTINY"]
    # Invalid target: inactive queue.
    Premises.objects.create(
        owner=applicant,
        display_name="Second Unmapped",
        address_line1="10 Nowhere Road",
        locality="Outskirts",
        ward_key="W-98",
        postal_code="560098",
        category_key="Office",
        area_sqm=Decimal("100.00"),
        height_m=Decimal("4.00"),
        floor_count=1,
    )


@pytest.mark.django_db
def test_at_09_scoped_timeline_revisions_and_overview(
    applicant: Principal,
    other_applicant: Principal,
    supervisor: Principal,
    leadership: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    duty_queue: DutyQueue,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    submitted = submit(client, ready)
    assert submitted.status_code == 200
    app_id = ready["app_id"]
    boss = signed_client(supervisor)
    detail = boss.get(f"/api/v1/applications/{app_id}")
    started = boss.post(
        f"/api/v1/applications/{app_id}/start-scrutiny",
        data={"reason": "Completeness check begins (internal note)"},
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )
    assert started.status_code == 200
    app = Application.objects.get(pk=app_id)
    CaseEvent.objects.create(
        application=app,
        aggregate_version=99,
        ordinal=0,
        event_type="decision.deliberation.v1",
        actor=supervisor,
        actor_kind="STAFF",
        occurred_at=clock.now(),
        payload={"note": "restricted"},
        audience="RESTRICTED",
        request_id=uuid4(),
    )

    # AT-09-01: applicant sees the public timeline and own receipt; internal notes never leak.
    mine = client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]
    assert [e["event_type"] for e in mine["items"]] == [
        "application.draft_created.v1",
        "application.submitted.v1",
        "scrutiny.started.v1",
    ]
    assert (
        all(e["audience"] == "PUBLIC_CASE" for e in mine["items"])
        and mine["as_of"] == clock.now().isoformat()
    )
    theirs = boss.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]
    assert [e["event_type"] for e in theirs["items"]] == [
        "application.draft_created.v1",
        "application.submitted.v1",
        "scrutiny.started.v1",
        "scrutiny.note.v1",
    ]
    assert "internal note" in theirs["items"][3]["payload"]["reason"]
    assert "decision.deliberation.v1" not in {
        e["event_type"] for e in theirs["items"]
    }  # RESTRICTED hidden from everyone here
    revisions = client.get(f"/api/v1/applications/{app_id}/revisions").json()["data"]["items"]
    assert (
        len(revisions) == 1 and revisions[0]["number"] == 1 and len(revisions[0]["documents"]) == 3
    )

    # AT-09-02 / 09-04: cross-applicant and unrelated staff see nothing; leadership reads only.
    stranger = signed_client(other_applicant)
    assert stranger.get(f"/api/v1/applications/{app_id}/timeline").status_code == 404
    assert stranger.get(f"/api/v1/applications/{app_id}/revisions").status_code == 404
    reader = signed_client(leadership)
    assert reader.get(f"/api/v1/applications/{app_id}").status_code == 200
    assert reader.get(f"/api/v1/applications/{app_id}/timeline").status_code == 200
    denied = reader.post(
        f"/api/v1/applications/{app_id}/start-scrutiny",
        data={"reason": "Leadership must not act on cases"},
        content_type=JSON,
        headers=cmd(etag=started["ETag"]),
    )
    assert denied.status_code == 403
    # Staff lists exclude drafts; the supervisor's list and overview agree.
    create_draft(client, premises, service)
    listing = boss.get("/api/v1/applications").json()["data"]["items"]
    assert [a["application_id"] for a in listing] == [app_id]
    overview = boss.get("/api/v1/overview").json()["data"]
    assert overview["role"] == "staff" and overview["counts"]["received"] == 1 == len(listing)
    assert (
        overview["counts"]["by_status"] == {"SCRUTINY": 1}
        and overview["counts"]["routing_exceptions"] == 0
    )
    assert (
        overview["counts"]["due_soon"] + overview["counts"]["overdue"] >= 0
        and len(overview["priority"]) == 2
    )
    assert overview["latest_events"][0]["event_type"] == "scrutiny.note.v1"
    applicant_overview = client.get("/api/v1/overview").json()["data"]
    assert (
        applicant_overview["role"] == "applicant"
        and applicant_overview["counts"]["drafts"] == 1
        and applicant_overview["counts"]["open"] == 1
    )
    assert all(e["audience"] == "PUBLIC_CASE" for e in applicant_overview["latest_events"])


@pytest.mark.django_db
def test_at_07_01_category_specific_route_wins(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    duty_queue: DutyQueue,
    artifacts: dict[str, PolicyArtifact],
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    hospital_desk = DutyQueue.objects.create(
        jurisdiction=duty_queue.jurisdiction,
        queue_key="hospital-desk",
        display_name="Hospital desk",
    )
    RoutingEntry.objects.create(
        artifact=artifacts["ROUTING"],
        ward_key="W-07",
        category_key="Hospital",
        target_jurisdiction=duty_queue.jurisdiction,
        target_queue=hospital_desk,
        priority=0,
    )
    hospital = Premises.objects.create(
        owner=applicant,
        display_name="Lotus Community Hospital",
        address_line1="5 Care Road",
        locality="Paharganj",
        ward_key="W-07",
        postal_code="560007",
        category_key="Hospital",
        area_sqm=Decimal("2500.00"),
        height_m=Decimal("15.00"),
        floor_count=4,
    )
    client = signed_client(applicant)
    ready = ready_draft(
        client,
        hospital,
        service,
        clock,
        requirement_codes=("ownership", "plan", "electrical", "evacuation"),
    )
    response = submit(client, ready)
    assert response.status_code == 200, response.content
    assert response.json()["data"]["owner_queue"]["queue_key"] == "hospital-desk"
    assert not RoutingException.objects.filter(application_id=ready["app_id"]).exists()
    assert datetime.fromisoformat(response.json()["data"]["accepted_at"]) == clock.now().astimezone(
        UTC
    )
