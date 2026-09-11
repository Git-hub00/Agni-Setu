"""Document commands on the kernel (FR-05; API-033/034/036; integrations s.3).

ReserveUpload   - scope-checks the target draft, validates name/type/size/quota, reserves a
                  random private staging key with a bounded lifetime.
CompleteUpload  - verifies the server-computed size/SHA-256 (and the client's claim) against
                  trusted storage metadata, sniffs the media type, promotes the bytes to the
                  content-addressed final key, creates a QUARANTINED version and enqueues the
                  durable scan job in the same transaction.
GrantDocumentAccess - reauthorises, refuses non-CLEAN files and records an append-only access
                  grant; the ticket is short-lived, principal-bound and served through the API.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Sum

from agni.cases.application.access import editable_draft_for_actor
from agni.cases.domain.drafts import requirement_codes_for
from agni.cases.models import Application
from agni.identity.models import PrincipalKind
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    FileQuarantined,
    FileRejected,
    FileTooLarge,
    FileTypeUnsupported,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    UploadExpired,
    UploadIncomplete,
    ValidationFailed,
    Violation,
)
from agni.platform.jobs import enqueue_job

from ..adapters import get_object_store
from ..models import (
    AccessMechanism,
    AccessPurpose,
    DocumentAccess,
    DocumentVersion,
    ReservationState,
    ScanState,
    UploadReservation,
    UploadTargetType,
)
from ..ports import ObjectNotFound, ObjectStoreUnavailable, ObjectTooLarge
from ..scanning import JOB_KIND

HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAGIC: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


def reservation_body(r: UploadReservation) -> dict[str, Any]:
    return {
        "upload_id": str(r.pk),
        "state": r.state,
        "target_type": r.target_type,
        "target_id": str(r.target_id),
        "requirement_code": r.requirement_code,
        "original_name": r.original_name,
        "media_type": r.media_type,
        "expected_size": r.expected_size,
        "expires_at": r.expires_at.isoformat(),
        "upload_url": f"/api/v1/uploads/{r.pk}/content",
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": r.media_type},
        "max_bytes": r.expected_size,
        "document_version_id": str(r.document_version_id) if r.document_version_id else None,
        "version": r.version,
    }


def document_body(d: DocumentVersion) -> dict[str, Any]:
    return {
        "document_version_id": str(d.pk),
        "application_id": str(d.application_id) if d.application_id else None,
        "requirement_code": d.requirement_code,
        "original_name": d.original_name,
        "media_type": d.media_type,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256,
        "scan_state": d.scan_state,
        "scan_detail": d.scan_detail if d.scan_state == ScanState.REJECTED else "",
        "scanned_at": d.scanned_at.isoformat() if d.scanned_at else None,
        "uploaded_at": d.created_at.isoformat(),
        "supersedes_id": str(d.supersedes_id) if d.supersedes_id else None,
        "version": d.version,
    }


class ReserveUpload(CommandHandler[UploadReservation]):
    """API-033. Target type is allowlisted: APPLICATION_DRAFT for the applicant (or a delegate
    with draft.edit) and INSPECTION_EVIDENCE for the currently assigned officer of an open
    attempt. Every other target type is refused until its phase lands."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only applicant and staff accounts upload files")

    def lock_target(self, uow: UnitOfWork) -> UploadReservation | None:
        return None

    def apply(
        self, uow: UnitOfWork, target: UploadReservation | None
    ) -> CommandOutcome[UploadReservation]:
        data = dict(uow.envelope.payload)
        limits = settings.AGNI_UPLOADS
        allowed_keys = {
            "target_type",
            "target_id",
            "original_name",
            "media_type",
            "size_bytes",
            "sha256",
            "requirement_code",
            "replaces_document_version_id",
        }
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed_keys)
        ]
        target_type = str(data.get("target_type", ""))
        permitted_types = (
            {
                UploadTargetType.APPLICATION_DRAFT.value,
                UploadTargetType.NOTICE_RESPONSE.value,
                UploadTargetType.SUPPORT_ATTACHMENT.value,
            }
            if uow.actor.kind == PrincipalKind.APPLICANT
            else {
                UploadTargetType.INSPECTION_EVIDENCE.value,
                UploadTargetType.SUPPORT_ATTACHMENT.value,
            }
        )
        if target_type not in permitted_types:
            violations.append(
                Violation(
                    "/target_type",
                    "unsupported",
                    f"permitted for this account: {', '.join(sorted(permitted_types))}",
                )
            )
        target_id = _uuid(data.get("target_id"), "/target_id", violations)
        name = data.get("original_name")
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 180):
            violations.append(Violation("/original_name", "length", "1 to 180 characters"))
        media_type = str(data.get("media_type", "")).lower()
        if media_type not in limits["ALLOWED_MEDIA_TYPES"]:
            violations.append(
                Violation("/media_type", "unsupported", "permitted types: PDF, JPEG, PNG")
            )
        size = data.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            violations.append(Violation("/size_bytes", "invalid", "must be a positive integer"))
            size = 0
        sha = data.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not HEX64.match(sha)):
            violations.append(Violation("/sha256", "format", "64 lowercase hex characters"))
        code = data.get("requirement_code")
        if not isinstance(code, str) or not re.match(r"^[a-z][a-z0-9_-]{1,59}$", code):
            violations.append(Violation("/requirement_code", "format", "requirement code"))
        if (
            violations
            or target_id is None
            or not isinstance(name, str)
            or not isinstance(code, str)
        ):
            raise ValidationFailed(violations=violations)
        if size > int(limits["MAX_FILE_BYTES"]):
            raise FileTooLarge(
                f"Files are limited to {int(limits['MAX_FILE_BYTES']) // (1024 * 1024)} MiB",
                extensions={"max_bytes": int(limits["MAX_FILE_BYTES"])},
            )

        application: Application | None
        if target_type == UploadTargetType.INSPECTION_EVIDENCE:
            application = _evidence_target(uow, target_id, code)
        elif target_type == UploadTargetType.NOTICE_RESPONSE:
            application = _response_target(uow, target_id, code)
        elif target_type == UploadTargetType.SUPPORT_ATTACHMENT:
            ticket = _ticket_target(uow, target_id, code)
            application = ticket.application
            _check_ticket_quota(target_id, size, uow)
        else:
            draft = editable_draft_for_actor(uow.actor, target_id, uow.now)
            if draft is None:
                raise ResourceNotFound("Application not found")
            application = draft
            if application.status != "DRAFT":
                raise InvalidTransition("Files can only be added to a draft application")
            codes = requirement_codes_for(application, uow.now)
            if code not in codes:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/requirement_code",
                            "unknown_requirement",
                            "not a requirement of this application's current policy",
                        )
                    ]
                )
        if application is not None and target_type != UploadTargetType.SUPPORT_ATTACHMENT:
            _check_quota(application, size, uow)

        reservation = UploadReservation.objects.create(
            uploader=uow.actor,
            target_type=target_type,
            target_id=target_id,
            requirement_code=code,
            original_name=name.strip(),
            media_type=media_type,
            expected_size=size,
            expected_sha256=sha,
            object_key=(
                f"staging/{application.pk if application is not None else target_id}/"
                f"{secrets.token_urlsafe(24)}"
            ),
            expires_at=uow.now + timedelta(seconds=int(limits["RESERVATION_TTL_SECONDS"])),
        )
        return CommandOutcome(
            status=201,
            body=reservation_body(reservation),
            aggregate=reservation,
            created=True,
            audits=[
                AuditEntry(
                    "upload_reservation",
                    reservation.pk,
                    "upload.reserved",
                    {
                        "application_id": str(application.pk) if application is not None else None,
                        "target_type": target_type,
                        "requirement_code": code,
                        "media_type": media_type,
                        "size_bytes": size,
                    },
                )
            ],
        )


