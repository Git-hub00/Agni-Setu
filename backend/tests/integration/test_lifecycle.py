"""B13 against real PostgreSQL: guarded withdrawal (TR-13; AT-30), authorised holds (FR-18),
return-for-clarification (TR-14), certificate status instruments and linked renewals (AT-24),
support tickets with audience-filtered conversations, attachments and the disabled appeal
referral (AT-30)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, CaseHold
from agni.certificates.adapters import DemoWatermarkSigner
from agni.certificates.models import Certificate
from agni.identity.contacts import decrypt_contact
from agni.identity.domain.roles import Capability, ScopeKind
from agni.identity.models import Principal, PrincipalKind
from agni.inspections.models import Assignment, Inspection
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.policies.models import Jurisdiction

from .conftest import grant, make_staff
from .test_decisions import approve_payload, decide, decide_grant, review_pending
from .test_reports import (  # noqa: F401 - pytest fixture import
    all_pass,
    clean_evidence,
    submit,
    submit_body,
    visit,
)
from .test_submission import cmd
from .test_sync import scheduled_visit  # noqa: F401 - pytest fixture import
from .test_uploads import PDF, reserve, run_worker, sha

JSON = "application/json"
REASON = "Recorded during the B13 acceptance drill; synthetic demonstration data only."


@pytest.fixture(autouse=True)
def _reset_signer() -> Iterator[None]:
    DemoWatermarkSigner.reset()
    yield
    DemoWatermarkSigner.reset()


def case_etag(client: Client, app_id: str) -> str:
    return str(client.get(f"/api/v1/applications/{app_id}")["ETag"])


def stranger(signed_client: Callable[[Principal], Client]) -> Client:
    return signed_client(
        Principal.objects.create_principal(
            kind=PrincipalKind.APPLICANT, display_name="Stranger Applicant"
        )
    )


# ---- TR-13 -------------------------------------------------------------------------------------


@pytest.mark.django_db
# Cases: AT-30-01 (allowed-stage withdrawal disposes open work) AT-30-02 (terminal case refuses a
# second withdrawal and a hold; empty reason 422) AT-30-04 (staff 403, stranger 404) AT-30-05
# (replay of the terminal command is a 409, never a second disposition)
def test_at_30_01_withdrawal_is_guarded_and_disposes_open_work(
    scheduled_visit: dict[str, Any],  # noqa: F811
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = scheduled_visit
    applicant, boss, app_id = v["applicant"], v["boss"], v["app_id"]
    url = f"/api/v1/applications/{app_id}/withdraw"
    detail = applicant.get(f"/api/v1/applications/{app_id}")
    actions = {a["key"]: a for a in detail.json()["data"]["allowed_actions"]}
    assert actions["withdraw"] == {"key": "withdraw", "enabled": True, "reason_code": None}
    # Staff cannot withdraw on the applicant's behalf; a stranger learns nothing.
    assert (
        boss.post(
            url, data={"reason": REASON}, content_type=JSON, headers=cmd(etag=detail["ETag"])
        ).status_code
        == 403
    )
    assert (
        stranger(signed_client)
        .post(url, data={"reason": REASON}, content_type=JSON, headers=cmd(etag=detail["ETag"]))
        .status_code
        == 404
    )
    assert (
        applicant.post(
            url, data={}, content_type=JSON, headers=cmd(etag=detail["ETag"])
        ).status_code
        == 422
    )
    withdrawn = applicant.post(
        url,
        data={"reason": "We sold the premises before the visit could take place."},
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )
    assert withdrawn.status_code == 200, withdrawn.content
    body = withdrawn.json()["data"]
    assert body["status"] == "WITHDRAWN" and body["from_status"] == "INSPECTION_PENDING"
    assert body["disposition"]["cancelled_attempts"] == [v["inspection_id"]]
    application = Application.objects.get(pk=app_id)
    assert application.status == "WITHDRAWN" and application.closed_at == clock.now()
    states = list(Obligation.objects.filter(application_id=app_id).values_list("state", flat=True))
    assert "CANCELLED" in states and not {"ACTIVE", "PAUSED"} & set(states)
    assert Inspection.objects.get(pk=v["inspection_id"]).status == "CANCELLED"
    assert Assignment.objects.get(inspection_id=v["inspection_id"]).state == "REVOKED"
    timeline = applicant.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    kinds = [e["event_type"] for e in timeline]
    assert "application.withdrawn.v1" in kinds and "case.disposition.v1" not in kinds
    staff_kinds = [
        e["event_type"]
        for e in boss.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "case.disposition.v1" in staff_kinds
    # Terminal: a second withdrawal and a hold are refused; the case stays readable.
    again = applicant.post(
        url,
        data={"reason": REASON},
        content_type=JSON,
        headers=cmd(etag=case_etag(applicant, app_id)),
    )
    assert again.status_code == 409
    hold = boss.post(
        f"/api/v1/applications/{app_id}/holds",
        data={"kind": "ADMINISTRATIVE", "reason": REASON},
        content_type=JSON,
        headers=cmd(etag=case_etag(boss, app_id)),
    )
    assert hold.status_code == 409
    closed_view = applicant.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert closed_view["closed_at"] is not None
    assert {a["key"]: a["enabled"] for a in closed_view["allowed_actions"]}.get("withdraw") in (
        None,
        False,
    )


# ---- holds + TR-14 ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_holds_pause_listed_clocks_block_transitions_and_release_recomputes(
    visit: dict[str, Any],  # noqa: F811
    clock: FrozenClock,
) -> None:
    v = visit
    boss, priya, applicant, app_id = v["boss"], v["priya"], v["applicant"], v["app_id"]
    case = boss.get(f"/api/v1/applications/{app_id}")
    obligations = {o["kind"]: o for o in case.json()["data"]["obligations"]}
    task = obligations["INSPECTION_TASK"]
    assert task["state"] == "ACTIVE" and task["due_at"]
    holds_url = f"/api/v1/applications/{app_id}/holds"
    court = boss.post(
        holds_url,
        data={
            "kind": "COURT_ORDER",
            "reason": REASON,
            "affected_obligation_ids": [task["obligation_id"]],
            "command_block_scope": ["TRANSITIONS"],
        },
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert court.status_code == 422  # a court order cites its basis document
    assert any(x["pointer"] == "/basis_document_id" for x in court.json()["violations"])
    created = boss.post(
        holds_url,
        data={
            "kind": "ADMINISTRATIVE",
            "reason": "Ownership dispute raised by the municipal office; the visit clock waits.",
            "affected_obligation_ids": [task["obligation_id"]],
            "command_block_scope": ["TRANSITIONS"],
        },
        content_type=JSON,
        headers=cmd(etag=case["ETag"]),
    )
    assert created.status_code == 201, created.content
    hold = created.json()["data"]
    assert hold["state"] == "ACTIVE" and hold["affected_obligation_ids"] == [task["obligation_id"]]
    paused = Obligation.objects.get(pk=task["obligation_id"])
    assert paused.state == "PAUSED" and paused.due_at is None
    assert Obligation.objects.get(pk=obligations["CASE_TARGET"]["obligation_id"]).state == "ACTIVE"
    # A transition command is blocked while the hold lists TRANSITIONS; uploads are not. The
    # hold bumped the case version, so the officer re-reads the attempt first.
    fresh = priya.get(f"/api/v1/inspections/{v['inspection_id']}")
    v = {**v, "detail": fresh.json()["data"], "etag": fresh["ETag"]}
    evidence = clean_evidence(v, clock)
    blocked = submit(priya, v, submit_body(v["detail"], all_pass(evidence)))
    assert blocked.status_code == 409, blocked.content
    assert blocked.json()["hold_id"] == hold["hold_id"]
    second = boss.post(
        holds_url,
        data={"kind": "ADMINISTRATIVE", "reason": REASON},
        content_type=JSON,
        headers=cmd(etag=case_etag(boss, app_id)),
    )
    assert second.status_code == 409
    applicant_view = applicant.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert applicant_view["on_hold"] is True and applicant_view["holds"] is None
    staff_view = boss.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert len(staff_view["holds"]) == 1
    staff_actions = {a["key"]: a for a in staff_view["allowed_actions"]}
    assert staff_actions["add-hold"]["reason_code"] == "HOLD_ACTIVE"
    assert staff_actions["release-hold"]["enabled"] is True
    # Release after twenty minutes (inside the session idle limit): stale ETag refused; the
    # clock resumes with the pause added.
    clock.advance(timedelta(minutes=20))
    release_url = f"/api/v1/holds/{hold['hold_id']}/release"
    stale = boss.post(
        release_url, data={"reason": REASON}, content_type=JSON, headers=cmd(etag='"hold:x:v9"')
    )
    assert stale.status_code == 412
    released = boss.post(
        release_url, data={"reason": REASON}, content_type=JSON, headers=cmd(etag=hold["etag"])
    )
    assert released.status_code == 200, released.content
    assert released.json()["data"]["state"] == "RELEASED"
    assert CaseHold.objects.get(pk=hold["hold_id"]).ends_at == clock.now()
    resumed = Obligation.objects.get(pk=task["obligation_id"])
    assert resumed.state == "ACTIVE" and resumed.due_at is not None
    from django.utils.dateparse import parse_datetime

    original_due = parse_datetime(task["due_at"])
    assert original_due is not None and resumed.due_at == original_due + timedelta(minutes=20)
    accepted = submit(priya, v, submit_body(v["detail"], all_pass(evidence)))
    assert accepted.status_code == 201, accepted.content
    assert Application.objects.get(pk=app_id).status == "REVIEW_PENDING"
    # The profile permits withdrawal only before review.
    refused = applicant.post(
        f"/api/v1/applications/{app_id}/withdraw",
        data={"reason": REASON},
        content_type=JSON,
        headers=cmd(etag=case_etag(applicant, app_id)),
    )
    assert refused.status_code == 409 and "REVIEW_PENDING" not in refused.json()["permitted_from"]

    # TR-14: return for clarification needs a new physical attempt in baseline 2.0.
    report_id = accepted.json()["data"]["report"]["report_id"]
    return_url = f"/api/v1/applications/{app_id}/return-review"
    payload = {
        "report_id": report_id,
        "items_requiring_clarification": [
            {"code": "C02", "text": "Confirm the extinguisher service dates on site."}
        ],
        "reason": "The report's extinguisher evidence is ambiguous; a second look is needed.",
        "requires_new_visit": True,
    }
    no_visit = boss.post(
        return_url,
        data={**payload, "requires_new_visit": False},
        content_type=JSON,
        headers=cmd(etag=case_etag(boss, app_id)),
    )
    assert no_visit.status_code == 409 and no_visit.json()["code"] == "SERVICE_DISABLED"
    unknown = boss.post(
        return_url,
        data={**payload, "items_requiring_clarification": [{"code": "C99", "text": "Nothing."}]},
        content_type=JSON,
        headers=cmd(etag=case_etag(boss, app_id)),
    )
    assert unknown.status_code == 422
    returned = boss.post(
        return_url, data=payload, content_type=JSON, headers=cmd(etag=case_etag(boss, app_id))
    )
    assert returned.status_code == 201, returned.content
    attempt = returned.json()["data"]
    assert attempt["purpose"] == "CLARIFICATION" and attempt["attempt_number"] == 2
    assert Application.objects.get(pk=app_id).status == "INSPECTION_PENDING"
    kinds = {
        o.kind: o.state
        for o in Obligation.objects.filter(application_id=app_id).order_by("created_at")
    }
    assert kinds["REVIEW_TASK"] == "SATISFIED" and kinds["INSPECTION_TASK"] == "ACTIVE"
    events = [
        e["event_type"]
        for e in applicant.get(f"/api/v1/applications/{app_id}/timeline").json()["data"]["items"]
    ]
    assert "inspection.clarification_requested.v1" in events
    assert Inspection.objects.filter(application_id=app_id).count() == 2


# ---- AT-24 ---------------------------------------------------------------------------------------


def published_certificate(
    v: dict[str, Any], supervisor: Principal, jurisdiction: Jurisdiction, clock: FrozenClock
) -> tuple[Certificate, str]:
    case = review_pending(v, clock)
    decide_grant(supervisor, jurisdiction, clock)
    readiness = (
        v["boss"].get(f"/api/v1/applications/{v['app_id']}/decision-readiness").json()["data"]
    )
    approved = decide(v["boss"], v["app_id"], approve_payload(readiness), etag=case["etag"])
    assert approved.status_code == 201, approved.content
    run_worker(clock)
    return Certificate.objects.get(application_id=v["app_id"]), str(case["evidence"])


def status_grant(subject: Principal, jurisdiction: Jurisdiction, clock: FrozenClock) -> Any:
    tag = subject.pk.hex[:6]
    return grant(
        subject,
        Capability.CERTIFICATE_STATUS,
        make_staff(f"Bootstrap S {tag}", f"bootstrap-s-{tag}"),
        make_staff(f"Approver S {tag}", f"approver-s-{tag}"),
        clock,
        scope_kind=ScopeKind.JURISDICTION,
        jurisdiction=jurisdiction,
    )


@pytest.mark.django_db
# Cases: AT-24-01 (suspend / reinstate / revoke instruments, linked renewal, public status)
# AT-24-02 (missing evidence 422, inadmissible after expiry 409, revoked is final, renewal from a
# revoked record refused) AT-24-04 (no status grant 403, staff cannot renew 403, holder sees the
# public reason only) AT-24-05 (stale ETag 412, second renewal 409); E2E-16 (renewal leaves the
# source validity untouched)
def test_at_24_status_instruments_renewal_and_expiry(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    plain_supervisor: Principal,
    applicant: Principal,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss, holder = v["boss"], v["applicant"]
    certificate, evidence = published_certificate(v, supervisor, jurisdiction, clock)
    cid = str(certificate.pk)
    url = f"/api/v1/certificates/{cid}/status-actions"
    detail = boss.get(f"/api/v1/certificates/{cid}")
    allowed = {a["action"]: a for a in detail.json()["data"]["allowed_status_actions"]}
    assert allowed["SUSPEND"]["reason_code"] == "AUTHORITY_MISSING"
    status_grant(supervisor, jurisdiction, clock)
    detail = boss.get(f"/api/v1/certificates/{cid}")
    allowed = {a["action"]: a for a in detail.json()["data"]["allowed_status_actions"]}
    assert allowed["SUSPEND"]["enabled"] and allowed["REVOKE"]["enabled"]
    assert allowed["REINSTATE"]["reason_code"] == "NOT_ADMISSIBLE"
    etag = detail["ETag"]
    suspend = {
        "action": "SUSPEND",
        "reason": "Fire door found chained during a complaint visit; suspended pending review.",
        "public_reason": "The certificate is suspended while a reported deficiency is reviewed.",
        "evidence_document_id": evidence,
    }
    no_evidence = boss.post(
        url,
        data={k: x for k, x in suspend.items() if k != "evidence_document_id"},
        content_type=JSON,
        headers=cmd(etag=etag),
    )
    assert no_evidence.status_code == 422
    no_grant = signed_client(plain_supervisor).post(
        url, data=suspend, content_type=JSON, headers=cmd(etag=etag)
    )
    assert no_grant.status_code == 403
    suspended = boss.post(url, data=suspend, content_type=JSON, headers=cmd(etag=etag))
    assert suspended.status_code == 201, suspended.content
    assert suspended.json()["data"]["certificate"]["recorded_status"] == "SUSPENDED"
    token = decrypt_contact(certificate.verification_token_ciphertext)
    public = Client().get(f"/api/v1/public/certificates/{token}").json()["data"]
    assert public["effective_status"] == "SUSPENDED"
    holder_detail = holder.get(f"/api/v1/certificates/{cid}").json()["data"]
    assert len(holder_detail["status_history"]) == 1
    assert "reason" not in holder_detail["status_history"][0]
    assert holder_detail["status_history"][0]["public_reason"] == suspend["public_reason"]
    assert "reason" in boss.get(f"/api/v1/certificates/{cid}").json()["data"]["status_history"][0]
    # Stale version refused; reinstatement of a still-in-force suspension is admissible.
    stale = boss.post(
        url,
        data={"action": "REINSTATE", "reason": REASON, "public_reason": REASON},
        content_type=JSON,
        headers=cmd(etag=etag),
    )
    assert stale.status_code == 412
    reinstated = boss.post(
        url,
        data={"action": "REINSTATE", "reason": REASON, "public_reason": REASON},
        content_type=JSON,
        headers=cmd(etag=suspended["ETag"]),
    )
    assert reinstated.status_code == 201, reinstated.content
    assert Certificate.objects.get(pk=cid).recorded_status == "ACTIVE"

    # Renewal: a new linked DRAFT; the source certificate's validity is untouched.
    valid_until = Certificate.objects.get(pk=cid).valid_until
    renewal_url = f"/api/v1/certificates/{cid}/renewals"
    assert (
        boss.post(
            renewal_url,
            data={"declaration_of_current_details": True},
            content_type=JSON,
            headers=cmd(),
        ).status_code
        == 403
    )
    renewal = holder.post(
        renewal_url, data={"declaration_of_current_details": True}, content_type=JSON, headers=cmd()
    )
    assert renewal.status_code == 201, renewal.content
    draft = renewal.json()["data"]
    assert (
        draft["status"] == "DRAFT"
        and draft["prior_certificate_number"] == certificate.certificate_number
    )
    renewal_case = Application.objects.get(pk=draft["application_id"])
    assert renewal_case.prior_certificate_id == certificate.pk
    assert renewal_case.current_draft_revision is not None
    fields = renewal_case.current_draft_revision.editable_payload["fields"]
    assert fields["application_type"] == "RENEWAL"
    assert fields["prior_certificate_reference"] == certificate.certificate_number
    assert Certificate.objects.get(pk=cid).valid_until == valid_until
    twice = holder.post(
        renewal_url, data={"declaration_of_current_details": True}, content_type=JSON, headers=cmd()
    )
    assert twice.status_code == 409
    assert (
        boss.get(f"/api/v1/certificates/{cid}").json()["data"]["renewals"][0]["status"] == "DRAFT"
    )

    # After expiry (interval passed) nothing reinstates or suspends the record; revocation stays
    # possible for cause and is final. Sessions expired with the clock jump: fresh clients.
    clock.advance(timedelta(days=366))
    fresh_boss = signed_client(supervisor)
    fresh_holder = signed_client(applicant)
    expired_detail = fresh_boss.get(f"/api/v1/certificates/{cid}")
    allowed = {a["action"]: a for a in expired_detail.json()["data"]["allowed_status_actions"]}
    assert expired_detail.json()["data"]["effective_status"] == "EXPIRED"
    assert allowed["SUSPEND"]["reason_code"] == "NOT_ADMISSIBLE"
    assert allowed["REINSTATE"]["reason_code"] == "NOT_ADMISSIBLE"
    assert allowed["REVOKE"]["enabled"] is True
    not_admissible = fresh_boss.post(
        url, data=suspend, content_type=JSON, headers=cmd(etag=expired_detail["ETag"])
    )
    assert not_admissible.status_code == 409
    assert not_admissible.json()["code"] == "CERTIFICATE_STATUS_CONFLICT"
    revoked = fresh_boss.post(
        url,
        data={**suspend, "action": "REVOKE"},
        content_type=JSON,
        headers=cmd(etag=expired_detail["ETag"]),
    )
    assert revoked.status_code == 201, revoked.content
    assert Certificate.objects.get(pk=cid).recorded_status == "REVOKED"
    assert (
        Client().get(f"/api/v1/public/certificates/{token}").json()["data"]["effective_status"]
        == "REVOKED"
    )
    history = fresh_boss.get(f"/api/v1/certificates/{cid}").json()["data"]["status_history"]
    assert [h["action"] for h in history] == ["SUSPEND", "REINSTATE", "REVOKE"]
    # A revoked record is final: no reinstatement, no renewal from it.
    final = fresh_boss.post(
        url,
        data={"action": "REINSTATE", "reason": REASON, "public_reason": REASON},
        content_type=JSON,
        headers=cmd(etag=revoked["ETag"]),
    )
    assert final.status_code == 409
    renewal_case.status = "WITHDRAWN"  # close the earlier draft so the guard tested is the status
    renewal_case.save(update_fields=["status", "updated_at"])
    assert (
        fresh_holder.post(
            renewal_url,
            data={"declaration_of_current_details": True},
            content_type=JSON,
            headers=cmd(),
        ).status_code
        == 409
    )


# ---- AT-30 support ------------------------------------------------------------------------------


def attach(client: Client, ticket_id: str, code: str, data: bytes) -> str:
    reserved = reserve(client, ticket_id, code, data, target_type="SUPPORT_ATTACHMENT")
    assert reserved.status_code == 201, reserved.content
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
    return str(done.json()["data"]["document_version_id"])


@pytest.mark.django_db
# Cases: AT-30-01 (ticket lifecycle with attributed replies) AT-30-02 (disabled appeal route ->
# SERVICE_DISABLED referral; out-of-scope case 422) AT-30-04 (stranger sees nothing, internal notes
# hidden, requester cannot write INTERNAL or resolve); E2E-20 (support never reopens a decision)
def test_at_30_support_tickets_referrals_and_attachments(
    visit: dict[str, Any],  # noqa: F811
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    requester, boss, app_id = v["applicant"], v["boss"], v["app_id"]
    before = Application.objects.get(pk=app_id)
    routes = requester.get("/api/v1/support/routes").json()["data"]
    assert routes["appeals"]["enabled"] is False and routes["appeals"]["referral_text"]
    appeal = requester.post(
        "/api/v1/appeals",
        data={"challenged_decision_id": str(uuid4()), "grounds": "x" * 40},
        content_type=JSON,
        headers=cmd(),
    )
    assert appeal.status_code == 409 and appeal.json()["code"] == "SERVICE_DISABLED"
    assert appeal.json()["referral_text"] == routes["appeals"]["referral_text"]

    create = {
        "category": "TECHNICAL",
        "subject": "Cannot open my inspection appointment",
        "description": "The appointment page shows an error when I open it from my phone.",
        "application_id": app_id,
    }
    out_of_scope = requester.post(
        "/api/v1/tickets",
        data={**create, "application_id": str(uuid4())},
        content_type=JSON,
        headers=cmd(),
    )
    assert out_of_scope.status_code == 422
    created = requester.post("/api/v1/tickets", data=create, content_type=JSON, headers=cmd())
    assert created.status_code == 201, created.content
    ticket = created.json()["data"]
    tid = ticket["ticket_id"]
    assert ticket["state"] == "OPEN" and ticket["owner_queue"] == before.owner_queue.queue_key
    assert len(ticket["messages"]) == 1
    other = stranger(signed_client)
    assert other.get("/api/v1/tickets").json()["data"]["items"] == []
    assert other.get(f"/api/v1/tickets/{tid}").status_code == 404
    listing = boss.get("/api/v1/tickets").json()["data"]
    assert [t["ticket_id"] for t in listing["items"]] == [tid] and listing["support_scope"]

    # Internal notes stay internal; requesters cannot write them.
    etag = boss.get(f"/api/v1/tickets/{tid}")["ETag"]
    note = boss.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "Checked the appointment record; the slot is valid.", "audience": "INTERNAL"},
        content_type=JSON,
        headers=cmd(etag=etag),
    )
    assert note.status_code == 201, note.content
    requester_view = requester.get(f"/api/v1/tickets/{tid}")
    assert all(m["audience"] == "REQUESTER" for m in requester_view.json()["data"]["messages"])
    assert len(requester_view.json()["data"]["messages"]) == 1
    assert len(boss.get(f"/api/v1/tickets/{tid}").json()["data"]["messages"]) == 2
    forbidden = requester.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "sneaky", "audience": "INTERNAL"},
        content_type=JSON,
        headers=cmd(etag=requester_view["ETag"]),
    )
    assert forbidden.status_code == 403

    # Attachments follow the ticket: the requester attaches a scanned file, cites it, and the
    # support agent can open it through the normal reauthorised access route.
    doc_id = attach(requester, tid, "support-screenshot", PDF + b"screenshot")
    run_worker(clock)
    reply = requester.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "Screenshot attached.", "document_version_ids": [doc_id]},
        content_type=JSON,
        headers=cmd(etag=requester.get(f"/api/v1/tickets/{tid}")["ETag"]),
    )
    assert reply.status_code == 201, reply.content
    access = boss.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": "PREVIEW"},
        content_type=JSON,
        headers=cmd(),
    )
    assert access.status_code == 200, access.content
    assert (
        other.post(
            f"/api/v1/documents/{doc_id}/access",
            data={"purpose": "PREVIEW"},
            content_type=JSON,
            headers=cmd(),
        ).status_code
        == 404
    )

    # Support lifecycle: staff reply -> IN_PROGRESS; waiting; requester reply resumes; resolve;
    # requester reopens; close; nothing after CLOSED.
    def status(client: Client, state: str, reason: str = REASON) -> Any:
        return client.post(
            f"/api/v1/tickets/{tid}/status",
            data={"state": state, "reason": reason},
            content_type=JSON,
            headers=cmd(etag=client.get(f"/api/v1/tickets/{tid}")["ETag"]),
        )

    staff_reply = boss.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "Please try again after clearing the app cache.", "audience": "REQUESTER"},
        content_type=JSON,
        headers=cmd(etag=boss.get(f"/api/v1/tickets/{tid}")["ETag"]),
    )
    assert (
        staff_reply.status_code == 201
        and staff_reply.json()["data"]["ticket_state"] == "IN_PROGRESS"
    )
    assert status(boss, "WAITING_FOR_REQUESTER").status_code == 200
    resumed = requester.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "Cleared the cache; it works now."},
        content_type=JSON,
        headers=cmd(etag=requester.get(f"/api/v1/tickets/{tid}")["ETag"]),
    )
    assert resumed.json()["data"]["ticket_state"] == "IN_PROGRESS"
    assert status(requester, "RESOLVED").status_code == 403  # requesters cannot resolve
    assert status(boss, "RESOLVED").status_code == 200
    assert status(requester, "IN_PROGRESS", "It failed again this morning.").status_code == 200
    assert status(boss, "RESOLVED").status_code == 200
    assert status(boss, "CLOSED").status_code == 200
    closed = requester.post(
        f"/api/v1/tickets/{tid}/messages",
        data={"body": "One more thing"},
        content_type=JSON,
        headers=cmd(etag=requester.get(f"/api/v1/tickets/{tid}")["ETag"]),
    )
    assert closed.status_code == 409
    # The regulatory case is untouched by the whole support conversation.
    after = Application.objects.get(pk=app_id)
    assert (after.status, after.version) == (before.status, before.version)
    # A ticket without a case goes to the configured support desk queue.
    general = requester.post(
        "/api/v1/tickets",
        data={
            "category": "HOW_TO",
            "subject": "Where do I find receipts?",
            "description": "I cannot find the receipt for my submitted application.",
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert (
        general.status_code == 201
        and general.json()["data"]["owner_queue"] == "demo-central-review"
    )
