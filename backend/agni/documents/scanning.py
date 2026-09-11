"""`document.scan` job handler (integrations s.3 step 5, docs/08 s.6). Reads the exact immutable
object, re-verifies its SHA-256, scans it, and records CLEAN/REJECTED bound to that identity.
Scanner outage or unreadable storage leaves the version QUARANTINED and the job retrying;
nothing ever infers CLEAN from a timeout."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from django.conf import settings

from agni.platform import audit
from agni.platform.clock import get_clock
from agni.platform.jobs import JobResult, register
from agni.platform.models import AttemptOutcome, LogicalJob

from .adapters import get_object_store, get_scanner
from .models import DocumentVersion, ScanState
from .ports import ObjectNotFound, ObjectStoreUnavailable, ObjectTooLarge

JOB_KIND = "document.scan"


@register(JOB_KIND)
def scan_document(job: LogicalJob) -> JobResult:
    version_id = UUID(str(job.aggregate_ref.get("document_version_id")))
    version = DocumentVersion.objects.filter(pk=version_id).first()
    if version is None:
        return JobResult(AttemptOutcome.PERMANENT, error_code="RESOURCE_NOT_FOUND")
    if version.scan_state != ScanState.QUARANTINED:
        return JobResult(AttemptOutcome.SUCCESS, disposition="CANCELLED_AS_OBSOLETE")

    store = get_object_store()
    scanner = get_scanner()
    now = get_clock().now()
    max_bytes = int(settings.AGNI_UPLOADS["MAX_FILE_BYTES"])
    try:
        # Read the whole (bounded) object first so the identity check never depends on how much
        # of the stream a scanner consumed before failing.
        data = b"".join(store.read(version.object_key, max_bytes=max_bytes))
    except ObjectStoreUnavailable as exc:
        return JobResult(
            AttemptOutcome.RETRYABLE,
            error_code="DEPENDENCY_UNAVAILABLE",
            safe_message=str(exc)[:120],
        )
    except ObjectNotFound:
        return _record(
            version, ScanState.REJECTED, scanner.name, "n/a", "stored object missing", now
        )
    except ObjectTooLarge:
        return _record(
            version,
            ScanState.REJECTED,
            scanner.name,
            "n/a",
            "stored object exceeds size limit",
            now,
        )

    if hashlib.sha256(data).hexdigest() != version.sha256:
        # The bytes behind the immutable identity changed: never trust any verdict on them.
        return _record(
            version,
            ScanState.REJECTED,
            scanner.name,
            "n/a",
            "object bytes do not match the recorded SHA-256",
            now,
        )
    result = scanner.scan([data], at=now)
    if result.verdict == "CLEAN":
        return _record(version, ScanState.CLEAN, result.engine, result.engine_version, "OK", now)
    if result.verdict == "REJECTED":
        return _record(
            version, ScanState.REJECTED, result.engine, result.engine_version, result.detail, now
        )
    return JobResult(
        AttemptOutcome.RETRYABLE, error_code="FILE_QUARANTINED", safe_message=result.detail[:120]
    )


def _record(
    version: DocumentVersion,
    state: str,
    engine: str,
    engine_version: str,
    detail: str,
    now: datetime,
) -> JobResult:
    def apply() -> None:
        current = DocumentVersion.objects.select_for_update().get(pk=version.pk)
        if current.scan_state != ScanState.QUARANTINED:
            return  # resolved meanwhile; a verdict is attached exactly once
        current.scan_state = state
        current.scan_engine = engine[:120]
        current.scan_engine_version = engine_version[:120]
        current.scanned_at = now
        current.scan_detail = detail[:200]
        current.version += 1
        current.save()
        audit.record_audit(
            entity_type="document_version",
            entity_id=current.pk,
            action=f"document.scan_{state.lower()}",
            actor_id=None,
            request_id=uuid4(),
            at=now,
            summary={"engine": engine[:120], "detail": detail[:200], "sha256": current.sha256},
        )

    return JobResult(AttemptOutcome.SUCCESS, apply=apply, response_digest=version.sha256)