EVIDENCE_CODE = re.compile(r"^inspection-(c\d{2})$")


def _evidence_target(uow: UnitOfWork, inspection_id: UUID, code: str) -> Application:
    """INSPECTION_EVIDENCE: the currently assigned officer of an open attempt uploads evidence
    for one item of the pinned checklist (`inspection-c01`). The file belongs to the case."""
    from agni.inspections.models import AssignmentState, Inspection, InspectionStatus

    inspection = (
        Inspection.objects.select_related("application", "current_assignment", "checklist_artifact")
        .filter(pk=inspection_id)
        .first()
    )
    current = inspection.current_assignment if inspection else None
    if (
        inspection is None
        or current is None
        or current.state != AssignmentState.ACTIVE
        or current.officer_id != uow.actor.pk
    ):
        raise ResourceNotFound("Inspection not found")
    if inspection.status not in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS):
        raise InvalidTransition("Evidence can only be added to an open attempt")
    match = EVIDENCE_CODE.match(code)
    items = {
        str(i.get("code", "")).lower()
        for i in inspection.checklist_artifact.payload.get("items", [])
    }
    if match is None or match.group(1) not in items:
        raise ValidationFailed(
            violations=[
                Violation(
                    "/requirement_code",
                    "unknown_requirement",
                    "use inspection-<item code> for an item of the pinned checklist",
                )
            ]
        )
    return inspection.application


