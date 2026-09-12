"""FR-05 / AT-05-01..05: reservations, bounded byte transfer, verified completion, quarantined
versions, the durable scan job (clean, rejected, outage), authorised access and immutability."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Premises
from agni.documents.adapters.memory import MemoryObjectStore
from agni.documents.adapters.scanners import DemoEicarScanner
from agni.documents.models import DocumentAccess, DocumentVersion, UploadReservation
from agni.identity.models import Principal
from agni.platform import jobs
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, JobAttempt, JobState, LogicalJob
from agni.policies.models import Service

from .test_drafts import create_draft, patch_draft

JSON = "application/json"
PDF = b"%PDF-1.7\n" + b"synthetic demo plan " * 40 + b"\n%%EOF\n"
EICAR = (
    b"%PDF-1.7\n" + b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*" + b"\n"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reserve(
    client: Client, app_id: str, code: str = "plan", data: bytes = PDF, **overrides: Any
) -> Any:
    body = {
        "target_type": "APPLICATION_DRAFT",
        "target_id": app_id,
        "original_name": "layout.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(data),
        "requirement_code": code,
    }
    body.update(overrides)
    return client.post(
        "/api/v1/uploads", data=body, content_type=JSON, headers={"Idempotency-Key": str(uuid4())}
    )


def upload_and_complete(client: Client, app_id: str, code: str = "plan", data: bytes = PDF) -> Any:
    reserved = reserve(client, app_id, code, data)
    assert reserved.status_code == 201, reserved.content
    ticket = reserved.json()["data"]
    put = client.put(ticket["upload_url"], data=data, content_type="application/pdf")
    assert put.status_code == 200, put.content
    assert put.json()["data"]["sha256"] == sha(data)
    done = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data={"sha256": sha(data), "size_bytes": len(data)},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": reserved["ETag"]},
    )
    assert done.status_code == 202, done.content
    return done.json()["data"]


def run_worker(clock: FrozenClock) -> jobs.RunReport:
    return jobs.run_due_jobs(owner="test-worker", limit=10, clock=clock)


@pytest.fixture
def draft(
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    signed_client: Callable[[Principal], Client],
) -> tuple[Client, str]:
    client = signed_client(applicant)
    created = create_draft(client, premises, service)
    return client, created.json()["data"]["application_id"]


@pytest.mark.django_db
def test_at_05_01_valid_file_becomes_clean_and_satisfies_requirement(
    draft: tuple[Client, str],
    clock: FrozenClock,
    applicant: Principal,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, app_id = draft
    # The test transaction never commits; execute the on_commit staging cleanup explicitly.
    with django_capture_on_commit_callbacks(execute=True):
        document = upload_and_complete(client, app_id)
    assert document["scan_state"] == "QUARANTINED" and document["sha256"] == sha(PDF)
    doc_id = document["document_version_id"]
    version = DocumentVersion.objects.get(pk=doc_id)
    assert version.object_key == f"objects/{sha(PDF)}" and version.size_bytes == len(PDF)
    job = LogicalJob.objects.get(kind="document.scan", aggregate_ref__document_version_id=doc_id)
    assert job.state == JobState.PENDING
    store = MemoryObjectStore.shared()
    assert store.head(version.object_key) is not None
    staging_key = UploadReservation.objects.get(pk=version.reservation_id).object_key
    assert store.head(staging_key) is None  # staging cleaned after commit

    # Not yet scanned: cannot be opened, cannot satisfy the slot.
    access = client.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": "PREVIEW"},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert access.status_code == 409 and access.json()["code"] == "FILE_QUARANTINED"
    detail = client.get(f"/api/v1/applications/{app_id}")
    linked = patch_draft(
        client, app_id, detail["ETag"], {"draft_revision": 1, "attachment_links": [doc_id]}
    )
    assert linked.status_code == 200
    plan = next(r for r in linked.json()["data"]["requirements"] if r["code"] == "plan")
    assert plan["status"] == "PENDING_SCAN"

    report = run_worker(clock)
    assert report.claimed == 1 and report.completed == 1
    version.refresh_from_db()
    assert (
        version.scan_state == "CLEAN"
        and version.scan_engine == "demo_eicar"
        and version.scanned_at == clock.now()
    )
    assert LogicalJob.objects.get(pk=job.pk).state == JobState.COMPLETE
    assert JobAttempt.objects.get(job=job).outcome == "SUCCESS"
    assert AuditEvent.objects.filter(entity_id=doc_id, action="document.scan_clean").exists()

    plan = next(
        r
        for r in client.get(f"/api/v1/applications/{app_id}").json()["data"]["draft"][
            "requirements"
        ]
        if r["code"] == "plan"
    )
    assert plan["status"] == "SATISFIED" and plan["document_version_id"] == doc_id

    access = client.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": "DOWNLOAD"},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert access.status_code == 200, access.content
    url = access.json()["data"]["url"]
    assert DocumentAccess.objects.filter(
        document_version_id=doc_id, principal=applicant, purpose="DOWNLOAD"
    ).exists()
    content = client.get(url)
    assert content.status_code == 200
    assert (
        content["Content-Type"] == "application/pdf"
        and content["X-Content-Type-Options"] == "nosniff"
    )
    assert content["Content-Disposition"].startswith("attachment")
    assert b"".join(getattr(content, "streaming_content")) == PDF  # noqa: B009
    # Tickets do not transfer to another principal and do not survive their lifetime.
    assert Client().get(url).status_code == 401
    clock.advance(timedelta(seconds=301))
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_at_05_02_blocked_files_never_satisfy_evidence(
    draft: tuple[Client, str], clock: FrozenClock, settings: Any
) -> None:
    client, app_id = draft
    # Malicious: EICAR -> REJECTED, cannot be attached or opened.
    rejected = upload_and_complete(client, app_id, data=EICAR)
    run_worker(clock)
    version = DocumentVersion.objects.get(pk=rejected["document_version_id"])
    assert version.scan_state == "REJECTED" and "Eicar" in version.scan_detail
    detail = client.get(f"/api/v1/applications/{app_id}")
    link = patch_draft(
        client, app_id, detail["ETag"], {"draft_revision": 1, "attachment_links": [str(version.pk)]}
    )
    assert link.status_code == 422 and link.json()["violations"][0]["code"] == "rejected"
    access = client.post(
        f"/api/v1/documents/{version.pk}/access",
        data={"purpose": "PREVIEW"},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert access.status_code == 422 and access.json()["code"] == "FILE_REJECTED"
    assert client.get(f"/api/v1/documents/{version.pk}").json()["data"]["scan_state"] == "REJECTED"

    # Unsupported declared type.
    bad_type = reserve(client, app_id, media_type="application/zip")
    assert (
        bad_type.status_code == 422 and bad_type.json()["violations"][0]["pointer"] == "/media_type"
    )
    # Oversized reservation.
    too_big = reserve(client, app_id, size_bytes=settings.AGNI_UPLOADS["MAX_FILE_BYTES"] + 1)
    assert too_big.status_code == 413 and too_big.json()["code"] == "FILE_TOO_LARGE"
    # Unknown requirement code for this policy/category.
    unknown = reserve(client, app_id, code="passport")
    assert (
        unknown.status_code == 422
        and unknown.json()["violations"][0]["code"] == "unknown_requirement"
    )

    # Truncated transfer: fewer bytes than reserved -> completion refused, nothing created.
    reserved = reserve(client, app_id)
    ticket = reserved.json()["data"]
    assert (
        client.put(ticket["upload_url"], data=PDF[:-10], content_type="application/pdf").status_code
        == 200
    )
    short = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data={"sha256": sha(PDF), "size_bytes": len(PDF)},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": reserved["ETag"]},
    )
    assert short.status_code == 409 and short.json()["code"] == "UPLOAD_INCOMPLETE"
    # Body larger than reserved -> refused at transfer time.
    reserved2 = reserve(client, app_id)
    big_put = client.put(
        reserved2.json()["data"]["upload_url"], data=PDF + b"x" * 10, content_type="application/pdf"
    )
    assert big_put.status_code == 413
    # Declared PDF but PNG bytes -> content sniff refuses at completion.
    fake = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    reserved3 = reserve(client, app_id, data=fake)
    t3 = reserved3.json()["data"]
    assert (
        client.put(t3["upload_url"], data=fake, content_type="application/pdf").status_code == 200
    )
    sniff = client.post(
        f"/api/v1/uploads/{t3['upload_id']}/complete",
        data={"sha256": sha(fake), "size_bytes": len(fake)},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": reserved3["ETag"]},
    )
    assert sniff.status_code == 415
    assert (
        DocumentVersion.objects.filter(application_id=app_id).count() == 1
    )  # only the EICAR version exists
    # No pending scan job leaked for the refused completions.
    assert LogicalJob.objects.filter(kind="document.scan").count() == 1


@pytest.mark.django_db
def test_at_05_03_scanner_outage_leaves_quarantine_and_retries_later(
    draft: tuple[Client, str],
    clock: FrozenClock,
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
) -> None:
    client, app_id = draft
    document = upload_and_complete(client, app_id)
    doc_id = document["document_version_id"]
    DemoEicarScanner.force_unknown = True
    report = run_worker(clock)
    version = DocumentVersion.objects.get(pk=doc_id)
    assert report.claimed == 1 and report.retried == 1 and report.completed == 0, (
        report,
        version.scan_state,
        version.scan_engine,
        version.scan_detail,
    )
    assert version.scan_state == "QUARANTINED"
    job = LogicalJob.objects.get(kind="document.scan")
    assert (
        job.state == JobState.RETRY_WAIT
        and job.attempt_count == 1
        and job.last_error_code == "FILE_QUARANTINED"
    )
    assert job.next_attempt_at is not None and job.next_attempt_at > clock.now()
    # Not due yet: nothing claimed.
    assert run_worker(clock).claimed == 0
    # Storage outage on the next attempt is also a retry, never a verdict.
    DemoEicarScanner.force_unknown = False
    MemoryObjectStore.shared().fail_next_read = True
    clock.advance(timedelta(minutes=1))
    report = run_worker(clock)
    assert (
        report.retried == 1 and DocumentVersion.objects.get(pk=doc_id).scan_state == "QUARANTINED"
    )
    job.refresh_from_db()
    assert job.attempt_count == 2 and job.last_error_code == "DEPENDENCY_UNAVAILABLE"
    clock.advance(timedelta(minutes=3))
    report = run_worker(clock)
    assert report.completed == 1 and DocumentVersion.objects.get(pk=doc_id).scan_state == "CLEAN"
    assert JobAttempt.objects.filter(job=job).count() == 3

    # Expired reservation: a new reservation is the recovery path.
    reserved = reserve(client, app_id)
    ticket = reserved.json()["data"]
    clock.advance(timedelta(minutes=31))
    # The 30-minute session idled out with the clock jump; sign in again like a returning user.
    fresh = signed_client(applicant)
    expired = fresh.put(ticket["upload_url"], data=PDF, content_type="application/pdf")
    assert expired.status_code == 410 and expired.json()["code"] == "UPLOAD_EXPIRED"


@pytest.mark.django_db
def test_at_05_04_scope_other_applicant_cannot_upload_read_or_use_tickets(
    draft: tuple[Client, str],
    other_applicant: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    client, app_id = draft
    document = upload_and_complete(client, app_id)
    run_worker(clock)
    doc_id = document["document_version_id"]
    stranger = signed_client(other_applicant)
    assert reserve(stranger, app_id).status_code == 404
    assert stranger.get(f"/api/v1/documents/{doc_id}").status_code == 404
    denied = stranger.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": "PREVIEW"},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 404
    # A valid ticket issued to the owner is useless to anyone else.
    granted = client.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": "PREVIEW"},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )
    url = granted.json()["data"]["url"]
    assert stranger.get(url).status_code == 404
    assert client.get(url).status_code == 200
    assert DocumentAccess.objects.filter(document_version_id=doc_id).count() == 1


@pytest.mark.django_db
# PROP-15 and AT-X-04 (bytes replaced after completion cannot change the accepted object)
def test_at_05_05_completion_replay_and_byte_replacement_are_safe(
    draft: tuple[Client, str], clock: FrozenClock
) -> None:
    client, app_id = draft
    reserved = reserve(client, app_id)
    ticket = reserved.json()["data"]
    client.put(ticket["upload_url"], data=PDF, content_type="application/pdf")
    key = str(uuid4())
    body = {"sha256": sha(PDF), "size_bytes": len(PDF)}
    first = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data=body,
        content_type=JSON,
        headers={"Idempotency-Key": key, "If-Match": reserved["ETag"]},
    )
    assert first.status_code == 202
    replay = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data=body,
        content_type=JSON,
        headers={"Idempotency-Key": key, "If-Match": reserved["ETag"]},
    )
    assert replay.status_code == 202 and replay.json()["data"]["replayed"] is True
    again = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data=body,
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": first["ETag"]},
    )
    assert (
        again.status_code == 202
        and again.json()["data"]["document_version_id"]
        == first.json()["data"]["document_version_id"]
    )
    assert DocumentVersion.objects.filter(application_id=app_id).count() == 1
    assert LogicalJob.objects.filter(kind="document.scan").count() == 1
    # Byte replacement behind the immutable identity is detected and rejected, never CLEAN.
    version = DocumentVersion.objects.get(application_id=app_id)
    MemoryObjectStore.shared().overwrite_for_test(version.object_key, b"%PDF-1.7 tampered")
    run_worker(clock)
    version.refresh_from_db()
    assert version.scan_state == "REJECTED" and "do not match" in version.scan_detail


@pytest.mark.django_db
def test_job_fence_blocks_a_worker_that_lost_its_lease(clock: FrozenClock) -> None:
    job = jobs.enqueue_job(
        kind="document.scan",
        aggregate_ref={"document_version_id": str(uuid4())},
        run_at=clock.now(),
    )
    [claim] = jobs.claim_due_jobs(owner="w1", now=clock.now())
    assert claim.job.lease_token == 1 and claim.job.state == JobState.RUNNING
    # w1 stalls past its lease; w2 recovers the job with a new token.
    clock.advance(timedelta(seconds=121))
    [claim2] = jobs.claim_due_jobs(owner="w2", now=clock.now())
    assert claim2.job.lease_token == 2 and claim2.attempt.attempt_number == 2
    with pytest.raises(jobs.LeaseLost):
        jobs.finish(claim, jobs.JobResult("SUCCESS"), now=clock.now())
    assert LogicalJob.objects.get(pk=job.pk).state == JobState.RUNNING
    done = jobs.finish(
        claim2, jobs.JobResult("PERMANENT", error_code="RESOURCE_NOT_FOUND"), now=clock.now()
    )
    assert done.state == JobState.DEAD_LETTER
    # Idempotent enqueue: the same logical action never creates a second job.
    same = jobs.enqueue_job(
        kind="document.scan",
        aggregate_ref={},
        run_at=clock.now(),
        logical_action_id=job.logical_action_id,
    )
    assert same.pk == job.pk
