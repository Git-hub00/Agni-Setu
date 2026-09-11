"""Issuance (FR-21; integrations s.5-6; docs/08 s.6). One issuance request per favourable
decision carries the stable identity every retry reuses: the logical action id, the certificate
number, the frozen render snapshot and - once rendered - the artifact. The durable
`certificate.issue` job renders, stores, "signs" through the signer port, verifies the receipt
and publishes in a short guarded transaction (TR-11). An unknown signer outcome stops the
automatic retries (RECONCILIATION_REQUIRED) until a lookup by the same identity settles it;
nothing here allocates a second certificate number or a second decision."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime

from agni.cases.application.submission import enter_stage
from agni.cases.domain.states import ApplicationStatus, transition_for
from agni.cases.models import Application, CaseEvent, EventAudience
from agni.decisions.models import Decision
from agni.documents.adapters import get_object_store
from agni.documents.ports import ObjectStoreError, ObjectStoreUnavailable
from agni.identity.contacts import decrypt_contact as decrypt_secret
from agni.identity.contacts import encrypt_contact as encrypt_secret
from agni.obligations.models import Obligation, ObligationKind, ObligationState
from agni.platform import audit, jobs, outbox
from agni.platform.errors import InvalidTransition
from agni.platform.jobs import JobResult, register
from agni.platform.models import AttemptOutcome, JobState, LogicalJob

from ..adapters import DEMO_ISSUER, get_renderer, get_signer, get_verifier
from ..models import (
    ArtifactMode,
    Certificate,
    CertificateArtifact,
    CertificateSequence,
    IssuanceRequest,
    IssuanceState,
    OutcomeKind,
    RecordedStatus,
)
from ..ports import (
    RendererFailed,
    RendererUnavailable,
    SignerRejected,
    SignerUnavailable,
    SignerUnknownOutcome,
    SignReceipt,
    VerificationResult,
)

JOB_KIND = "certificate.issue"
TEMPLATE_KEY = "demo-certificate"
TEMPLATE_VERSION = 1
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
_NAMESPACE = uuid.UUID("3c1f7a4e-2d6b-4d9a-9f0e-6b1c2d3e4f50")


def issuance_job_id(decision_id: UUID) -> UUID:
    return uuid.uuid5(_NAMESPACE, f"issuance:{decision_id}")


def verification_url(token: str) -> str:
    return f"{str(settings.PUBLIC_VERIFY_BASE_URL).rstrip('/')}/{token}"


# ---- creation (inside the decision command transaction) ----------------------------------------


def allocate_certificate_number(now: datetime) -> str:
    """One human reference per issuance request, allocated under a per-year row lock; a retry of
    the same decision reuses the request and therefore the number."""
    for _ in range(3):
        try:
            with transaction.atomic():
                sequence, _ = CertificateSequence.objects.select_for_update().get_or_create(
                    year=now.year
                )
                sequence.last_number += 1
                sequence.save(update_fields=["last_number"])
                return f"AGNI-DEMO-{now.year}-{sequence.last_number}"
        except IntegrityError:
            continue  # two first allocations of a year raced on the row creation
    raise InvalidTransition("Certificate number allocation failed; retry the decision command")


def create_issuance_request(
    application: Application, decision: Decision, *, now: datetime
) -> IssuanceRequest:
    number = allocate_certificate_number(now)
    request = IssuanceRequest.objects.create(
        application=application,
        decision=decision,
        logical_action_id=issuance_job_id(decision.pk),
        certificate_number=number,
        state=IssuanceState.READY,
        template_key=TEMPLATE_KEY,
        template_version=TEMPLATE_VERSION,
    )
    jobs.enqueue_job(
        kind=JOB_KIND,
        aggregate_ref={
            "issuance_request_id": str(request.pk),
            "application_id": str(application.pk),
        },
        run_at=now,
        logical_action_id=request.logical_action_id,
        owner_queue_id=application.owner_queue_id,
    )
    return request


# ---- the durable job ------------------------------------------------------------------------


def build_snapshot(request: IssuanceRequest, now: datetime) -> dict[str, Any]:
    application = request.application
    premises = application.premises
    policy = request.decision.policy_version
    validity_days = int(policy.payload.get("sample_validity_days", 365))
    return {
        "certificate_number": request.certificate_number,
        "public_reference": application.public_reference,
        "premises_display_name": premises.display_name,
        "locality": premises.locality,
        "category_key": premises.category_key,
        "issued_at": now.isoformat(),
        "valid_until": (now + timedelta(days=validity_days)).isoformat(),
        "issuer": DEMO_ISSUER,
        "mode": ArtifactMode.DEMO_WATERMARK.value,
        "outcome_kind": OutcomeKind.DEMO_CERTIFICATE.value,
        "decision_id": str(request.decision_id),
        "decision_sha256": request.decision.sha256,
        "policy_version_id": str(policy.pk),
        "policy_number": policy.number,
        "template": {"key": request.template_key, "version": request.template_version},
    }


def _ensure_snapshot(request: IssuanceRequest, now: datetime) -> IssuanceRequest:
    """First attempt only: freeze the business data and mint the public verification token
    (hash + recoverable ciphertext; the token itself is never stored in clear)."""
    with transaction.atomic():
        locked = IssuanceRequest.objects.select_for_update().get(pk=request.pk)
        if not locked.render_snapshot:
            token = secrets.token_urlsafe(32)  # 256 bits of randomness (integrations s.5)
            ciphertext, key_version = encrypt_secret(token)
            locked.render_snapshot = build_snapshot(request, now)
            locked.token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            locked.token_ciphertext = ciphertext
            locked.token_key_version = key_version
        if locked.state in (IssuanceState.READY, IssuanceState.RECONCILIATION_REQUIRED):
            locked.state = IssuanceState.PROCESSING
        locked.attempts += 1
        locked.version += 1
        locked.save()
    return IssuanceRequest.objects.select_related(
        "application__premises", "application__owner_queue", "decision__policy_version", "artifact"
    ).get(pk=request.pk)


def _render_and_store(request: IssuanceRequest, now: datetime) -> CertificateArtifact:
    renderer = get_renderer()
    token = decrypt_secret(request.token_ciphertext or b"")
    artifact = renderer.render(
        request.template_key,
        request.template_version,
        {**request.render_snapshot, "verification_url": verification_url(token)},
    )
    store = get_object_store()
    staging_key = f"staging/certificates/{request.pk}/{artifact.sha256}"
    final_key = (
        f"certificates/{request.application_id}/{request.certificate_number}/{artifact.sha256}.pdf"
    )
    store.put_staging(staging_key, [artifact.data], max_bytes=MAX_ARTIFACT_BYTES)
    stored = store.promote(staging_key, final_key, expected_size=len(artifact.data))
    store.delete(staging_key)
    with transaction.atomic():
        row, _ = CertificateArtifact.objects.get_or_create(
            object_key=final_key,
            defaults={
                "issuance_request": request,
                "object_version_id": stored.version_id,
                "sha256": artifact.sha256,
                "size_bytes": len(artifact.data),
                "media_type": artifact.media_type,
                "mode": artifact.mode,
                "renderer": artifact.renderer,
                "renderer_version": artifact.renderer_version,
                "rendered_at": now,
            },
        )
        IssuanceRequest.objects.filter(pk=request.pk).update(artifact=row)
    return row


def _mark(
    request: IssuanceRequest,
    state: str,
    error_code: str,
    note: str,
    *,
    provider_request_id: str | None = None,
) -> None:
    with transaction.atomic():
        locked = IssuanceRequest.objects.select_for_update().get(pk=request.pk)
        if locked.state == IssuanceState.PUBLISHED:
            return
        locked.state = state
        locked.last_error_code = error_code[:80]
        locked.reconciliation_note = note[:2000]
        if provider_request_id:
            locked.provider_request_id = provider_request_id
        locked.version += 1
        locked.save()


@register(JOB_KIND)
def issue_certificate(job: LogicalJob) -> JobResult:
    request_id = UUID(str(job.aggregate_ref.get("issuance_request_id")))
    request = (
        IssuanceRequest.objects.select_related(
            "application__premises",
            "application__owner_queue",
            "decision__policy_version",
            "artifact",
        )
        .filter(pk=request_id)
        .first()
    )
    if request is None:
        return JobResult(AttemptOutcome.PERMANENT, error_code="RESOURCE_NOT_FOUND")
    if request.state == IssuanceState.PUBLISHED:
        return JobResult(AttemptOutcome.SUCCESS, disposition="CANCELLED_AS_OBSOLETE")
    if request.state == IssuanceState.FAILED:
        return JobResult(AttemptOutcome.PERMANENT, error_code="ISSUANCE_FAILED")
    if request.application.status != ApplicationStatus.APPROVED_PENDING_ISSUE.value:
        return JobResult(
            AttemptOutcome.PERMANENT,
            error_code="INVALID_TRANSITION",
            safe_message="the case is no longer awaiting issuance",
        )
    now = jobs.current_clock().now()
    request = _ensure_snapshot(request, now)

    # 1. render + store once; retries reuse the immutable artifact by identity.
    if request.artifact is None:
        try:
            request.artifact = _render_and_store(request, now)
        except (RendererUnavailable, ObjectStoreUnavailable) as exc:
            return JobResult(
                AttemptOutcome.RETRYABLE,
                error_code="DEPENDENCY_UNAVAILABLE",
                safe_message=str(exc)[:120],
            )
        except ObjectStoreError as exc:
            return JobResult(
                AttemptOutcome.RETRYABLE,
                error_code="OBJECT_STORE_ERROR",
                safe_message=str(exc)[:120],
            )
        except RendererFailed as exc:
            _mark(request, IssuanceState.RECONCILIATION_REQUIRED, "RENDER_FAILED", str(exc))
            return JobResult(
                AttemptOutcome.PERMANENT, error_code="RENDER_FAILED", safe_message=str(exc)[:120]
            )
    artifact = request.artifact

    # 2. sign through the port; look up first when an earlier attempt may have reached the signer.
    signer = get_signer()
    stable_id = str(request.logical_action_id)
    receipt: SignReceipt | None = None
    if request.provider_request_id:
        lookup = signer.lookup(stable_id)
        if lookup.status == "COMPLETED" and lookup.receipt is not None:
            receipt = lookup.receipt
        elif lookup.status == "UNKNOWN":
            _mark(
                request,
                IssuanceState.RECONCILIATION_REQUIRED,
                "SIGNER_OUTCOME_UNKNOWN",
                "provider cannot determine the outcome; manual reconciliation required",
                provider_request_id=stable_id,
            )
            return JobResult(
                AttemptOutcome.UNKNOWN,
                error_code="EXTERNAL_OUTCOME_UNKNOWN",
                provider_request_id=stable_id,
                safe_message="signer outcome unknown",
            )
        # NOT_FOUND: the provider confirms no action -> the same identity is submitted again.
    if receipt is None:
        try:
            receipt = signer.submit(stable_id, artifact.sha256, at=now)
        except SignerUnavailable as exc:
            return JobResult(
                AttemptOutcome.RETRYABLE,
                error_code="DEPENDENCY_UNAVAILABLE",
                safe_message=str(exc)[:120],
            )
        except SignerUnknownOutcome as exc:
            _mark(
                request,
                IssuanceState.RECONCILIATION_REQUIRED,
                "SIGNER_OUTCOME_UNKNOWN",
                str(exc),
                provider_request_id=stable_id,
            )
            return JobResult(
                AttemptOutcome.UNKNOWN,
                error_code="EXTERNAL_OUTCOME_UNKNOWN",
                provider_request_id=stable_id,
                safe_message=str(exc)[:120],
            )
        except SignerRejected as exc:
            _mark(request, IssuanceState.RECONCILIATION_REQUIRED, "SIGNATURE_REJECTED", str(exc))
            return JobResult(
                AttemptOutcome.PERMANENT,
                error_code="SIGNATURE_REJECTED",
                safe_message=str(exc)[:120],
            )

    # 3. verify the receipt against the stored artifact identity.
    verification = get_verifier().verify(artifact.sha256, receipt, expected_issuer=DEMO_ISSUER)
    if not verification.valid:
        _mark(
            request,
            IssuanceState.RECONCILIATION_REQUIRED,
            "SIGNATURE_INVALID",
            "receipt does not verify against the stored artifact",
            provider_request_id=receipt.request_id,
        )
        return JobResult(
            AttemptOutcome.PERMANENT,
            error_code="SIGNATURE_INVALID",
            provider_request_id=receipt.request_id,
        )

    # 4. publish inside the completion transaction (fence checked by the worker first).
    def apply() -> None:
        publish(request.pk, receipt, verification, now)

    return JobResult(
        AttemptOutcome.SUCCESS,
        apply=apply,
        provider_request_id=receipt.request_id,
        response_digest=artifact.sha256,
    )


def publish(
    request_id: UUID, receipt: SignReceipt, verification: VerificationResult, now: datetime
) -> None:
    """TR-11 as a short database transaction: re-check the still-valid conditions under the
    request and case locks, create the registry entry, complete the case, satisfy the
    obligations, audit and enqueue the event. Idempotent: an already published request returns."""
    with transaction.atomic():
        request = (
            IssuanceRequest.objects.select_for_update(of=("self",))
            .select_related("artifact", "decision")
            .get(pk=request_id)
        )
        if request.state == IssuanceState.PUBLISHED:
            return
        application = (
            Application.objects.select_for_update(of=("self",))
            .select_related("owner_queue", "premises", "current_stage_instance")
            .get(pk=request.application_id)
        )
        artifact = request.artifact
        if (
            application.status != ApplicationStatus.APPROVED_PENDING_ISSUE.value
            or artifact is None
            or not request.token_hash
            or request.token_ciphertext is None
        ):
            request.state = IssuanceState.RECONCILIATION_REQUIRED
            request.last_error_code = "PUBLISH_PRECONDITION_FAILED"
            request.reconciliation_note = (
                f"case status {application.status}; artifact={'yes' if artifact else 'no'}"
            )
            request.version += 1
            request.save()
            return
        transition = transition_for("publish-instrument", application.status_enum)
        if transition is None:
            request.state = IssuanceState.RECONCILIATION_REQUIRED
            request.last_error_code = "INVALID_TRANSITION"
            request.version += 1
            request.save()
            return
        _, target_state, event_type = transition
        snapshot = request.render_snapshot
        issued_at = parse_datetime(str(snapshot.get("issued_at"))) or now
        valid_until = parse_datetime(str(snapshot.get("valid_until")))
        certificate = Certificate.objects.create(
            application=application,
            issuance_request=request,
            outcome_kind=OutcomeKind.DEMO_CERTIFICATE,
            certificate_number=request.certificate_number,
            verification_token_hash=request.token_hash,
            verification_token_ciphertext=bytes(request.token_ciphertext),
            token_key_version=request.token_key_version,
            artifact=artifact,
            issuer_reference=DEMO_ISSUER,
            issued_at=issued_at,
            valid_until=valid_until,
            recorded_status=RecordedStatus.ACTIVE,
            is_demo=True,
        )
        new_version = application.version + 1
        application.status = target_state.value
        request_ref = uuid.uuid4()
        event = CaseEvent.objects.create(
            application=application,
            aggregate_version=new_version,
            ordinal=0,
            event_type=event_type,
            actor=None,
            actor_kind="SYSTEM",
            occurred_at=now,
            payload={
                "certificate_id": str(certificate.pk),
                "certificate_number": certificate.certificate_number,
                "valid_until": certificate.valid_until.isoformat()
                if certificate.valid_until
                else None,
                "is_demo": True,
                "issuance_request_id": str(request.pk),
            },
            audience=EventAudience.PUBLIC_CASE,
            request_id=request_ref,
            command_receipt=None,
        )
        enter_stage(application, application.status, event, now, application.policy_version_id)
        application.version = new_version
        application.save(
            update_fields=["status", "current_stage_instance", "version", "updated_at"]
        )
        Obligation.objects.filter(
            application=application,
            kind__in=[ObligationKind.ISSUANCE_TASK, ObligationKind.CASE_TARGET],
            state__in=[ObligationState.ACTIVE, ObligationState.PAUSED],
        ).update(state=ObligationState.SATISFIED, satisfied_event=event)
        request.state = IssuanceState.PUBLISHED
        request.published_at = now
        request.provider_request_id = receipt.request_id
        request.signature_verification = {
            "receipt": receipt.as_dict(),
            "verification": dict(verification.evidence),
            "valid": True,
        }
        request.last_error_code = None
        request.version += 1
        request.save()
        audit.record_audit(
            entity_type="application",
            entity_id=application.pk,
            action="certificate.published",
            actor_id=None,
            request_id=request_ref,
            at=now,
            summary={
                "certificate_id": str(certificate.pk),
                "certificate_number": certificate.certificate_number,
                "artifact_sha256": artifact.sha256,
                "provider_request_id": receipt.request_id,
                "mode": artifact.mode,
            },
        )
        audit.record_audit(
            entity_type="certificate",
            entity_id=certificate.pk,
            action="certificate.created",
            actor_id=None,
            request_id=request_ref,
            at=now,
            summary={
                "issuance_request_id": str(request.pk),
                "decision_id": str(request.decision_id),
                "artifact_sha256": artifact.sha256,
            },
        )
        outbox.enqueue_intent(
            event_type=event_type,
            aggregate_type="application",
            aggregate_id=application.pk,
            payload={
                "event_id": str(event.pk),
                "event_type": event_type,
                "schema_version": 1,
                "aggregate_type": "application",
                "aggregate_id": str(application.pk),
                "aggregate_version": new_version,
                "event_ordinal": 0,
                "occurred_at": now.isoformat(),
                "actor_id": None,
                "command_id": None,
                "correlation_id": str(request_ref),
                "payload": event.payload,
            },
            available_at=now,
            logical_action_id=event.pk,
        )


# ---- operator recovery ----------------------------------------------------------------------


def reconcile_issuance(request_id: UUID, *, now: datetime, note: str = "") -> LogicalJob:
    """Docs/16 s.6: resume the SAME issuance identity. The handler looks the provider up by the
    stable request id before any resubmission; no new decision, number or token is created."""
    with transaction.atomic():
        request = IssuanceRequest.objects.select_for_update().get(pk=request_id)
        if request.state == IssuanceState.PUBLISHED:
            raise InvalidTransition("This issuance request is already published")
        request.state = IssuanceState.PROCESSING
        request.reconciliation_note = (note or "operator-triggered reconciliation")[:2000]
        request.version += 1
        request.save()
        job = LogicalJob.objects.select_for_update().get(
            logical_action_id=request.logical_action_id
        )
        job.state = JobState.PENDING
        job.next_attempt_at = now
        job.lease_owner = None
        job.lease_until = None
        job.max_attempts = max(job.max_attempts, job.attempt_count + 1)
        job.save(
            update_fields=[
                "state",
                "next_attempt_at",
                "lease_owner",
                "lease_until",
                "max_attempts",
                "updated_at",
            ]
        )
    return job
