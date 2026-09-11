"""FR-08 / AT-08-01..05 (assignment, conflict-safe booking, reassignment) and FR-11 /
AT-11-01..05 (appointments in both queues, failed visits, cancellation, next-action attempts)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import Client

from agni.cases.models import Application, CaseEvent, Premises, StageInstance
from agni.identity.models import Principal
from agni.inspections.models import Assignment, Inspection
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent
from agni.policies.models import Service
from agni.routing.models import DutyQueue

from .test_submission import cmd, ready_draft, submit

JSON = "application/json"


def case_in_scrutiny(
    applicant: Principal,
    supervisor: Principal,
    premises: Premises,
    service: Service,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> tuple[Client, Client, str]:
    """Submit a complete draft and start scrutiny; returns (applicant client, boss client, id)."""
    client = signed_client(applicant)
    ready = ready_draft(client, premises, service, clock)
    submitted = submit(client, ready)
    assert submitted.status_code == 200, submitted.content
    boss = signed_client(supervisor)
    app_id = ready["app_id"]
    started = boss.post(
        f"/api/v1/applications/{app_id}/start-scrutiny",
        data={"reason": "Completeness confirmed; moving to scrutiny"},
        content_type=JSON,
        headers=cmd(etag=submitted["ETag"]),
    )
    assert started.status_code == 200, started.content
    return client, boss, app_id


def require_inspection(boss: Client, app_id: str) -> Any:
    detail = boss.get(f"/api/v1/applications/{app_id}")
    return boss.post(
        f"/api/v1/applications/{app_id}/require-inspection",
        data={"purpose": "INITIAL", "reason": "Site visit is required by the demo policy"},
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )


def schedule(
    boss: Client,
    inspection: dict[str, Any],
    officer: Principal,
    start: str,
    end: str,
    *,
    key: str | None = None,
    etag: str | None = None,
    app_version: int | None = None,
) -> Any:
    return boss.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/schedule",
        data={
            "officer_id": str(officer.pk),
            "starts_at": start,
            "ends_at": end,
            "appointment_timezone": "Asia/Kolkata",
            "reason": "Officer available and within the ward cluster",
            "application_version": app_version
            if app_version is not None
            else inspection["application_version"],
        },
        content_type=JSON,
        headers=cmd(
            etag=etag or f'"inspection:{inspection["inspection_id"]}:v{inspection["version"]}"',
            key=key,
        ),
    )


SLOT_START = "2026-09-14T04:30:00+00:00"  # Mon 10:00 IST
SLOT_END = "2026-09-14T06:30:00+00:00"


@pytest.mark.django_db
def test_at_11_01_08_01_visit_required_scheduled_and_visible_in_both_queues(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    duty_queue: DutyQueue,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    hint = next(
        a
        for a in boss.get(f"/api/v1/applications/{app_id}").json()["data"]["allowed_actions"]
        if a["key"] == "require-inspection"
    )
    assert hint["enabled"] is True

    required = require_inspection(boss, app_id)
    assert required.status_code == 201, required.content
    inspection = required.json()["data"]
    assert (
        inspection["status"] == "REQUESTED"
        and inspection["attempt_number"] == 1
        and inspection["checklist_ref"] == "demo-checklist-v1#1"
    )
    app = Application.objects.get(pk=app_id)
    assert app.status == "INSPECTION_PENDING"
    stages = list(
        StageInstance.objects.filter(application=app)
        .order_by("cycle_number")
        .values_list("state", flat=True)
    )
    assert stages == ["DRAFT", "SUBMITTED", "SCRUTINY", "INSPECTION_PENDING"]
    kinds = {o.kind: o for o in Obligation.objects.filter(application=app)}
    assert kinds["SCRUTINY_TASK"].state == "SATISFIED" and kinds["CASE_TARGET"].state == "ACTIVE"
    assert kinds["INSPECTION_TASK"].state == "ACTIVE" and kinds[
        "INSPECTION_TASK"
    ].due_at == clock.now() + timedelta(days=7)
    case_target_due = kinds["CASE_TARGET"].due_at

    scheduled = schedule(boss, inspection, officers["suresh"], SLOT_START, SLOT_END)
    assert scheduled.status_code == 200, scheduled.content
    body = scheduled.json()["data"]
    assert (
        body["status"] == "SCHEDULED"
        and body["current_assignment"]["number"] == 1
        and body["current_assignment"]["officer_name"] == "Suresh Yadav"
    )
    assert body["scheduled_start"] == SLOT_START and body["appointment_timezone"] == "Asia/Kolkata"
    assert scheduled["ETag"] == f'"inspection:{inspection["inspection_id"]}:v2"'
    # Officer queue (UI-10) and applicant timeline (UI-07) both carry the appointment.
    queue = signed_client(officers["suresh"]).get("/api/v1/inspections").json()["data"]["items"]
    assert [i["inspection_id"] for i in queue] == [inspection["inspection_id"]]
    assert signed_client(officers["priya"]).get("/api/v1/inspections").json()["data"]["items"] == []
    events = [
        e["event_type"]
        for e in client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "inspection.requested.v1" in events and "inspection.scheduled.v1" in events
    assert "inspection.assignment_changed.v1" not in events  # officer identity stays internal
    applicant_view = client.get(f"/api/v1/applications/{app_id}").json()["data"]["inspections"][0]
    assert (
        applicant_view["scheduled_start"] == SLOT_START and applicant_view["officer_name"] is None
    )
    staff_view = boss.get(f"/api/v1/applications/{app_id}").json()["data"]["inspections"][0]
    assert staff_view["officer_name"] == "Suresh Yadav"
    # Officers read the case they are assigned to, and only that.
    officer_client = signed_client(officers["suresh"])
    assert officer_client.get(f"/api/v1/applications/{app_id}").status_code == 200
    window = officer_client.get(
        "/api/v1/schedule?starts_at=2026-09-14T00:00:00%2B00:00&ends_at=2026-09-15T00:00:00%2B00:00"
    ).json()["data"]
    assert len(window["bookings"]) == 1 and window["bookings"][0]["officer_name"] == "Suresh Yadav"
    assert Obligation.objects.get(pk=kinds["CASE_TARGET"].pk).due_at == case_target_due
    assert AuditEvent.objects.filter(action="inspection.scheduled").exists()


@pytest.mark.django_db
def test_at_08_02_ineligible_unavailable_and_overlapping_bookings_fail_atomically(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    # Out-of-scope officer and an inactive officer are refused before anything is written.
    outside = schedule(boss, inspection, officers["outsider"], SLOT_START, SLOT_END)
    assert outside.status_code == 409 and outside.json()["code"] == "OFFICER_UNAVAILABLE"
    Principal.objects.filter(pk=officers["priya"].pk).update(is_active=False)
    inactive = schedule(boss, inspection, officers["priya"], SLOT_START, SLOT_END)
    assert inactive.status_code == 409 and inactive.json()["code"] == "OFFICER_UNAVAILABLE"
    Principal.objects.filter(pk=officers["priya"].pk).update(is_active=True)
    assert (
        Assignment.objects.count() == 0
        and Inspection.objects.get(pk=inspection["inspection_id"]).status == "REQUESTED"
    )

    # Unavailability recorded by the officer blocks bookings inside it and surfaces existing ones.
    officer_client = signed_client(officers["suresh"])
    leave = officer_client.post(
        f"/api/v1/staff/{officers['suresh'].pk}/availability",
        data={
            "kind": "UNAVAILABLE",
            "starts_at": "2026-09-15T00:00:00+00:00",
            "ends_at": "2026-09-16T00:00:00+00:00",
            "reason_code": "LEAVE",
            "reason": "Approved leave day (synthetic)",
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert leave.status_code == 201 and leave.json()["data"]["affected_bookings"] == []
    on_leave = schedule(
        boss,
        inspection,
        officers["suresh"],
        "2026-09-15T04:30:00+00:00",
        "2026-09-15T06:30:00+00:00",
    )
    assert on_leave.status_code == 409 and on_leave.json()["code"] == "OFFICER_UNAVAILABLE"

    first = schedule(boss, inspection, officers["suresh"], SLOT_START, SLOT_END)
    assert first.status_code == 200
    # A second case in the same slot for the same officer -> APPOINTMENT_CONFLICT (half-open).
    second_premises = Premises.objects.create(
        owner=applicant,
        display_name="Second Hall",
        address_line1="2 Demo Road",
        locality="Demo Nagar",
        ward_key="W-01",
        postal_code="560001",
        category_key="Office",
        area_sqm=200,
        height_m=5,
        floor_count=1,
    )
    _, _, app2 = case_in_scrutiny(
        applicant, supervisor, second_premises, service, signed_client, clock
    )
    inspection2 = require_inspection(boss, app2).json()["data"]
    clash = schedule(
        boss,
        inspection2,
        officers["suresh"],
        "2026-09-14T05:30:00+00:00",
        "2026-09-14T07:30:00+00:00",
    )
    assert clash.status_code == 409 and clash.json()["code"] == "APPOINTMENT_CONFLICT"
    assert clash.json()["conflicting_interval"]["start"] == SLOT_START
    adjacent = schedule(
        boss, inspection2, officers["suresh"], SLOT_END, "2026-09-14T08:30:00+00:00"
    )
    assert adjacent.status_code == 200  # ends 06:30 / starts 06:30 do not collide
    # The database constraint is the final guard even if the pre-check were bypassed.
    with pytest.raises(IntegrityError), transaction.atomic():
        Assignment.objects.create(
            inspection_id=inspection["inspection_id"],
            officer=officers["suresh"],
            assigned_by=supervisor,
            number=9,
            state="ACTIVE",
            starts_at=clock.now(),
            reason="bypass attempt",
            booking_start=clock.now() + timedelta(days=4),
            booking_end=clock.now() + timedelta(days=4, hours=1),
        )
    # Leadership/applicant/officer cannot schedule (AT-08-04).
    assert (
        schedule(
            client,
            inspection2,
            officers["priya"],
            "2026-09-16T04:30:00+00:00",
            "2026-09-16T05:30:00+00:00",
        ).status_code
        == 403
    )
    assert (
        schedule(
            officer_client,
            inspection2,
            officers["priya"],
            "2026-09-16T04:30:00+00:00",
            "2026-09-16T05:30:00+00:00",
        ).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_at_08_05_concurrent_bookings_for_one_officer_yield_exactly_one_assignment(
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
    inspection_a = require_inspection(boss, app_id).json()["data"]
    second = Premises.objects.create(
        owner=applicant,
        display_name="Race Hall",
        address_line1="3 Demo Road",
        locality="Demo Nagar",
        ward_key="W-01",
        postal_code="560001",
        category_key="Office",
        area_sqm=200,
        height_m=5,
        floor_count=1,
    )
    _, _, app_b = case_in_scrutiny(applicant, supervisor, second, service, signed_client, clock)
    inspection_b = require_inspection(boss, app_b).json()["data"]
    results: list[int] = []

    def book(inspection: dict[str, Any]) -> None:
        try:
            results.append(
                schedule(
                    signed_client(supervisor), inspection, officers["suresh"], SLOT_START, SLOT_END
                ).status_code
            )
        finally:
            connection.close()

    threads = [
        threading.Thread(target=book, args=(inspection_a,)),
        threading.Thread(target=book, args=(inspection_b,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == [200, 409], results
    assert Assignment.objects.filter(officer=officers["suresh"], state="ACTIVE").count() == 1
    # Replay of the winning command returns the same assignment; stale versions are refused.
    winner = Inspection.objects.get(status="SCHEDULED")
    winning = {
        "inspection_id": str(winner.pk),
        "version": winner.version - 1,
        "application_version": winner.application.version,
    }
    stale = schedule(boss, winning, officers["priya"], SLOT_START, SLOT_END)
    assert stale.status_code == 412


@pytest.mark.django_db
def test_at_08_03_11_02_11_03_reassign_check_in_failed_visit_and_cancel_preserve_history_and_clock(
    applicant: Principal,
    supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    scheduled = schedule(boss, inspection, officers["suresh"], SLOT_START, SLOT_END)
    assert scheduled.status_code == 200
    app = Application.objects.get(pk=app_id)
    case_due = Obligation.objects.get(application=app, kind="CASE_TARGET").due_at
    inspection_due = Obligation.objects.get(application=app, kind="INSPECTION_TASK").due_at

    # AT-08-03: reassign to Priya through a new assignment version; Suresh's authority is stale.
    reassigned = boss.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/reassign",
        data={
            "new_officer_id": str(officers["priya"].pk),
            "reason": "Suresh reassigned to an emergency call-out",
            "application_version": app.version,
        },
        content_type=JSON,
        headers=cmd(etag=scheduled["ETag"]),
    )
    assert reassigned.status_code == 200, reassigned.content
    body = reassigned.json()["data"]
    assert (
        body["current_assignment"]["number"] == 2
        and body["current_assignment"]["officer_name"] == "Priya Nair"
    )
    assert list(
        Assignment.objects.filter(inspection_id=inspection["inspection_id"])
        .order_by("number")
        .values_list("state", flat=True)
    ) == ["SUPERSEDED", "ACTIVE"]
    detail = boss.get(f"/api/v1/inspections/{inspection['inspection_id']}").json()["data"]
    assert [a["state"] for a in detail["assignments"]] == ["SUPERSEDED", "ACTIVE"]
    suresh = signed_client(officers["suresh"])
    priya = signed_client(officers["priya"])
    check_in = {
        "application_version": app.version,
        "assignment_version": body["current_assignment"]["version"],
        "captured_at": "2026-09-14T04:32:00+00:00",
        "location_unavailable_reason": "GPS denied on the device",
    }
    assert (
        suresh.post(
            f"/api/v1/inspections/{inspection['inspection_id']}/check-in",
            data=check_in,
            content_type=JSON,
            headers=cmd(etag=reassigned["ETag"]),
        ).status_code
        == 404
    )
    stale_assignment = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/check-in",
        data={**check_in, "assignment_version": 99},
        content_type=JSON,
        headers=cmd(etag=reassigned["ETag"]),
    )
    assert (
        stale_assignment.status_code == 409
        and stale_assignment.json()["code"] == "ASSIGNMENT_CHANGED"
    )
    no_reason = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/check-in",
        data={**check_in, "location_unavailable_reason": None},
        content_type=JSON,
        headers=cmd(etag=reassigned["ETag"]),
    )
    assert (
        no_reason.status_code == 422
        and no_reason.json()["violations"][0]["pointer"] == "/location_unavailable_reason"
    )
    checked = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/check-in",
        data=check_in,
        content_type=JSON,
        headers=cmd(etag=reassigned["ETag"]),
    )
    assert checked.status_code == 200 and checked.json()["data"]["status"] == "IN_PROGRESS"
    assert checked.json()["data"]["check_in"]["location"] is None

    # AT-11-02: an inaccessible site does not complete the inspection or reset elapsed time.
    failed = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/fail-visit",
        data={
            "application_version": app.version,
            "assignment_version": body["current_assignment"]["version"],
            "reason_code": "SITE_INACCESSIBLE",
            "reason": "Premises locked; caretaker absent; photos of the locked gate taken",
            "captured_at": "2026-09-14T04:40:00+00:00",
        },
        content_type=JSON,
        headers=cmd(etag=checked["ETag"]),
    )
    assert failed.status_code == 200, failed.content
    outcome = failed.json()["data"]
    assert (
        outcome["status"] == "FAILED"
        and outcome["failed_reason_code"] == "SITE_INACCESSIBLE"
        and outcome["next_attempt_id"]
    )
    app.refresh_from_db()
    assert app.status == "INSPECTION_PENDING"
    assert Obligation.objects.get(application=app, kind="CASE_TARGET").due_at == case_due
    inspection_task = Obligation.objects.get(application=app, kind="INSPECTION_TASK")
    assert inspection_task.state == "ACTIVE" and inspection_task.due_at == inspection_due
    attempts = list(Inspection.objects.filter(application=app).order_by("attempt_number"))
    assert [a.status for a in attempts] == ["FAILED", "REQUESTED"] and attempts[
        1
    ].parent_inspection_id == attempts[0].pk
    assert (
        Assignment.objects.get(pk=body["current_assignment"]["assignment_id"]).state == "FULFILLED"
    )
    public = [
        e["event_type"]
        for e in client.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "inspection.visit_failed.v1" in public
    # Terminal attempt fields cannot be overwritten (AT-11-03 recovery = new attempt).
    again = priya.post(
        f"/api/v1/inspections/{inspection['inspection_id']}/fail-visit",
        data={
            "application_version": app.version,
            "assignment_version": 3,
            "reason_code": "OTHER",
            "reason": "second failure attempt on a closed record",
            "captured_at": "2026-09-14T04:50:00+00:00",
        },
        content_type=JSON,
        headers=cmd(etag=failed["ETag"]),
    )
    assert again.status_code == 404  # no ACTIVE assignment on a terminal attempt
    reschedule = schedule(
        boss,
        {
            "inspection_id": str(attempts[0].pk),
            "version": attempts[0].version,
            "application_version": app.version,
        },
        officers["suresh"],
        "2026-09-16T04:30:00+00:00",
        "2026-09-16T06:30:00+00:00",
    )
    assert reschedule.status_code == 409 and reschedule.json()["code"] == "INVALID_TRANSITION"

    # The follow-up attempt can be scheduled, and cancelled (which opens attempt 3).
    follow_up = boss.get(f"/api/v1/inspections/{outcome['next_attempt_id']}").json()["data"]
    booked = schedule(
        boss,
        follow_up,
        officers["suresh"],
        "2026-09-16T04:30:00+00:00",
        "2026-09-16T06:30:00+00:00",
    )
    assert booked.status_code == 200
    cancelled = boss.post(
        f"/api/v1/inspections/{follow_up['inspection_id']}/cancel",
        data={
            "reason": "Applicant asked to move the visit to next week",
            "application_version": app.version,
        },
        content_type=JSON,
        headers=cmd(etag=booked["ETag"]),
    )
    assert cancelled.status_code == 200 and cancelled.json()["data"]["status"] == "CANCELLED"
    assert (
        Assignment.objects.get(inspection_id=follow_up["inspection_id"], number=1).state
        == "REVOKED"
    )
    assert Inspection.objects.filter(application=app).count() == 3
    assert (
        Inspection.objects.get(pk=cancelled.json()["data"]["next_attempt_id"]).status == "REQUESTED"
    )
    assert CaseEvent.objects.filter(application=app, event_type="inspection.cancelled.v1").exists()
    assert app.status == "INSPECTION_PENDING"


@pytest.mark.django_db
def test_at_08_04_scope_foreign_supervisor_and_applicant_are_denied(
    applicant: Principal,
    other_applicant: Principal,
    supervisor: Principal,
    foreign_supervisor: Principal,
    officers: dict[str, Principal],
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    inspection = require_inspection(boss, app_id).json()["data"]
    foreign = signed_client(foreign_supervisor)
    assert foreign.get(f"/api/v1/inspections/{inspection['inspection_id']}").status_code == 404
    assert (
        schedule(foreign, inspection, officers["suresh"], SLOT_START, SLOT_END).status_code == 404
    )
    assert foreign.get("/api/v1/inspections").json()["data"]["items"] == []
    assert foreign.get("/api/v1/officers").json()["data"]["items"] == []
    assert client.get("/api/v1/inspections").status_code == 403
    assert signed_client(other_applicant).get(f"/api/v1/applications/{app_id}").status_code == 404
    roster = boss.get("/api/v1/officers").json()["data"]["items"]
    assert {o["display_name"] for o in roster} == {"Suresh Yadav", "Priya Nair"}
    # The applicant cannot require an inspection either.
    detail = client.get(f"/api/v1/applications/{app_id}")
    assert (
        client.post(
            f"/api/v1/applications/{app_id}/require-inspection",
            data={"purpose": "INITIAL", "reason": "please inspect my building"},
            content_type=JSON,
            headers=cmd(etag=detail["ETag"]),
        ).status_code
        == 403
    )
