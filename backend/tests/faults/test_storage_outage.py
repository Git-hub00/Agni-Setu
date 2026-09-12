"""Object storage full / unreachable during an upload and during export generation (docs/08
s.6 "Object upload incomplete", s.10 "fill object storage")."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client

from agni.documents.adapters.memory import MemoryObjectStore
from agni.documents.models import UploadReservation
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.platform.models import LogicalJob
from agni.reporting.models import ExportJob
from tests.integration.test_drafts import create_draft
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture import
from tests.integration.test_submission import cmd
from tests.integration.test_uploads import PDF, reserve, run_worker, sha

JSON = "application/json"


@pytest.mark.django_db
def test_storage_outage_leaves_uploads_incomplete_and_exports_retrying(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    premises: Any,
    service: Any,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    owner, boss = visit["applicant"], visit["boss"]
    store = MemoryObjectStore.shared()
    # ---- upload transfer while storage refuses writes (uploads belong to a draft) -------------
    draft_id = create_draft(owner, premises, service).json()["data"]["application_id"]
    reserved = reserve(owner, draft_id)
    assert reserved.status_code == 201, reserved.content
    ticket = reserved.json()["data"]
    store.fail_writes = True
    try:
        put = owner.put(ticket["upload_url"], data=PDF, content_type="application/pdf")
    finally:
        store.fail_writes = False
    assert put.status_code == 503 and put.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    reservation = UploadReservation.objects.get(pk=ticket["upload_id"])
    assert reservation.state == "RESERVED" and reservation.uploaded_sha256 in (None, "")
    # Completing without bytes is refused: no placeholder evidence.
    incomplete = owner.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data={"sha256": sha(PDF), "size_bytes": len(PDF)},
        content_type=JSON,
        headers=cmd(etag=reserved["ETag"]),
    )
    assert incomplete.status_code == 409 and incomplete.json()["code"] == "UPLOAD_INCOMPLETE"
    # Storage recovers: the same reservation accepts the bytes.
    retry = owner.put(ticket["upload_url"], data=PDF, content_type="application/pdf")
    assert retry.status_code == 200 and retry.json()["data"]["state"] == "UPLOADED"

    # ---- export generation while storage refuses writes ----------------------------------------
    created = boss.post(
        "/api/v1/exports",
        data={
            "kind": "CASES",
            "field_set_key": "case-summary",
            "purpose": "Fault drill export: synthetic demonstration data only.",
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert created.status_code == 202, created.content
    export_id = created.json()["data"]["export_id"]
    job = LogicalJob.objects.get(kind="export.generate", aggregate_ref__export_id=export_id)
    store.fail_writes = True
    try:
        first = run_worker(clock)
    finally:
        store.fail_writes = False
    assert first.retried == 1 and first.completed == 0
    job.refresh_from_db()
    assert job.state == "RETRY_WAIT" and job.last_error_code == "DEPENDENCY_UNAVAILABLE"
    assert ExportJob.objects.get(pk=export_id).state in ("READY", "RUNNING")
    assert ExportJob.objects.get(pk=export_id).artifact_object_key is None
    # Backoff, then the same logical action completes once with one artifact.
    clock.advance(timedelta(minutes=1))
    second = run_worker(clock)
    assert second.completed == 1
    export = ExportJob.objects.get(pk=export_id)
    assert export.state == "COMPLETE" and export.artifact_object_key is not None
    job.refresh_from_db()
    assert job.state == "COMPLETE" and job.attempt_count == 2
    assert job.attempts.count() == 2
    assert [a.outcome for a in job.attempts.order_by("attempt_number")] == ["RETRYABLE", "SUCCESS"]