RESPONSE_CODE = re.compile(r"^response-([a-z0-9][a-z0-9_-]{1,39})$")


def _response_target(uow: UnitOfWork, notice_id: UUID, code: str) -> Application:
    """NOTICE_RESPONSE: the applicant side of a PUBLISHED notice uploads evidence for one of its
    items (`response-<item code>`). The file belongs to the case."""
    from agni.cases.application.access import can_respond_to_notices
    from agni.notices.models import Notice, NoticeState

    notice = Notice.objects.select_related("application").filter(pk=notice_id).first()
    if notice is None or not can_respond_to_notices(uow.actor, notice.application, uow.now):
        raise ResourceNotFound("Notice not found")
    if notice.state != NoticeState.PUBLISHED:
        raise InvalidTransition("Evidence can only be added to an open notice")
    match = RESPONSE_CODE.match(code)
    codes = {c.lower() for c in notice.items.values_list("code", flat=True)}
    if match is None or match.group(1) not in codes:
        raise ValidationFailed(
            violations=[
                Violation(
                    "/requirement_code",
                    "unknown_requirement",
                    "use response-<item code> for an item of this notice",
                )
            ]
        )
    return notice.application


SUPPORT_CODE = re.compile(r"^support-[a-z0-9][a-z0-9_-]{0,49}$")


def _ticket_target(uow: UnitOfWork, ticket_id: UUID, code: str) -> Any:
    """SUPPORT_ATTACHMENT: the requester or a support agent of an open ticket attaches a file
    (`support-<label>`). The file belongs to the ticket's case when there is one; attachment
    readership follows the ticket (FR-30), never general admin status."""
    from agni.identity.authz import load_snapshot
    from agni.support.application.commands import support_scope, visible_tickets
    from agni.support.models import TicketState

    snapshot = load_snapshot(uow.actor, uow.now)
    ticket = visible_tickets(snapshot).filter(pk=ticket_id).first()
    if ticket is None or not (
        ticket.requester_id == uow.actor.pk or support_scope(snapshot, ticket.owner_queue)
    ):
        raise ResourceNotFound("Ticket not found")
    if ticket.state == TicketState.CLOSED:
        raise InvalidTransition("Files cannot be added to a closed ticket")
    if SUPPORT_CODE.match(code) is None:
        raise ValidationFailed(
            violations=[
                Violation(
                    "/requirement_code", "unknown_requirement", "use support-<label> for a ticket"
                )
            ]
        )
    return ticket


