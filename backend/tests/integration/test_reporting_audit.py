"""B14 against real PostgreSQL: reconciled single-cutoff metrics (AT-25), controlled exports with
frozen scope, neutralised cells and expiry (AT-26), the scoped self-auditing audit reader
(AT-28), operator job recovery (API-105/106) and staff/grant governance over HTTP (API-087..093).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, Premises, StageInstance
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import (
    AccessRequest,
    AccessRequestStatus,
    AuthorityGrant,
    Principal,
    PrincipalKind,
)
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, JobAttempt, JobState, LogicalJob
from agni.policies.models import Jurisdiction, Service
from agni.reporting.models import ExportJob

from .conftest import ISSUER, grant, make_staff
from .test_drafts import create_draft
from .test_reports import visit  # noqa: F401 - pytest fixture import
from .test_submission import cmd
from .test_uploads import run_worker

JSON = "application/json"
PURPOSE = "Monthly service review for the demonstration circle; synthetic data only."


def metrics(client: Client, **params: str) -> Any:
    return client.get("/api/v1/reports/summary", params)


# ---- AT-25 -------------------------------------------------------------------------------------


@pytest.mark.django_db
# Cases: AT-25-01 (one cutoff, reconciled) AT-25-02 (future cutoff and unknown ids 422) AT-25-04
# (own cases / strangers / leadership / foreign supervisor / officers 403); PROP-16 (every scoped
# drill-down reconciles to the same population and cutoff)
def test_at_25_01_metrics_reconcile_at_one_cutoff_within_scope(
    visit: dict[str, Any],  # noqa: F811
    other_applicant: Principal,
    leadership: Principal,
    foreign_supervisor: Principal,
    premises: Premises,
    service: Service,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss, app_id = v["boss"], v["app_id"]
    create_draft(v["applicant"], premises, service)  # a draft is never "received"
    body = metrics(boss).json()["data"]
    assert body["definition_version"] == "metrics-v1" and body["reconciled"] is True
    assert body["metrics"]["received"] == 1 and body["metrics"]["open"] == 1
    assert body["metrics"]["completed"] == body["metrics"]["rejected"] == 0
    assert body["by_status"] == {"INSPECTION_PENDING": 1}
    assert body["metrics"]["resolution_hours"]["insufficient_sample"] is True
    assert body["scope"] == {"kind": "JURISDICTIONS", "jurisdiction_ids": [str(jurisdiction.pk)]}
    assert "received" in body["definitions"]
    # Status at an earlier cutoff comes from the stage instance in force then. The frozen clock
    # ran the whole flow at one instant, so spread the recorded stages over the last two hours.
    now = clock.now()
    stages = StageInstance.objects.filter(application_id=app_id)
    assert set(stages.values_list("state", flat=True)) == {
        "DRAFT",
        "SUBMITTED",
        "SCRUTINY",
        "INSPECTION_PENDING",
    }
    stages.filter(state="DRAFT").update(
        entered_at=now - timedelta(hours=3), exited_at=now - timedelta(hours=2)
    )
    stages.filter(state="SUBMITTED").update(
        entered_at=now - timedelta(hours=2), exited_at=now - timedelta(hours=1)
    )
    stages.filter(state="SCRUTINY").update(
        entered_at=now - timedelta(hours=1), exited_at=now - timedelta(minutes=30)
    )
    stages.filter(state="INSPECTION_PENDING").update(entered_at=now - timedelta(minutes=30))
    Application.objects.filter(pk=app_id).update(submitted_at=now - timedelta(hours=2))
    cutoff = {
        "-3h": (now - timedelta(hours=3)).isoformat(),
        "-90m": (now - timedelta(minutes=90)).isoformat(),
        "-60m": (now - timedelta(minutes=60)).isoformat(),  # exited_at is exclusive
        "-45m": (now - timedelta(minutes=45)).isoformat(),
    }
    before = metrics(boss, as_of=cutoff["-3h"]).json()["data"]
    assert before["metrics"]["received"] == 0 and before["reconciled"] is True
    assert metrics(boss, as_of=cutoff["-90m"]).json()["data"]["by_status"] == {"SUBMITTED": 1}
    assert metrics(boss, as_of=cutoff["-60m"]).json()["data"]["by_status"] == {"SCRUTINY": 1}
    assert metrics(boss, as_of=cutoff["-45m"]).json()["data"]["by_status"] == {"SCRUTINY": 1}
    assert metrics(boss).json()["data"]["by_status"] == {"INSPECTION_PENDING": 1}
    future = metrics(boss, as_of=(clock.now() + timedelta(days=1)).isoformat())
    assert future.status_code == 422 and future.json()["code"] == "VALIDATION_FAILED"
    # Filters narrow the same population; unknown ids are rejected.
    assert metrics(boss, category_key="WAREHOUSE").json()["data"]["metrics"]["received"] == 1
    assert metrics(boss, category_key="HOSPITAL").json()["data"]["metrics"]["received"] == 0
    assert metrics(boss, jurisdiction_id="nope").status_code == 422
    # Scope: applicant own cases (draft excluded but counted), strangers nothing, leadership
    # same jurisdiction, foreign supervisor nothing, officers no metrics.
    own = metrics(v["applicant"]).json()["data"]
    assert own["scope"] == {"kind": "OWN_CASES"} and own["metrics"]["received"] == 1
    assert own["exclusions"]["drafts"] == 1
    assert metrics(signed_client(other_applicant)).json()["data"]["metrics"]["received"] == 0
    assert metrics(signed_client(leadership)).json()["data"]["metrics"]["received"] == 1
    assert metrics(signed_client(foreign_supervisor)).json()["data"]["metrics"]["received"] == 0
    assert metrics(v["priya"]).status_code == 403


# ---- AT-26 -------------------------------------------------------------------------------------


def request_export(client: Client, payload: dict[str, Any]) -> Any:
    return client.post("/api/v1/exports", data=payload, content_type=JSON, headers=cmd())


@pytest.mark.django_db
# Cases: AT-26-01 (frozen population, neutralised cells, ticketed access) AT-26-02 (PDF disabled,
# unknown field set / short purpose 422, AUDIT kind without capability 403) AT-26-03 (expired
# artifact -> EXPORT_EXPIRED 410, regeneration is the remedy) AT-26-04 (stranger 404, ticket bound
# to the requester, no applicant identity in the field set); E2E-19 (formula injection blocked)
def test_at_26_01_exports_freeze_scope_neutralise_cells_and_expire(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    leadership: Principal,
    other_applicant: Principal,
    premises: Premises,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss = v["boss"]
    Premises.objects.filter(pk=premises.pk).update(display_name='=HYPERLINK("http://evil")')
    base = {"kind": "CASES", "field_set_key": "case-summary", "purpose": PURPOSE, "format": "CSV"}
    # Validation and policy refusals.
    assert request_export(boss, {**base, "format": "PDF"}).json()["code"] == "SERVICE_DISABLED"
    assert request_export(boss, {**base, "field_set_key": "everything"}).status_code == 422
    assert request_export(boss, {**base, "purpose": "short"}).status_code == 422
    assert (
        request_export(
            boss, {**base, "kind": "AUDIT", "field_set_key": "audit-summary"}
        ).status_code
        == 403
    )
    neha = signed_client(leadership)
    assert request_export(neha, base).status_code == 403  # needs export.sensitive
    grant(
        leadership,
        Capability.EXPORT_SENSITIVE,
        make_staff("Bootstrap X", "bootstrap-x"),
        make_staff("Approver X", "approver-x"),
        clock,
    )
    assert (
        signed_client(leadership)
        .post("/api/v1/exports", data=base, content_type=JSON, headers=cmd())
        .status_code
        == 202
    )
    # The supervisor's export: frozen population, asynchronous generation.
    created = request_export(boss, base)
    assert created.status_code == 202, created.content
    export = created.json()["data"]
    export_id = export["export_id"]
    assert export["state"] == "READY" and export["population"] == 1
    assert export["fields"][0] == "public_reference" and export["scope_valid"] is True
    # Applicants export their own cases as a metrics report too.
    own = request_export(
        v["applicant"], {"kind": "REPORT", "field_set_key": "metrics", "purpose": PURPOSE}
    )
    assert own.status_code == 202, own.content
    report = run_worker(clock)
    assert report.completed >= 3 and report.dead == 0
    status = boss.get(f"/api/v1/exports/{export_id}")
    body = status.json()["data"]
    assert body["state"] == "COMPLETE" and body["row_count"] == 1 and body["scope_valid"] is True
    assert body["allowed_actions"] == [{"key": "access", "enabled": True, "reason_code": None}]
    own_status = v["applicant"].get(f"/api/v1/exports/{own.json()['data']['export_id']}")
    assert own_status.json()["data"]["state"] == "COMPLETE"
    assert own_status.json()["data"]["row_count"] > 5
    # Another account learns nothing about this export.
    stranger = signed_client(other_applicant)
    assert stranger.get(f"/api/v1/exports/{export_id}").status_code == 404
    assert (
        stranger.post(f"/api/v1/exports/{export_id}/access", data={}, content_type=JSON).status_code
        == 404
    )
    # Access is reauthorised, audited and served through a short-lived ticket.
    access = boss.post(
        f"/api/v1/exports/{export_id}/access",
        data={"reason": "Preparing the circle review pack"},
        content_type=JSON,
    )
    assert access.status_code == 200, access.content
    ticket_url = access.json()["data"]["url"]
    assert access.json()["data"]["expires_in_seconds"] > 0
    assert (
        AuditEvent.objects.filter(
            entity_type="export_job", entity_id=export_id, action="export.access_granted"
        ).count()
        == 1
    )
    assert stranger.get(ticket_url).status_code == 404  # ticket is bound to the requester
    artifact = boss.get(ticket_url)
    assert artifact.status_code == 200 and artifact["Content-Type"].startswith("text/csv")
    assert artifact["Cache-Control"] == "private, no-store"
    text = artifact.content.decode("utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# Agni Setu export") and "public_reference" in lines[3]
    row = lines[4]
    assert "'=HYPERLINK" in row and "INSPECTION_PENDING" in row and "WAREHOUSE" in row
    assert "Asha" not in text  # no applicant identity in the field set
    assert ExportJob.objects.get(pk=export_id).artifact_object_key is not None
    # Expiry: the artifact is gone after the retention window; regeneration is the remedy.
    clock.advance(timedelta(hours=25))
    boss_later = signed_client(supervisor)
    assert boss_later.get(f"/api/v1/exports/{export_id}").json()["data"]["state"] == "EXPIRED"
    expired = boss_later.post(f"/api/v1/exports/{export_id}/access", data={}, content_type=JSON)
    assert expired.status_code == 410 and expired.json()["code"] == "EXPORT_EXPIRED"
    # The old ticket is refused too (ticket age runs on wall-clock time; the export expiry on
    # the application clock - either refusal keeps the artifact closed).
    assert boss_later.get(ticket_url).status_code in (404, 410)


# ---- AT-28 -------------------------------------------------------------------------------------


@pytest.mark.django_db
# Cases: AT-28-01 (scoped read, integrity metadata, the read itself audited) AT-28-02 (malformed
# filter 422) AT-28-04 (foreign supervisor sees nothing / 404, applicants 403, leadership and
# administrators read redacted)
def test_at_28_01_audit_reader_is_scoped_redacted_and_self_audited(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    leadership: Principal,
    foreign_supervisor: Principal,
    governance_actors: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
) -> None:
    v = visit
    boss, app_id = v["boss"], v["app_id"]
    listed = boss.get("/api/v1/audit-events", {"entity_type": "application", "entity_id": app_id})
    assert listed.status_code == 200, listed.content
    data = listed.json()["data"]
    assert data["items"] and data["redacted"] is False
    assert all(i["entity_id"] == app_id for i in data["items"])
    assert all(i["action"] != "audit.read" for i in data["items"])
    actions = {i["action"] for i in data["items"]}
    assert "application.submitted" in actions
    # The query itself is on the reader's chain.
    reads = AuditEvent.objects.filter(
        entity_type="audit_query", entity_id=supervisor.pk, action="audit.read"
    )
    assert reads.count() == 1
    assert reads.get().safe_change_summary["count"] == len(data["items"])
    # Detail carries integrity metadata computed on read.
    first = data["items"][0]
    detail = boss.get(f"/api/v1/audit-events/{first['audit_event_id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["integrity"]["chain_valid"] is True
    assert detail.json()["data"]["hash"] == first["hash"]
    # Scope: foreign supervisor sees none and cannot open the row; applicants are refused;
    # leadership and administrators read redacted.
    foreign = signed_client(foreign_supervisor)
    assert foreign.get("/api/v1/audit-events").json()["data"]["items"] == []
    assert foreign.get(f"/api/v1/audit-events/{first['audit_event_id']}").status_code == 404
    assert v["applicant"].get("/api/v1/audit-events").status_code == 403
    neha = signed_client(leadership).get("/api/v1/audit-events", {"entity_id": app_id})
    assert neha.json()["data"]["items"] and neha.json()["data"]["redacted"] is True
    admin = signed_client(governance_actors["admin"])
    everything = admin.get("/api/v1/audit-events", {"limit": "100"}).json()["data"]
    assert everything["redacted"] is True and len(everything["items"]) > len(data["items"])
    reasons = [i["summary"].get("reason") for i in everything["items"] if "reason" in i["summary"]]
    assert reasons and set(reasons) == {"[redacted]"}
    assert admin.get("/api/v1/audit-events", {"from": "yesterday"}).status_code == 422
    # Reads of reads are visible only when asked for explicitly.
    own_reads = boss.get("/api/v1/audit-events", {"action": "audit.read"})
    assert own_reads.status_code == 200
    own_rows = boss.get(
        "/api/v1/audit-events", {"action": "audit.read", "entity_type": "audit_query"}
    ).json()["data"]["items"]
    assert own_rows and all(r["actor_id"] == str(supervisor.pk) for r in own_rows)
    assert (
        AuditEvent.objects.filter(entity_type="audit_query", entity_id=supervisor.pk).count() >= 3
    )


# ---- API-105/106 ---------------------------------------------------------------------------------


def make_job(kind: str, state: str, *, last_outcome: str | None, clock: FrozenClock) -> LogicalJob:
    job = LogicalJob.objects.create(
        logical_action_id=uuid4(),
        kind=kind,
        aggregate_ref={"x": str(uuid4())},
        state=state,
        attempt_count=3,
        max_attempts=3,
        last_error_code="DEPENDENCY_UNAVAILABLE",
    )
    if last_outcome:
        JobAttempt.objects.create(
            job=job,
            attempt_number=3,
            lease_token=3,
            started_at=clock.now() - timedelta(minutes=2),
            ended_at=clock.now() - timedelta(minutes=1),
            outcome=last_outcome,
            safe_error={"code": "DEPENDENCY_UNAVAILABLE"},
        )
    return job


@pytest.mark.django_db
def test_job_recovery_retries_same_action_and_refuses_blind_retry_after_unknown(
    governance_actors: dict[str, Principal],
    supervisor: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    admin = signed_client(governance_actors["admin"])
    dead = make_job(
        "notification.deliver", JobState.DEAD_LETTER, last_outcome="PERMANENT", clock=clock
    )
    url = f"/api/v1/jobs/{dead.pk}/retry"
    reason = {"reason": "Provider outage confirmed over; resume the same delivery."}
    assert (
        signed_client(supervisor)
        .post(url, data=reason, content_type=JSON, headers=cmd())
        .status_code
        == 403
    )
    assert admin.post(url, data={}, content_type=JSON, headers=cmd()).status_code == 422
    retried = admin.post(url, data=reason, content_type=JSON, headers=cmd())
    assert retried.status_code == 202, retried.content
    body = retried.json()["data"]
    assert body["state"] == "PENDING" and body["max_attempts"] == 4
    assert body["logical_action_id"] == str(dead.logical_action_id)
    dead.refresh_from_db()
    assert dead.state == JobState.PENDING and dead.next_attempt_at == clock.now()
    assert AuditEvent.objects.filter(
        entity_type="logical_job", entity_id=dead.pk, action="job.retried"
    ).exists()
    # A retry of a PENDING job is not a transition.
    assert admin.post(url, data=reason, content_type=JSON, headers=cmd()).status_code == 409
    # Ambiguous last outcome: blind retry refused, reconcile first.
    ambiguous = make_job(
        "notification.deliver", JobState.DEAD_LETTER, last_outcome="UNKNOWN", clock=clock
    )
    refused = admin.post(
        f"/api/v1/jobs/{ambiguous.pk}/retry", data=reason, content_type=JSON, headers=cmd()
    )
    assert refused.status_code == 409 and refused.json()["code"] == "INVALID_TRANSITION"
    assert "reconcile" in refused.json()["detail"]
    # Reconcile: only RECONCILIATION_REQUIRED jobs, and only kinds with a procedure.
    pending = make_job("document.scan", JobState.PENDING, last_outcome=None, clock=clock)
    assert (
        admin.post(
            f"/api/v1/jobs/{pending.pk}/reconcile", data=reason, content_type=JSON, headers=cmd()
        ).status_code
        == 409
    )
    no_procedure = make_job(
        "notification.deliver",
        JobState.RECONCILIATION_REQUIRED,
        last_outcome="UNKNOWN",
        clock=clock,
    )
    refused = admin.post(
        f"/api/v1/jobs/{no_procedure.pk}/reconcile", data=reason, content_type=JSON, headers=cmd()
    )
    assert refused.status_code == 409 and refused.json()["job_kind"] == "notification.deliver"
    rescan = make_job(
        "document.scan", JobState.RECONCILIATION_REQUIRED, last_outcome="UNKNOWN", clock=clock
    )
    reconciled = admin.post(
        f"/api/v1/jobs/{rescan.pk}/reconcile", data=reason, content_type=JSON, headers=cmd()
    )
    assert reconciled.status_code == 202, reconciled.content
    assert reconciled.json()["data"]["state"] == "PENDING"
    assert "immutable object version" in reconciled.json()["data"]["procedure"]
    assert AuditEvent.objects.filter(
        entity_type="logical_job", entity_id=rescan.pk, action="job.reconciled"
    ).exists()
    listing = admin.get("/api/v1/jobs", {"state": "PENDING"}).json()["data"]
    assert {j["job_id"] for j in listing["items"]} >= {
        str(dead.pk),
        str(rescan.pk),
        str(pending.pk),
    }


# ---- API-087..093 --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_staff_roster_and_grant_governance_over_http(
    governance_actors: dict[str, Principal],
    supervisor: Principal,
    officers: dict[str, Principal],
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    arjun, editor, meera, bootstrap = (
        governance_actors["admin"],
        governance_actors["editor"],
        governance_actors["approver"],
        governance_actors["bootstrap"],
    )
    admin = signed_client(arjun)
    roster = admin.get("/api/v1/staff").json()["data"]
    assert roster["scope"] == "GLOBAL" and roster["can_manage"] is True
    by_id = {p["principal_id"]: p for p in roster["items"]}
    anita = by_id[str(supervisor.pk)]
    assert anita["roles"][0]["role_key"] == "SUPERVISOR" and anita["roles"][0]["in_force"] is True
    assert anita["roles"][0]["jurisdiction_code"] == jurisdiction.code
    assert anita["workload"] == {"active_assignments": 0} and anita["identity_bound"] is True
    assert "external_subject" not in anita and "login_key" not in anita
    # Supervisors see their jurisdiction's staff read-only; officers see nothing.
    boss = signed_client(supervisor)
    mine = boss.get("/api/v1/staff").json()["data"]
    ids = {p["principal_id"] for p in mine["items"]}
    assert mine["scope"] == "JURISDICTIONS" and mine["can_manage"] is False
    assert {str(officers["suresh"].pk), str(officers["priya"].pk)} <= ids
    assert str(officers["outsider"].pk) not in ids and str(arjun.pk) not in ids
    assert signed_client(officers["priya"]).get("/api/v1/staff").status_code == 403
    # Propose (prepare) a grant; the preparer cannot approve it; an independent approver can.
    proposal = {
        "subject_id": str(supervisor.pk),
        "capability": "certificate.status",
        "scope_kind": "JURISDICTION",
        "jurisdiction_id": str(jurisdiction.pk),
        "reason": "Anita takes over certificate status instruments for the circle.",
    }
    assert (
        admin.post(
            "/api/v1/authority-grants",
            data={**proposal, "scope_kind": "GLOBAL"},
            content_type=JSON,
            headers=cmd(),
        ).status_code
        == 422
    )
    proposed = admin.post(
        "/api/v1/authority-grants", data=proposal, content_type=JSON, headers=cmd()
    )
    assert proposed.status_code == 201, proposed.content
    grant_id = proposed.json()["data"]["grant_id"]
    etag = proposed["ETag"]
    assert proposed.json()["data"]["state"] == "PROPOSED"
    assert (
        admin.post(
            "/api/v1/authority-grants", data=proposal, content_type=JSON, headers=cmd()
        ).status_code
        == 409
    )
    approve_url = f"/api/v1/authority-grants/{grant_id}/approve"
    basis = {"reason": "Approved at the circle governance meeting (synthetic)."}
    assert (
        boss.post(approve_url, data=basis, content_type=JSON, headers=cmd(etag=etag)).status_code
        == 403
    )
    grant(editor, Capability.GRANT_APPROVE, bootstrap, meera, clock)
    second = signed_client(editor)
    assert (
        admin.post(approve_url, data=basis, content_type=JSON, headers=cmd(etag=etag)).status_code
        == 403
    )
    assert second.post(approve_url, data=basis, content_type=JSON, headers=cmd()).status_code == 428
    approved = second.post(approve_url, data=basis, content_type=JSON, headers=cmd(etag=etag))
    assert approved.status_code == 200, approved.content
    assert approved.json()["data"]["state"] == "APPROVED"
    # The subject's epoch moved: existing sessions end, a fresh sign-in sees the new power.
    assert boss.get("/api/v1/authority-grants").status_code in (401, 403)
    supervisor.refresh_from_db()  # the fixture instance still carries the old epoch
    boss = signed_client(supervisor)
    listed = boss.get("/api/v1/authority-grants").json()["data"]["items"]
    mine_grant = next(g for g in listed if g["grant_id"] == grant_id)
    assert (
        mine_grant["state"] == "APPROVED" and mine_grant["subject_display_name"] == "Anita Kapoor"
    )
    revoked = second.post(
        f"/api/v1/authority-grants/{grant_id}/revoke",
        data={"reason": "Rotation complete."},
        content_type=JSON,
        headers=cmd(etag=approved["ETag"]),
    )
    assert revoked.status_code == 200 and revoked.json()["data"]["state"] == "REVOKED"
    # Deactivate an officer: sessions die on the next request; roles and powers are revoked.
    priya = officers["priya"]
    priya_client = signed_client(priya)
    assert priya_client.get("/api/v1/me").status_code == 200
    detail = admin.get(f"/api/v1/staff/{priya.pk}")
    off = admin.post(
        f"/api/v1/staff/{priya.pk}/deactivate",
        data={"reason": "Left the department."},
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )
    assert off.status_code == 200, off.content
    assert priya_client.get("/api/v1/me").status_code in (401, 403)
    after = admin.get(f"/api/v1/staff/{priya.pk}").json()["data"]
    assert after["active"] is False and all(r["revoked_at"] for r in after["roles"])
    # Reactivation needs a NEW approved access request for the same identity (never self).
    request = AccessRequest.objects.create(
        requester=bootstrap,
        intended_issuer=ISSUER,
        intended_subject="priya",
        intended_display_name="Priya Nair",
        requested_role="OFFICER",
        jurisdiction=jurisdiction,
        justification="Returns from secondment.",
        status=AccessRequestStatus.APPROVED,
        approver=meera,
        decision_at=clock.now(),
    )
    provisioner = make_staff("Provisioner P", "provisioner-p")
    from .conftest import bind_role

    bind_role(provisioner, RoleKey.ADMIN, bootstrap, clock)
    grant(provisioner, Capability.STAFF_PROVISION, bootstrap, meera, clock)
    back = signed_client(provisioner).post(
        f"/api/v1/staff/{priya.pk}/reactivate",
        data={"access_request_id": str(request.pk), "reason": "Approved return."},
        content_type=JSON,
        headers=cmd(etag=admin.get(f"/api/v1/staff/{priya.pk}")["ETag"]),
    )
    assert back.status_code == 200, back.content
    assert back.json()["data"]["active"] is True and back.json()["data"]["role_key"] == "OFFICER"
    priya.refresh_from_db()
    assert signed_client(priya).get("/api/v1/me").status_code == 200
    restored = admin.get(f"/api/v1/staff/{priya.pk}").json()["data"]
    assert [r["in_force"] for r in restored["roles"]] == [False, True]
    assert AccessRequest.objects.get(pk=request.pk).consumed_at == clock.now()
    assert not AuthorityGrant.objects.filter(subject=priya, state="APPROVED").exists()
    assert Principal.objects.get(pk=priya.pk).kind == PrincipalKind.STAFF
