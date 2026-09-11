"""FR-20 / AT-20 (guarded decisions), FR-21 / AT-21 (issuance through the simulated renderer and
the demo watermark signer, unknown-outcome reconciliation) and FR-22 / AT-22 (privacy-safe
public verification) through the HTTP API and the durable job worker against real PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, CaseEvent
from agni.certificates.adapters import DemoWatermarkSigner
from agni.certificates.application import issuance
from agni.certificates.models import Certificate, CertificateArtifact, IssuanceRequest
from agni.decisions.models import Decision
from agni.documents.adapters.memory import MemoryObjectStore
from agni.identity.contacts import decrypt_contact
from agni.identity.domain.roles import Capability, RoleKey, ScopeKind
from agni.identity.models import Principal
from agni.obligations.models import Obligation
from agni.platform.clock import FrozenClock
from agni.platform.models import LogicalJob, OutboxMessage
from agni.policies.models import Jurisdiction

from .conftest import bind_role, grant, make_staff
from .test_reports import (  # noqa: F401 - pytest fixture import
    all_pass,
    clean_evidence,
    observation,
    submit,
    submit_body,
    visit,
)
from .test_submission import cmd
from .test_uploads import run_worker

JSON = "application/json"
PUBLIC_FIELDS = {
    "certificate_number",
    "effective_status",
    "premises_display_name",
    "locality",
    "issued_at",
    "valid_until",
    "issuer_label",
    "source",
    "checked_at",
    "is_demo",
    "notice",
}
APPROVE = {
    "kind": "APPROVE",
    "reason": "Reviewed the submitted record and verified closure evidence for the demo checklist.",
    "public_reason": "The demonstration review is complete. Sample certificate processing started.",
    "review_acknowledged": True,
}


@pytest.fixture(autouse=True)
def _reset_signer() -> Iterator[None]:
    DemoWatermarkSigner.reset()
    yield
    DemoWatermarkSigner.reset()


def review_pending(
    v: dict[str, Any], clock: FrozenClock, observations: Any = None
) -> dict[str, Any]:
    """Accept a report (all PASS unless given) -> TR-06 REVIEW_PENDING; return the case facts."""
    evidence = clean_evidence(v, clock)
    accepted = submit(v["priya"], v, submit_body(v["detail"], observations or all_pass(evidence)))
    assert accepted.status_code == 201, accepted.content
    detail = v["boss"].get(f"/api/v1/applications/{v['app_id']}")
    data = detail.json()["data"]
    assert data["status"] == "REVIEW_PENDING"
    return {
        "detail": data,
        "etag": detail["ETag"],
        "evidence": evidence,
        "report_id": accepted.json()["data"]["report"]["report_id"],
    }


def decide_grant(subject: Principal, jurisdiction: Jurisdiction, clock: FrozenClock) -> Any:
    bootstrap = make_staff(f"Bootstrap D {subject.pk.hex[:6]}", f"bootstrap-d-{subject.pk.hex[:6]}")
    approver = make_staff(f"Approver D {subject.pk.hex[:6]}", f"approver-d-{subject.pk.hex[:6]}")
    return grant(
        subject,
        Capability.CASE_DECIDE,
        bootstrap,
        approver,
        clock,
        scope_kind=ScopeKind.JURISDICTION,
        jurisdiction=jurisdiction,
    )


def decide(
    client: Client, app_id: str, payload: dict[str, Any], *, etag: str, key: str | None = None
) -> Any:
    return client.post(
        f"/api/v1/applications/{app_id}/decisions",
        data=payload,
        content_type=JSON,
        headers=cmd(etag=etag, key=key),
    )


def approve_payload(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        **APPROVE,
        "submission_revision_id": readiness["evidence"]["submission_revision_id"],
        "report_id": readiness["evidence"]["report_id"],
    }


@pytest.mark.django_db
def test_at_20_01_21_01_22_01_favourable_decision_issues_exactly_one_sample_certificate(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss, applicant, app_id = v["boss"], v["applicant"], v["app_id"]
    case = review_pending(v, clock)
    url = f"/api/v1/applications/{app_id}/decision-readiness"
    # API-064 without decision authority: the read result lists the missing grant.
    ready = boss.get(url)
    assert ready.status_code == 200 and ready["Cache-Control"] == "no-store"
    assert ready.json()["data"]["approve"]["eligible"] is False
    assert [b["code"] for b in ready.json()["data"]["approve"]["blockers"]] == ["AUTHORITY_MISSING"]
    assert applicant.get(url).status_code == 403
    detail = boss.get(f"/api/v1/applications/{app_id}").json()["data"]
    actions = {a["key"]: a for a in detail["allowed_actions"]}
    assert actions["approve"] == {
        "key": "approve",
        "enabled": False,
        "reason_code": "AUTHORITY_MISSING",
    }

    authority = decide_grant(supervisor, jurisdiction, clock)
    readiness = boss.get(url).json()["data"]
    assert readiness["approve"]["eligible"] is True and readiness["reject"]["eligible"] is True
    assert readiness["evidence"]["report_id"] == case["report_id"]
    assert readiness["authority"]["grant_id"] == str(authority.pk)
    payload = approve_payload(readiness)

    # Guard rails: explicit acknowledgment, current evidence, no caller-specified outcome fields,
    # and the version precondition.
    r = decide(boss, app_id, {**payload, "review_acknowledged": False}, etag=case["etag"])
    assert r.status_code == 422 and any(
        x["pointer"] == "/review_acknowledged" for x in r.json()["violations"]
    )
    r = decide(boss, app_id, {**payload, "submission_revision_id": str(uuid4())}, etag=case["etag"])
    assert r.status_code == 412 and r.json()["code"] == "VERSION_CONFLICT"
    assert r.json()["changed"] == "submission_revision"
    r = decide(
        boss, app_id, {**payload, "certificate_number": "AGNI-DEMO-2026-999"}, etag=case["etag"]
    )
    assert r.status_code == 422
    r = boss.post(
        f"/api/v1/applications/{app_id}/decisions", data=payload, content_type=JSON, headers=cmd()
    )
    assert r.status_code == 428
    r = decide(boss, app_id, payload, etag='"application:x:v1"')
    assert r.status_code == 412

    # TR-10: one favourable decision, one issuance intent, same key -> same decision.
    key = str(uuid4())
    first = decide(boss, app_id, payload, etag=case["etag"], key=key)
    assert first.status_code == 201, first.content
    receipt = first.json()["data"]
    assert receipt["status"] == "APPROVED_PENDING_ISSUE" and receipt["kind"] == "APPROVE"
    number = receipt["issuance"]["certificate_number"]
    assert (
        number.startswith(f"AGNI-DEMO-{clock.now().year}-")
        and receipt["issuance"]["state"] == "READY"
    )
    again = decide(boss, app_id, payload, etag=case["etag"], key=key)
    assert again.status_code == 201 and again.json()["data"]["replayed"] is True
    assert again.json()["data"]["decision_id"] == receipt["decision_id"]
    assert Decision.objects.filter(application_id=app_id).count() == 1
    decision = Decision.objects.get(pk=receipt["decision_id"])
    assert decision.authority_grant_id == authority.pk and decision.actor_id == supervisor.pk
    assert decision.evidence_snapshot["report_id"] == case["report_id"]
    assert decision.evidence_snapshot["submission_revision_id"] == payload["submission_revision_id"]
    current_etag = boss.get(f"/api/v1/applications/{app_id}")["ETag"]
    twice = decide(boss, app_id, payload, etag=current_etag)
    assert twice.status_code == 409
    assert Decision.objects.filter(application_id=app_id).count() == 1
    kinds = {o.kind: o.state for o in Obligation.objects.filter(application_id=app_id)}
    assert kinds["REVIEW_TASK"] == "SATISFIED" and kinds["ISSUANCE_TASK"] == "ACTIVE"
    assert CaseEvent.objects.filter(
        application_id=app_id, event_type="decision.approved.v1", audience="PUBLIC_CASE"
    ).exists()
    assert CaseEvent.objects.filter(
        application_id=app_id, event_type="decision.rationale.v1", audience="INTERNAL"
    ).exists()
    # The applicant sees the public decision and "certificate processing", never the rationale.
    public_view = applicant.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert public_view["status"] == "APPROVED_PENDING_ISSUE"
    assert public_view["decision"]["public_reason"] == payload["public_reason"]
    assert "reason" not in public_view["decision"] and public_view["certificate"] is None
    assert public_view["issuance"]["state"] == "READY" and "attempts" not in public_view["issuance"]
    staff_view = boss.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert staff_view["decision"]["reason"] == payload["reason"]
    staff_actions = {a["key"]: a for a in staff_view["allowed_actions"]}
    assert staff_actions["publish-instrument"]["reason_code"] == "SYSTEM_JOB"  # TR-11 = job
    request = IssuanceRequest.objects.get(application_id=app_id)
    assert LogicalJob.objects.get(logical_action_id=request.logical_action_id).state == "PENDING"

    # TR-11 by the worker: render (simulated PDF), store, demo-watermark receipt, verify, publish.
    report = run_worker(clock)
    assert report.completed >= 1, report
    request.refresh_from_db()
    assert request.state == "PUBLISHED" and request.artifact is not None
    assert request.signature_verification is not None and request.signature_verification["valid"]
    certificate = Certificate.objects.get(application_id=app_id)
    assert certificate.certificate_number == number and certificate.recorded_status == "ACTIVE"
    assert certificate.is_demo is True and certificate.artifact_id == request.artifact_id
    assert certificate.valid_until == certificate.issued_at + timedelta(days=365)
    assert Application.objects.get(pk=app_id).status == "COMPLETED"
    kinds = {o.kind: o.state for o in Obligation.objects.filter(application_id=app_id)}
    assert kinds["ISSUANCE_TASK"] == "SATISFIED" and kinds["CASE_TARGET"] == "SATISFIED"
    assert CaseEvent.objects.filter(
        application_id=app_id, event_type="certificate.published.v1", actor__isnull=True
    ).exists()
    assert OutboxMessage.objects.filter(event_type="certificate.published.v1").count() == 1
    data = b"".join(
        MemoryObjectStore.shared().read(request.artifact.object_key, max_bytes=10_000_000)
    )
    assert data.startswith(b"%PDF") and b"DEMONSTRATION - NOT AN OFFICIAL CERTIFICATE" in data
    # A second worker pass changes nothing.
    run_worker(clock)
    assert Certificate.objects.filter(application_id=app_id).count() == 1

    # API-067/068: applicant and supervisor see the same register entry; artifact access is a
    # separate reauthorised, ticketed, audited operation bound to the reader.
    listing = applicant.get("/api/v1/certificates").json()["data"]
    assert [c["certificate_number"] for c in listing["items"]] == [number]
    assert listing["items"][0]["effective_status"] == "ACTIVE" and listing["items"][0]["is_demo"]
    assert listing["pending_issuance"] == []
    assert boss.get("/api/v1/certificates").json()["data"]["items"][0]["certificate_id"] == str(
        certificate.pk
    )
    detail_view = applicant.get(f"/api/v1/certificates/{certificate.pk}")
    assert detail_view.status_code == 200 and detail_view["ETag"] == certificate.etag
    assert detail_view.json()["data"]["artifact"]["mode"] == "DEMO_WATERMARK"
    assert detail_view.json()["data"]["status_history"] == []
    access = applicant.post(
        f"/api/v1/certificates/{certificate.pk}/access", data={}, content_type=JSON, headers=cmd()
    )
    assert access.status_code == 200, access.content
    download = applicant.get(access.json()["data"]["url"])
    assert download.status_code == 200 and download["Content-Type"] == "application/pdf"
    assert (
        download.content.startswith(b"%PDF")
        and download["X-Agni-Artifact-Mode"] == "DEMO_WATERMARK"
    )
    assert download["Cache-Control"] == "private, no-store"
    assert boss.get(access.json()["data"]["url"]).status_code == 404  # ticket bound to the reader

    # API-073: public verification by token; approved fields only; no-store; unknown -> 404.
    token = decrypt_contact(certificate.verification_token_ciphertext)
    public = Client().get(f"/api/v1/public/certificates/{token}")
    assert public.status_code == 200 and public["Cache-Control"] == "no-store"
    body = public.json()["data"]
    assert body["effective_status"] == "ACTIVE" and body["is_demo"] is True
    assert body["certificate_number"] == number and set(body) <= PUBLIC_FIELDS
    assert Client().get(f"/api/v1/public/certificates/{number}").status_code == 200  # demo profile
    assert Client().get("/api/v1/public/certificates/not-a-real-token-value").status_code == 404
    # AT-22-05: expiry is derived at query time from the interval; the recorded state stays.
    clock.advance(timedelta(days=366))
    expired = Client().get(f"/api/v1/public/certificates/{token}").json()["data"]
    assert expired["effective_status"] == "EXPIRED"
    assert Certificate.objects.get(pk=certificate.pk).recorded_status == "ACTIVE"
    # Sessions expired with the clock jump: a fresh supervisor session sees the derived status.
    fresh = signed_client(supervisor)
    assert fresh.get("/api/v1/certificates?effective_status=ACTIVE").json()["data"]["items"] == []
    historical = fresh.get("/api/v1/certificates?effective_status=EXPIRED").json()["data"]["items"]
    assert [c["recorded_status"] for c in historical] == ["ACTIVE"]


@pytest.mark.django_db
def test_at_20_02_20_04_blocked_decisions_and_rejection(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    plain_supervisor: Principal,
    officers: dict[str, Principal],
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss, app_id = v["boss"], v["app_id"]
    evidence = clean_evidence(v, clock)
    case = review_pending(
        v,
        clock,
        [
            observation(
                "C01", "FAIL", "Rear escape route padlocked and stacked with cartons", [evidence]
            ),
            observation("C02", "PASS", "Six extinguishers in date", docs=[evidence]),
            observation("C07", "PASS", "Two access points clear"),
        ],
    )
    decide_grant(supervisor, jurisdiction, clock)
    url = f"/api/v1/applications/{app_id}/decision-readiness"
    readiness = boss.get(url).json()["data"]
    codes = [b["code"] for b in readiness["approve"]["blockers"]]
    assert "REPORT_NOT_ELIGIBLE" in codes and "MANDATORY_FINDINGS_OPEN" in codes
    assert readiness["reject"]["eligible"] is True
    payload = approve_payload(readiness)
    # Mandatory failure blocks approval (never compensated by anything).
    blocked = decide(boss, app_id, payload, etag=case["etag"])
    assert blocked.status_code == 409 and blocked.json()["code"] == "INVALID_TRANSITION"
    assert {b["code"] for b in blocked.json()["blockers"]} >= {"REPORT_NOT_ELIGIBLE"}
    assert not Decision.objects.exists()

    # Separation of duties: the inspecting officer cannot decide, even as a supervisor with a
    # grant.
    priya = officers["priya"]
    bind_role(
        priya,
        RoleKey.SUPERVISOR,
        make_staff("Bootstrap SoD", "bootstrap-sod"),
        clock,
        jurisdiction=jurisdiction,
    )
    decide_grant(priya, jurisdiction, clock)
    priya_client = signed_client(priya)
    priya_ready = priya_client.get(url).json()["data"]
    assert "SEPARATION_OF_DUTIES" in [b["code"] for b in priya_ready["reject"]["blockers"]]
    sod = decide(priya_client, app_id, {**payload, "kind": "REJECT"}, etag=case["etag"])
    assert sod.status_code == 403 and sod.json()["code"] == "SEPARATION_OF_DUTIES"

    # Authority scoped to another jurisdiction is not authority here.
    elsewhere = Jurisdiction.objects.create(code="ELSEWHERE-D", display_name="Elsewhere D")
    decide_grant(plain_supervisor, elsewhere, clock)
    scoped = decide(
        signed_client(plain_supervisor), app_id, {**payload, "kind": "REJECT"}, etag=case["etag"]
    )
    assert scoped.status_code == 403 and scoped.json()["code"] == "AUTHORITY_SCOPE_MISMATCH"
    # An applicant or a stranger never reaches the command.
    assert v["applicant"].post(
        f"/api/v1/applications/{app_id}/decisions",
        data=payload,
        content_type=JSON,
        headers=cmd(etag=case["etag"]),
    ).status_code in (403, 404)
    assert not Decision.objects.exists()

    # TR-12 rejection from REVIEW_PENDING (profile-permitted) with a public reason.
    rejected = decide(
        boss,
        app_id,
        {
            "kind": "REJECT",
            "submission_revision_id": payload["submission_revision_id"],
            "reason": (
                "Mandatory escape-route deficiency; the applicant did not pursue corrections."
            ),
            "public_reason": (
                "The application was not approved because a mandatory fire-safety item failed."
            ),
            "review_acknowledged": True,
        },
        etag=case["etag"],
    )
    assert rejected.status_code == 201, rejected.content
    assert (
        rejected.json()["data"]["status"] == "REJECTED"
        and rejected.json()["data"]["issuance"] is None
    )
    application = Application.objects.get(pk=app_id)
    assert application.status == "REJECTED"
    states = {o.state for o in Obligation.objects.filter(application_id=app_id)}
    assert states <= {"SATISFIED", "CANCELLED"} and "ACTIVE" not in states
    assert not IssuanceRequest.objects.exists()
    assert CaseEvent.objects.filter(
        application_id=app_id, event_type="decision.rejected.v1", audience="PUBLIC_CASE"
    ).exists()
    applicant_view = v["applicant"].get(f"/api/v1/applications/{app_id}").json()["data"]
    assert (
        applicant_view["decision"]["kind"] == "REJECT"
        and "reason" not in applicant_view["decision"]
    )
    # Terminal: a second decision is refused; nothing else moves.
    later = boss.get(f"/api/v1/applications/{app_id}")["ETag"]
    assert decide(boss, app_id, payload, etag=later).status_code == 409
    assert Decision.objects.filter(application_id=app_id).count() == 1


@pytest.mark.django_db
def test_at_21_02_21_03_unknown_signer_outcome_reconciles_without_a_second_certificate(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    boss, app_id = v["boss"], v["app_id"]
    case = review_pending(v, clock)
    decide_grant(supervisor, jurisdiction, clock)
    readiness = boss.get(f"/api/v1/applications/{app_id}/decision-readiness").json()["data"]
    approved = decide(boss, app_id, approve_payload(readiness), etag=case["etag"])
    assert approved.status_code == 201, approved.content
    request = IssuanceRequest.objects.get(application_id=app_id)
    job = LogicalJob.objects.get(logical_action_id=request.logical_action_id)

    # Signer outage before the request reaches it: a plain retry with the same identity.
    DemoWatermarkSigner.force_outcome = "unavailable"
    run_worker(clock)
    job.refresh_from_db()
    request.refresh_from_db()
    assert job.state == "RETRY_WAIT" and request.state == "PROCESSING"
    assert request.artifact is not None  # rendered once; retries reuse it
    artifact_sha = request.artifact.sha256
    assert not Certificate.objects.exists()

    # Timeout after the request reached the signer: UNKNOWN -> reconciliation, no retry storm.
    DemoWatermarkSigner.force_outcome = "unknown"
    clock.advance(timedelta(minutes=3))  # past the first backoff step (docs/08 s.4)
    run_worker(clock)
    job.refresh_from_db()
    request.refresh_from_db()
    assert job.state == "RECONCILIATION_REQUIRED"
    assert request.state == "RECONCILIATION_REQUIRED"
    assert request.provider_request_id == str(request.logical_action_id)
    assert request.last_error_code == "SIGNER_OUTCOME_UNKNOWN"
    assert Application.objects.get(pk=app_id).status == "APPROVED_PENDING_ISSUE"
    assert not Certificate.objects.exists()
    clock.advance(timedelta(hours=3))
    run_worker(clock)  # nothing is due: reconciliation is a human/operator step
    assert not Certificate.objects.exists()
    fresh = signed_client(supervisor)  # the clock jump expired the earlier session
    register = fresh.get("/api/v1/certificates").json()["data"]
    assert register["pending_issuance"][0]["certificate_number"] == request.certificate_number
    assert register["pending_issuance"][0]["state"] == "RECONCILIATION_REQUIRED"
    assert register["items"] == []  # a reserved number is never listed as issued

    # Operator reconciliation: the SAME identity runs again; the provider lookup finds the
    # completed signing, so the artifact is verified and published once.
    DemoWatermarkSigner.force_outcome = None
    issuance.reconcile_issuance(request.pk, now=clock.now(), note="AT-21-03 drill")
    run_worker(clock)
    request.refresh_from_db()
    assert request.state == "PUBLISHED"
    certificate = Certificate.objects.get(application_id=app_id)
    assert certificate.certificate_number == request.certificate_number
    assert certificate.artifact is not None and certificate.artifact.sha256 == artifact_sha
    assert CertificateArtifact.objects.filter(issuance_request=request).count() == 1
    assert IssuanceRequest.objects.count() == 1 and Certificate.objects.count() == 1
    assert Application.objects.get(pk=app_id).status == "COMPLETED"
    assert request.signature_verification is not None
    assert request.signature_verification["receipt"]["request_id"] == str(request.logical_action_id)