def _check_ticket_quota(ticket_id: UUID, size: int, uow: UnitOfWork) -> None:
    limits = settings.AGNI_UPLOADS
    versions = DocumentVersion.objects.filter(
        reservation__target_type=UploadTargetType.SUPPORT_ATTACHMENT,
        reservation__target_id=ticket_id,
    ).exclude(scan_state=ScanState.REJECTED)
    pending = UploadReservation.objects.filter(
        target_type=UploadTargetType.SUPPORT_ATTACHMENT,
        target_id=ticket_id,
        state__in=[ReservationState.RESERVED, ReservationState.UPLOADED],
        expires_at__gt=uow.now,
    )
    files = versions.count() + pending.count()
    used = (versions.aggregate(total=Sum("size_bytes"))["total"] or 0) + (
        pending.aggregate(total=Sum("expected_size"))["total"] or 0
    )
    if files + 1 > int(limits["MAX_PACKAGE_FILES"]) or used + size > int(
        limits["MAX_PACKAGE_BYTES"]
    ):
        raise FileTooLarge(
            "The ticket attachment limit would be exceeded",
            extensions={
                "max_files": int(limits["MAX_PACKAGE_FILES"]),
                "max_package_bytes": int(limits["MAX_PACKAGE_BYTES"]),
            },
        )


def _application_for(target: UploadReservation) -> Application | None:
    if target.target_type == UploadTargetType.INSPECTION_EVIDENCE:
        from agni.inspections.models import Inspection

        return Inspection.objects.select_related("application").get(pk=target.target_id).application
    if target.target_type == UploadTargetType.NOTICE_RESPONSE:
        from agni.notices.models import Notice

        return Notice.objects.select_related("application").get(pk=target.target_id).application
    if target.target_type == UploadTargetType.SUPPORT_ATTACHMENT:
        from agni.support.models import SupportTicket

        return (
            SupportTicket.objects.select_related("application").get(pk=target.target_id).application
        )
    return Application.objects.get(pk=target.target_id)


def _check_quota(application: Application, size: int, uow: UnitOfWork) -> None:
    limits = settings.AGNI_UPLOADS
    versions = DocumentVersion.objects.filter(application=application).exclude(
        scan_state=ScanState.REJECTED
    )
    from agni.inspections.models import Inspection
    from agni.notices.models import Notice

    targets = [
        application.pk,
        *Inspection.objects.filter(application=application).values_list("pk", flat=True),
        *Notice.objects.filter(application=application).values_list("pk", flat=True),
    ]
    pending = UploadReservation.objects.filter(
        target_id__in=targets,
        state__in=[ReservationState.RESERVED, ReservationState.UPLOADED],
        expires_at__gt=uow.now,
    )
    files = versions.count() + pending.count()
    used = (versions.aggregate(total=Sum("size_bytes"))["total"] or 0) + (
        pending.aggregate(total=Sum("expected_size"))["total"] or 0
    )
    if files + 1 > int(limits["MAX_PACKAGE_FILES"]) or used + size > int(
        limits["MAX_PACKAGE_BYTES"]
    ):
        raise FileTooLarge(
            "The application package limit would be exceeded",
            extensions={
                "max_files": int(limits["MAX_PACKAGE_FILES"]),
                "max_package_bytes": int(limits["MAX_PACKAGE_BYTES"]),
            },
        )


