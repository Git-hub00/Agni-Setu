"""Worker killed after the remote effect (the signer accepted the request) but before the
completion transaction (docs/08 s.10 first proof; s.3 fencing). The lease expires, another
worker recovers the SAME logical action, the provider's idempotency returns the same receipt,
exactly one certificate is published, and the dead worker's late completion is refused."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from agni.cases.models import Application
from agni.certificates.adapters import DemoWatermarkSigner
from agni.certificates.application import issuance
from agni.certificates.models import Certificate, CertificateArtifact, IssuanceRequest
from agni.identity.models import Principal
from agni.platform import jobs
from agni.platform.clock import FrozenClock
from agni.platform.models import LogicalJob
from agni.policies.models import Jurisdiction
from tests.integration.test_decisions import approve_payload, decide, decide_grant, review_pending
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture import
from tests.integration.test_uploads import run_worker


@pytest.fixture(autouse=True)
def _reset_signer() -> Iterator[None]:
    DemoWatermarkSigner.reset()
    yield
    DemoWatermarkSigner.reset()


@pytest.mark.django_db
def test_worker_crash_after_signing_recovers_the_same_action_with_one_certificate(
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

    # Worker 1 claims the job and executes the handler: render, store, SUBMIT to the signer.
    jobs._ACTIVE_CLOCK = clock
    try:
        claims = jobs.claim_due_jobs(owner="worker-1", now=clock.now())
        assert [c.job.pk for c in claims] == [job.pk]
        crashed_claim = claims[0]
        result = issuance.issue_certificate(crashed_claim.job)
    finally:
        jobs._ACTIVE_CLOCK = None
    assert result.outcome == "SUCCESS" and result.apply is not None
    assert list(DemoWatermarkSigner._submitted) == [str(request.logical_action_id)]
    # ... and dies here: no completion transaction. The job is RUNNING under worker-1's lease.
    job.refresh_from_db()
    request.refresh_from_db()
    assert job.state == "RUNNING" and job.lease_owner == "worker-1" and job.attempt_count == 1
    assert request.state == "PROCESSING" and request.artifact is not None
    assert not Certificate.objects.exists()
    assert Application.objects.get(pk=app_id).status == "APPROVED_PENDING_ISSUE"

    # While the lease is live nobody else may take the job.
    clock.advance(timedelta(seconds=10))
    assert run_worker(clock).claimed == 0

    # Lease expiry -> worker 2 recovers the SAME logical action. The provider returns the same
    # receipt for the stable request id, so verification and publication happen exactly once.
    clock.advance(timedelta(seconds=settings.AGNI_JOBS["LEASE_SECONDS"] + 1))
    report = run_worker(clock)
    assert report.claimed == 1 and report.completed == 1 and report.lost == 0
    job.refresh_from_db()
    request.refresh_from_db()
    assert job.state == "COMPLETE" and job.attempt_count == 2
    attempts = list(job.attempts.order_by("attempt_number"))
    assert [a.outcome for a in attempts] == [None, "SUCCESS"]  # the crash left no outcome
    assert attempts[0].ended_at is None and attempts[1].ended_at == clock.now()
    assert request.state == "PUBLISHED"
    assert Certificate.objects.filter(application_id=app_id).count() == 1
    assert CertificateArtifact.objects.filter(issuance_request=request).count() == 1
    assert len(DemoWatermarkSigner._submitted) == 1  # one provider request identity
    assert Application.objects.get(pk=app_id).status == "COMPLETED"

    # The dead worker comes back and tries to record its stale completion: fenced out.
    with pytest.raises(jobs.LeaseLost):
        jobs.finish(crashed_claim, result, now=clock.now())
    assert Certificate.objects.count() == 1 and IssuanceRequest.objects.count() == 1
    # Nothing further is due.
    assert run_worker(clock).claimed == 0
