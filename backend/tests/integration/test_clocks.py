"""FR-18 / AT-18 (persisted clocks and pauses), FR-19 / AT-19 (unique threshold actions, one
escalation with two schedulers, obsolete reminders suppressed, acknowledgement is not
satisfaction) and FR-23 / AT-23 (in-app notification survives a provider outage, recipient
scoping, read markers) against real PostgreSQL."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test import Client

from agni.cases.models import Application, Premises
from agni.identity.contacts import normalize_contact
from agni.identity.models import Principal
from agni.identity.otp import record_verified_contact
from agni.notifications.adapters import DemoSinkMessageSender
from agni.notifications.models import DeliveryAttempt, DemoOutboundMessage, Notification
from agni.notifications.templates import TEMPLATES
from agni.obligations.application import scheduler
from agni.obligations.application.clock_service import add_pause, end_pause, recompute_obligation
from agni.obligations.models import Escalation, Obligation, ObligationPause, ThresholdAction
from agni.platform import dispatch, jobs
from agni.platform.clock import FrozenClock
from agni.platform.errors import ValidationFailed
from agni.platform.models import LogicalJob, OutboxMessage
from agni.policies.models import Service

from .test_inspections import case_in_scrutiny
from .test_notices import info_notice_body, publish
from .test_submission import cmd

JSON = "application/json"
IST = ZoneInfo("Asia/Kolkata")


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=IST).astimezone(UTC)


def run_worker(clock: FrozenClock) -> jobs.RunReport:
    return jobs.run_due_jobs(owner="test-worker", limit=50, clock=clock)


def drain_worker(clock: FrozenClock) -> jobs.RunReport:
    """Run passes until nothing is due: a fan-out job enqueues delivery jobs for the next pass."""
    total = jobs.RunReport()
    for _ in range(5):
        report = run_worker(clock)
        if report.claimed == 0:
            break
        total.claimed += report.claimed
        total.completed += report.completed
        total.retried += report.retried
        total.dead += report.dead
        total.reconcile += report.reconcile
        total.lost += report.lost
    return total


@pytest.fixture
def scrutiny_case(
    applicant: Principal,
    supervisor: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> dict[str, Any]:
    client, boss, app_id = case_in_scrutiny(
        applicant, supervisor, premises, service, signed_client, clock
    )
    task = Obligation.objects.get(application_id=app_id, kind="SCRUTINY_TASK", state="ACTIVE")
    return {"applicant": client, "boss": boss, "app_id": app_id, "task": task}


@pytest.mark.django_db
def test_at_18_01_18_02_persisted_pauses_move_the_due_instant_and_union_overlaps(
    scrutiny_case: dict[str, Any], supervisor: Principal, clock: FrozenClock
) -> None:
    task: Obligation = scrutiny_case["task"]
    # Re-base the working-time task on the worked example: Monday 09:00 IST, 240 minutes.
    task.started_at = ist(14, 9, 0)
    task.budget_minutes = 240
    task.save(update_fields=["started_at", "budget_minutes"])
    recompute_obligation(task, now=clock.now())
    assert task.due_at == ist(14, 13, 0)
    # One authorised pause 10:00-11:00 -> due 14:00.
    pause = add_pause(
        task,
        starts_at=ist(14, 10, 0),
        ends_at=ist(14, 11, 0),
        authorized_by=supervisor,
        reason_code="AUTHORIZED_ADMINISTRATIVE_HOLD",
        reason="Administrative hold (synthetic)",
        now=clock.now(),
    )
    task.refresh_from_db()
    assert task.due_at == ist(14, 14, 0) and task.state == "ACTIVE"
    # Overlapping second pause 10:30-11:30 -> 14:30, not 15:00 (union, never double-subtracted).
    add_pause(
        task,
        starts_at=ist(14, 10, 30),
        ends_at=ist(14, 11, 30),
        authorized_by=supervisor,
        reason_code="AUTHORIZED_ADMINISTRATIVE_HOLD",
        reason="Second overlapping hold (synthetic)",
        now=clock.now(),
    )
    task.refresh_from_db()
    assert task.due_at == ist(14, 14, 30)
    # A reason the policy does not permit is refused; nothing is written.
    with pytest.raises(ValidationFailed):
        add_pause(
            task,
            starts_at=ist(14, 12, 0),
            ends_at=ist(14, 12, 30),
            authorized_by=supervisor,
            reason_code="WORKER_OUTAGE",
            reason="Technical outage must never pause a clock",
            now=clock.now(),
        )
    assert ObligationPause.objects.filter(obligation=task).count() == 2
    # An open-ended pause means PAUSED with no estimate; ending it recomputes from the facts.
    open_pause = add_pause(
        task,
        starts_at=ist(14, 12, 0),
        ends_at=None,
        authorized_by=supervisor,
        reason_code="AUTHORIZED_ADMINISTRATIVE_HOLD",
        reason="Open hold pending court paper (synthetic)",
        now=clock.now(),
    )
    task.refresh_from_db()
    assert task.state == "PAUSED" and task.due_at is None
    detail = scrutiny_case["boss"].get(f"/api/v1/obligations/{task.pk}")
    assert detail.status_code == 200, detail.content
    clock_view = detail.json()["data"]["clock"]
    assert clock_view["paused"] is True and clock_view["due_estimate"].startswith("Paused")
    assert len(clock_view["pauses"]) == 3
    end_pause(open_pause, ends_at=ist(14, 12, 30), now=clock.now())
    task.refresh_from_db()
    assert task.state == "ACTIVE" and task.due_at == ist(14, 15, 0)
    assert pause.pk != open_pause.pk
    # The list endpoint labels urgency from one cutoff and is staff-only.
    cutoff = ist(14, 14, 0).isoformat().replace("+", "%2B")
    listing = scrutiny_case["boss"].get(f"/api/v1/obligations?as_of={cutoff}")
    assert listing.status_code == 200, listing.content
    row = next(i for i in listing.json()["data"]["items"] if i["obligation_id"] == str(task.pk))
    assert row["urgency"] == "DUE_SOON"
    assert scrutiny_case["applicant"].get("/api/v1/obligations").status_code == 403


@pytest.mark.django_db(transaction=True)
# Cases: AT-18-05 (two schedulers, one logical action per obligation cycle) PROP-08
def test_at_19_01_19_02_two_schedulers_yield_one_threshold_action_and_one_escalation(
    scrutiny_case: dict[str, Any], supervisor: Principal, clock: FrozenClock
) -> None:
    task: Obligation = scrutiny_case["task"]
    # Make the task overdue by more than the first escalation step (60 min after due).
    task.due_at = clock.now() - timedelta(minutes=90)
    task.started_at = clock.now() - timedelta(days=3)
    task.save(update_fields=["due_at", "started_at"])
    results: list[dict[str, int]] = []

    def scan() -> None:
        try:
            results.append(scheduler.scan_due_obligations(now=clock.now()))
        finally:
            connection.close()

    threads = [threading.Thread(target=scan) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    actions = list(ThresholdAction.objects.filter(obligation=task).order_by("scheduled_for"))
    keys = [a.threshold_key for a in actions]
    assert keys == ["REMINDER_75", "DUE", "ESCALATION_60"], keys
    assert sum(r["created"] for r in results) == 3  # created once across both schedulers
    assert LogicalJob.objects.filter(kind="obligation.threshold").count() == 3
    # Restart / rescan: nothing new.
    again = scheduler.scan_due_obligations(now=clock.now())
    assert again["created"] == 0 and ThresholdAction.objects.filter(obligation=task).count() == 3
    # Worker executes: one escalation (unique per threshold action), notifications, event.
    report = run_worker(clock)
    assert report.completed == 3 and report.lost == 0, report
    escalations = list(Escalation.objects.filter(obligation=task))
    assert len(escalations) == 1 and escalations[0].level == 1 and escalations[0].state == "OPEN"
    assert Notification.objects.filter(recipient=supervisor, category="ESCALATION").count() == 1
    assert Notification.objects.filter(recipient=supervisor, category="OBLIGATION").count() == 2
    events = [
        e["event_type"]
        for e in scrutiny_case["boss"]
        .get(f"/api/v1/applications/{scrutiny_case['app_id']}/timeline")
        .json()["data"]["items"]
    ]
    assert events.count("obligation.threshold_reached.v1") == 3
    # Running the worker again (duplicate delivery of the same wake-up) changes nothing.
    assert run_worker(clock).claimed == 0
    assert Escalation.objects.filter(obligation=task).count() == 1
    # Acknowledgement records ownership; the obligation stays ACTIVE and overdue (AT-19-03).
    boss = scrutiny_case["boss"]
    esc = escalations[0]
    ack = boss.post(
        f"/api/v1/escalations/{esc.pk}/acknowledge",
        data={
            "reason": "Taking ownership of the overdue scrutiny",
            "next_action": "Assign a second reviewer today",
        },
        content_type=JSON,
        headers=cmd(etag=esc.etag),
    )
    assert ack.status_code == 200, ack.content
    assert (
        ack.json()["data"]["state"] == "ACKNOWLEDGED"
        and ack.json()["data"]["obligation_state"] == "ACTIVE"
    )
    assert Obligation.objects.get(pk=task.pk).state == "ACTIVE"
    twice = boss.post(
        f"/api/v1/escalations/{esc.pk}/acknowledge",
        data={"reason": "Second acknowledgement attempt"},
        content_type=JSON,
        headers=cmd(etag=ack["ETag"]),
    )
    assert twice.status_code == 409


@pytest.mark.django_db
def test_at_19_02_satisfied_obligation_suppresses_the_obsolete_reminder(
    scrutiny_case: dict[str, Any], clock: FrozenClock
) -> None:
    task: Obligation = scrutiny_case["task"]
    task.due_at = clock.now() - timedelta(minutes=1)
    task.started_at = clock.now() - timedelta(days=1)
    task.save(update_fields=["due_at", "started_at"])
    created = scheduler.scan_due_obligations(now=clock.now())["created"]
    assert created == 2  # REMINDER_75 and DUE
    # The obligation is satisfied (e.g. the case moved on) before the worker runs.
    Obligation.objects.filter(pk=task.pk).update(state="SATISFIED")
    report = run_worker(clock)
    assert report.completed == 2
    actions = ThresholdAction.objects.filter(obligation=task)
    assert {a.disposition for a in actions} == {"CANCELLED_AS_OBSOLETE"}
    assert not Notification.objects.filter(category="OBLIGATION").exists()
    assert not Escalation.objects.exists()


@pytest.mark.django_db
def test_at_19_04_19_05_manual_escalation_is_scoped_idempotent_and_never_satisfies(
    scrutiny_case: dict[str, Any],
    supervisor: Principal,
    foreign_supervisor: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    task: Obligation = scrutiny_case["task"]
    boss = scrutiny_case["boss"]
    body = {
        "reason": "Applicant is a hospital; scrutiny must not slip past today",
        "requested_level": 2,
        "next_action": "Reassign to the senior desk before 17:00",
    }
    key = "manual-esc-1"
    first = boss.post(
        f"/api/v1/obligations/{task.pk}/escalations",
        data=body,
        content_type=JSON,
        headers=cmd(etag=task.etag, key=key),
    )
    assert first.status_code == 201, first.content
    replay = boss.post(
        f"/api/v1/obligations/{task.pk}/escalations",
        data=body,
        content_type=JSON,
        headers=cmd(etag=task.etag, key=key),
    )
    assert replay.status_code == 201 and replay.json()["data"]["replayed"] is True
    assert Escalation.objects.filter(obligation=task).count() == 1
    assert Obligation.objects.get(pk=task.pk).state == "ACTIVE"
    assert Notification.objects.filter(recipient=supervisor, category="ESCALATION").count() == 1
    stale = boss.post(
        f"/api/v1/obligations/{task.pk}/escalations",
        data=body,
        content_type=JSON,
        headers=cmd(etag=task.etag),
    )
    assert stale.status_code == 412
    assert (
        signed_client(foreign_supervisor)
        .post(
            f"/api/v1/obligations/{task.pk}/escalations",
            data=body,
            content_type=JSON,
            headers=cmd(etag=task.etag),
        )
        .status_code
        == 404
    )
    assert (
        scrutiny_case["applicant"]
        .post(
            f"/api/v1/obligations/{task.pk}/escalations",
            data=body,
            content_type=JSON,
            headers=cmd(etag=task.etag),
        )
        .status_code
        == 403
    )
    assert (
        signed_client(foreign_supervisor).get(f"/api/v1/obligations/{task.pk}").status_code == 404
    )
    short = boss.post(
        f"/api/v1/obligations/{task.pk}/escalations",
        data={**body, "reason": "short"},
        content_type=JSON,
        headers=cmd(etag=f'"obligation:{task.pk}:v{task.version + 1}"'),
    )
    assert short.status_code == 422


@pytest.mark.django_db
# Cases: AT-23-04 (recipient scoping: nobody reads another recipient's notification); DS-13
# (provider outage keeps the case accepted and the notification PENDING / FAILED, never "sent")
def test_at_23_01_23_05_dispatch_fanout_delivery_outage_and_recipient_scoping(
    scrutiny_case: dict[str, Any],
    applicant: Principal,
    other_applicant: Principal,
    supervisor: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    boss, client, app_id = (
        scrutiny_case["boss"],
        scrutiny_case["applicant"],
        scrutiny_case["app_id"],
    )
    # The applicant has a verified e-mail contact, so mandatory notices also get a channel attempt.
    record_verified_contact(applicant, normalize_contact("EMAIL", "asha@example.test"), clock.now())
    detail = boss.get(f"/api/v1/applications/{app_id}")
    published = publish(boss, app_id, detail["ETag"], info_notice_body())
    assert published.status_code == 201, published.content
    pending_before = OutboxMessage.objects.filter(state="PENDING").count()
    assert pending_before >= 1
    # Broker outage: intents stay PENDING with a visible attempt count; nothing is lost.
    outage = dispatch.dispatch_pending(now=clock.now(), broker=dispatch.FailingBroker())
    assert outage.failed == outage.scanned >= 1 and outage.published == 0
    assert OutboxMessage.objects.filter(state="PENDING").count() == pending_before
    assert OutboxMessage.objects.filter(dispatch_attempts__gte=1).count() == pending_before
    lag = dispatch.outbox_lag(clock.now())
    assert lag["pending"] == pending_before
    # Recovery: the next pass publishes; the fan-out job id is deterministic (no duplicates).
    recovered = dispatch.dispatch_pending(now=clock.now(), broker=dispatch.NullBroker())
    assert recovered.published == pending_before
    fanout_jobs = LogicalJob.objects.filter(kind="notification.fanout").count()
    assert fanout_jobs == pending_before
    dispatch.dispatch_pending(now=clock.now(), broker=dispatch.NullBroker())
    assert LogicalJob.objects.filter(kind="notification.fanout").count() == fanout_jobs
    # Fan-out with the e-mail gateway DOWN: the in-app notification exists anyway (AT-23-01).
    DemoSinkMessageSender.force_failure = "transient"
    try:
        report = drain_worker(clock)  # fan-out pass, then the delivery pass it enqueued
        # Every mandatory message for the applicant (case received, notice) tried the gateway
        # and was told to retry; none of them lost the in-app copy.
        assert report.completed >= 1 and report.retried >= 1 and report.dead == 0
        notice_notifications = Notification.objects.filter(
            recipient=applicant, template_key="notice-information"
        )
        assert notice_notifications.count() == 1
        attempt = DeliveryAttempt.objects.get(notification=notice_notifications.first())
        assert attempt.channel == "EMAIL" and attempt.state == "FAILED"
        assert attempt.safe_failure_code == "PROVIDER_UNAVAILABLE"
        assert attempt.job_id is not None
        job = LogicalJob.objects.get(logical_action_id=attempt.job_id)
        assert job.state == "RETRY_WAIT" and job.attempt_count == 1
        assert OutboxMessage.objects.filter(state="PENDING").count() == 0
        assert Application.objects.get(pk=app_id).status == "INFO_REQUIRED"  # outcome untouched
    finally:
        DemoSinkMessageSender.force_failure = None
    # Supervisors got the case-submitted in-app notice; applicants get theirs; nobody else's.
    mine = client.get("/api/v1/notifications").json()["data"]
    assert mine["unread_count"] >= 1 and all(n["title"] for n in mine["items"])
    titles = [n["title"] for n in mine["items"]]
    assert any(t.startswith("Information required") for t in titles)
    assert any(d["state"] == "FAILED" for n in mine["items"] for d in n["deliveries"])
    stranger = signed_client(other_applicant).get("/api/v1/notifications").json()["data"]
    assert stranger["items"] == []
    theirs = boss.get("/api/v1/notifications").json()["data"]
    assert all("Information required" not in n["title"] for n in theirs["items"])
    assert any(n["title"].startswith("Application") for n in theirs["items"])
    # Provider recovers: the retry is due later; advancing the clock lets the same job succeed.
    clock.advance(timedelta(minutes=3))
    report = drain_worker(clock)
    attempt.refresh_from_db()
    assert attempt.state == "ACCEPTED_BY_PROVIDER" and attempt.provider_message_id
    assert DemoOutboundMessage.objects.filter(purpose="NOTIFICATION:NOTICE").count() == 1
    assert attempt.job_id is not None
    assert LogicalJob.objects.get(logical_action_id=attempt.job_id).state == "COMPLETE"
    # Read markers: idempotent, recipient-only, boundary-respecting; no case state change.
    client = signed_client(applicant)  # the clock advance expired nothing, but re-sign to be safe
    target = next(n for n in mine["items"] if n["title"].startswith("Information required"))
    read = client.post(
        f"/api/v1/notifications/{target['notification_id']}/read",
        data={},
        content_type=JSON,
        headers=cmd(),
    )
    assert read.status_code == 200 and read.json()["data"]["read_at"]
    again = client.post(
        f"/api/v1/notifications/{target['notification_id']}/read",
        data={},
        content_type=JSON,
        headers=cmd(),
    )
    assert (
        again.status_code == 200
        and again.json()["data"]["read_at"] == read.json()["data"]["read_at"]
    )
    assert (
        boss.post(
            f"/api/v1/notifications/{target['notification_id']}/read",
            data={},
            content_type=JSON,
            headers=cmd(),
        ).status_code
        == 404
    )
    boundary = mine["as_of"]
    swept = client.post(
        "/api/v1/notifications/read-through",
        data={"through": boundary},
        content_type=JSON,
        headers=cmd(),
    )
    assert swept.status_code == 200
    unread_after = client.get("/api/v1/notifications?unread_only=true").json()["data"]["items"]
    assert all(n["created_at"] > boundary for n in unread_after)
    # Preferences: optional channels cannot suppress mandatory messages (recorded, not enforced
    # against the notice which is mandatory); unknown channel refused.
    prefs = client.patch(
        "/api/v1/me/preferences",
        data={"locale": "en", "optional_channels": ["EMAIL"], "reduced_motion": True},
        content_type=JSON,
    )
    assert prefs.status_code == 200 and prefs.json()["data"]["reduced_motion"] is True
    bad = client.patch(
        "/api/v1/me/preferences", data={"optional_channels": ["FAX"]}, content_type=JSON
    )
    assert bad.status_code == 422
    assert TEMPLATES["notice.published.v1"].mandatory is True