class CompleteUpload(CommandHandler[UploadReservation]):
    """API-034. Body values are claims; the server's own computation and storage metadata are
    the truth. Target: the reservation (If-Match on its version)."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only applicant and staff accounts upload files")

    def lock_target(self, uow: UnitOfWork) -> UploadReservation | None:
        reservation = (
            UploadReservation.objects.select_for_update()
            .filter(pk=uow.envelope.target_id, uploader=uow.actor)
            .first()
        )
        if reservation is None:
            raise ResourceNotFound("Upload not found")
        return reservation

    def apply(
        self, uow: UnitOfWork, target: UploadReservation | None
    ) -> CommandOutcome[UploadReservation]:
        if target is None:  # lock_target always returns or raises; defensive for the Protocol
            raise ResourceNotFound("Upload not found")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"sha256", "size_bytes", "object_version_id"})
        ]
        claimed_sha = data.get("sha256")
        if not isinstance(claimed_sha, str) or not HEX64.match(claimed_sha):
            violations.append(Violation("/sha256", "format", "64 lowercase hex characters"))
        claimed_size = data.get("size_bytes")
        if not isinstance(claimed_size, int) or isinstance(claimed_size, bool) or claimed_size <= 0:
            violations.append(Violation("/size_bytes", "invalid", "must be a positive integer"))
        if violations:
            raise ValidationFailed(violations=violations)

        if target.state == ReservationState.COMPLETED and target.document_version_id:
            existing = DocumentVersion.objects.get(pk=target.document_version_id)
            return CommandOutcome(status=202, body=document_body(existing), aggregate=target)
        if target.expires_at <= uow.now:
            target.state = ReservationState.EXPIRED
            target.save(update_fields=["state", "updated_at"])
            raise UploadExpired("The upload reservation has expired; request a new one")
        if target.state != ReservationState.UPLOADED or not target.uploaded_sha256:
            raise UploadIncomplete("No bytes have been received for this upload")

        store = get_object_store()
        staged = store.head(target.object_key)
        if staged is None:
            raise UploadIncomplete("Uploaded bytes are not in storage; upload again")
        if (
            staged.size != target.uploaded_size
            or staged.size != claimed_size
            or target.uploaded_sha256 != claimed_sha
            or (target.expected_sha256 and target.expected_sha256 != target.uploaded_sha256)
            or staged.size != target.expected_size
        ):
            raise UploadIncomplete(
                "Uploaded size or checksum does not match the reservation",
                extensions={
                    "stored_size": staged.size,
                    "stored_sha256": target.uploaded_sha256,
                    "expected_size": target.expected_size,
                },
            )
        head = _first_bytes(store, target.object_key)
        if not any(head.startswith(magic) for magic in MAGIC.get(target.media_type, ())):
            raise FileTypeUnsupported("File content does not match the declared type")

        final_key = f"objects/{target.uploaded_sha256}"
        try:
            promoted = store.promote(target.object_key, final_key, expected_size=staged.size)
        except ObjectNotFound:
            raise UploadIncomplete("Uploaded bytes disappeared before completion") from None
        except ObjectTooLarge:
            raise UploadIncomplete(
                "An object with this checksum exists with another size"
            ) from None
        except ObjectStoreUnavailable as exc:
            from agni.platform.errors import DependencyUnavailable

            raise DependencyUnavailable(
                "Object storage is unavailable; retry the completion"
            ) from exc

        application = _application_for(target)
        supersedes = None
        replaces = (
            uow.envelope.payload.get("replaces_document_version_id") if False else None
        )  # reserved
        version = DocumentVersion.objects.create(
            application=application,
            uploaded_by=uow.actor,
            requirement_code=target.requirement_code,
            original_name=target.original_name,
            media_type=target.media_type,
            size_bytes=staged.size,
            sha256=target.uploaded_sha256,
            object_key=final_key,
            object_version_id=promoted.version_id,
            scan_state=ScanState.QUARANTINED,
            supersedes=supersedes or replaces,
            reservation=target,
        )
        target.state = ReservationState.COMPLETED
        target.object_version_id = promoted.version_id
        target.document_version = version
        target.save(update_fields=["state", "object_version_id", "document_version", "updated_at"])
        # Durable scan intent in the same transaction; the worker owns the verdict.
        enqueue_job(
            kind=JOB_KIND,
            aggregate_ref={"document_version_id": str(version.pk), "sha256": version.sha256},
            run_at=uow.now,
            logical_action_id=version.pk,
        )
        staging_key = target.object_key
        transaction.on_commit(lambda: store.delete(staging_key))
        return CommandOutcome(
            status=202,
            body=document_body(version),
            aggregate=target,
            audits=[
                AuditEntry(
                    "document_version",
                    version.pk,
                    "document.version_created",
                    {
                        "application_id": str(application.pk) if application is not None else None,
                        "target_type": target.target_type,
                        "requirement_code": version.requirement_code,
                        "sha256": version.sha256,
                        "size_bytes": version.size_bytes,
                        "media_type": version.media_type,
                        "scan_state": version.scan_state,
                    },
                )
            ],
        )


def _first_bytes(store: Any, key: str) -> bytes:
    for chunk in store.read(key, max_bytes=int(settings.AGNI_UPLOADS["MAX_FILE_BYTES"])):
        return bytes(chunk[:16])
    return b""


class GrantDocumentAccess(CommandHandler[DocumentVersion]):
    """API-036. Reauthorise the reader, refuse non-CLEAN files, audit, and issue a proxy ticket.
    The document row is not versioned by this (append-only access record), so no If-Match."""

    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> DocumentVersion | None:
        return None

    def apply(
        self, uow: UnitOfWork, target: DocumentVersion | None
    ) -> CommandOutcome[DocumentVersion]:
        from agni.identity.authz import load_snapshot

        from ..selectors import visible_documents

        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"purpose", "reason"})
        ]
        purpose = str(data.get("purpose", ""))
        if purpose not in AccessPurpose.values:
            violations.append(Violation("/purpose", "invalid", "PREVIEW, DOWNLOAD or PRINT"))
        reason = data.get("reason")
        if reason is not None and (not isinstance(reason, str) or not (10 <= len(reason) <= 500)):
            violations.append(Violation("/reason", "length", "10 to 500 characters when given"))
        if violations:
            raise ValidationFailed(violations=violations)

        snapshot = load_snapshot(uow.actor, uow.now)
        document = visible_documents(snapshot, uow.now).filter(pk=uow.envelope.target_id).first()
        if document is None:
            raise ResourceNotFound("Document not found")
        if document.scan_state == ScanState.QUARANTINED:
            raise FileQuarantined("The file is still waiting for its security scan")
        if document.scan_state == ScanState.REJECTED:
            raise FileRejected("The file was rejected by the security scan and cannot be opened")

        ttl = int(settings.AGNI_UPLOADS["ACCESS_TTL_SECONDS"])
        access = DocumentAccess.objects.create(
            document_version=document,
            principal=uow.actor,
            purpose=purpose,
            mechanism=AccessMechanism.PROXY,
            expires_at=uow.now + timedelta(seconds=ttl),
            request_id=uow.request_id,
        )
        ticket = signing.TimestampSigner(salt="agni.document-access").sign(
            f"{document.pk}:{uow.actor.pk}:{access.pk}"
        )
        return CommandOutcome(
            status=200,
            body={
                "document_version_id": str(document.pk),
                "access_id": str(access.pk),
                "mechanism": AccessMechanism.PROXY,
                "url": f"/api/v1/documents/{document.pk}/content?ticket={ticket}",
                "expires_at": access.expires_at.isoformat(),
                "purpose": purpose,
            },
            aggregate=None,
            audits=[
                AuditEntry(
                    "document_version",
                    document.pk,
                    "document.access_granted",
                    {"purpose": purpose, "access_id": str(access.pk), "mechanism": "PROXY"},
                )
            ],
        )


def verify_access_ticket(
    ticket: str, document_id: UUID, principal_id: UUID
) -> DocumentAccess | None:
    """Validate signature, age, binding and the recorded grant; None means refuse."""
    ttl = int(settings.AGNI_UPLOADS["ACCESS_TTL_SECONDS"])
    try:
        value = signing.TimestampSigner(salt="agni.document-access").unsign(ticket, max_age=ttl)
    except signing.BadSignature:
        return None
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != str(document_id) or parts[1] != str(principal_id):
        return None
    try:
        access_id = UUID(parts[2])
    except ValueError:
        return None
    return DocumentAccess.objects.filter(
        pk=access_id, document_version_id=document_id, principal_id=principal_id
    ).first()


def _uuid(value: Any, pointer: str, violations: list[Violation]) -> UUID | None:
    if value is None or value == "":
        violations.append(Violation(pointer, "required", "is required"))
        return None
    try:
        return UUID(str(value))
    except ValueError:
        violations.append(Violation(pointer, "invalid", "must be a UUID"))
        return None
