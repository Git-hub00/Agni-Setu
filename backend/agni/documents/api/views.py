"""Document endpoints API-033..037. Byte transfer (PUT content) and ticketed retrieval (GET
content) are not kernel commands; every state-changing step is."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.cases.application.drafts import DetachDraftDocument
from agni.identity.authz import load_snapshot
from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    DependencyUnavailable,
    FileTooLarge,
    FileTypeUnsupported,
    ResourceNotFound,
    UploadExpired,
    UploadIncomplete,
)

from ..adapters import get_object_store
from ..application.commands import (
    CompleteUpload,
    GrantDocumentAccess,
    ReserveUpload,
    document_body,
    verify_access_ticket,
)
from ..models import ReservationState, ScanState, UploadReservation
from ..ports import ObjectNotFound, ObjectStoreUnavailable, ObjectTooLarge
from ..selectors import visible_documents


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


_FALLBACK_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def content_disposition(disposition: str, original_name: str) -> str:
    """RFC 6266 / RFC 8187 header value for a user-supplied file name.

    The quoted `filename` is an inert ASCII fallback (letters, digits, dot, dash, underscore;
    no path segments, no markup, no control characters) and `filename*` carries the exact
    original name percent-encoded, so nothing a user typed reaches the header raw (security s.9).
    """
    fallback = _FALLBACK_UNSAFE.sub("_", original_name).strip("._-") or "document"
    fallback = re.sub(r"\.{2,}", ".", fallback)
    encoded = quote(original_name, safe="")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


class UploadListView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            ReserveUpload(),
            command_name="reserve-upload",
            target_type="reserve-upload:scope",
            target_id=principal.pk,
            etag_type="upload",
        )


class UploadContentView(ApiView):
    """PUT raw bytes for a reservation. Bounded by the reserved size; hashed server-side. Not a
    kernel command: a retried transfer simply replaces the staged bytes before completion."""

    permission_classes = [IsAuthenticated]
    parser_classes: list[Any] = []

    def put(self, request: Request, upload_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        reservation = UploadReservation.objects.filter(pk=upload_id, uploader=principal).first()
        if reservation is None:
            raise ResourceNotFound("Upload not found")
        if reservation.expires_at <= now or reservation.state in (
            ReservationState.EXPIRED,
            ReservationState.ABORTED,
        ):
            raise UploadExpired("The upload reservation has expired; request a new one")
        if reservation.state == ReservationState.COMPLETED:
            raise UploadIncomplete("This upload was already completed")
        declared = request.META.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
        if declared and declared != reservation.media_type:
            raise FileTypeUnsupported("Content-Type must match the reserved media type")
        length = request.META.get("CONTENT_LENGTH")
        try:
            content_length = int(length) if length else None
        except ValueError:
            content_length = None
        if content_length is not None and content_length > reservation.expected_size:
            raise FileTooLarge("Body exceeds the reserved size")

        store = get_object_store()
        try:
            stored = store.put_staging(
                reservation.object_key,
                _read_chunks(request, reservation.expected_size),
                max_bytes=reservation.expected_size,
            )
        except ObjectTooLarge:
            raise FileTooLarge("Body exceeds the reserved size") from None
        except ObjectStoreUnavailable as exc:
            raise DependencyUnavailable("Object storage is unavailable; retry the upload") from exc
        reservation.uploaded_size = stored.size
        reservation.uploaded_sha256 = stored.sha256
        reservation.state = ReservationState.UPLOADED
        reservation.save(update_fields=["uploaded_size", "uploaded_sha256", "state", "updated_at"])
        return ok(
            {
                "upload_id": str(reservation.pk),
                "state": reservation.state,
                "size_bytes": stored.size,
                "sha256": stored.sha256,
                "version": reservation.version,
            },
            request,
        )


def _read_chunks(request: Request, max_bytes: int) -> Iterator[bytes]:
    stream = request._request
    total = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ObjectTooLarge("body exceeds reservation")
        yield chunk


class UploadCompleteView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, upload_id: UUID) -> Response:
        return self.run_command(
            request,
            CompleteUpload(),
            command_name="complete-upload",
            target_type="upload_reservation",
            target_id=upload_id,
            etag_type="upload",
        )


class DocumentDetailView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, document_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        document = (
            visible_documents(load_snapshot(principal, now), now).filter(pk=document_id).first()
        )
        if document is None:
            raise ResourceNotFound("Document not found")
        response = ok(document_body(document), request)
        response["ETag"] = f'"document:{document.pk}:v{document.version}"'
        return response


class DocumentAccessView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: UUID) -> Response:
        return self.run_command(
            request,
            GrantDocumentAccess(),
            command_name="grant-document-access",
            target_type="document-access:scope",
            target_id=document_id,
        )


class DocumentDetachView(ApiView):
    """API-037: detach an unsubmitted draft reference (a new draft revision); never deletes."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        document = (
            visible_documents(load_snapshot(principal, now), now).filter(pk=document_id).first()
        )
        if document is None or document.application_id is None:
            raise ResourceNotFound("Document not found")
        body = request.data if isinstance(request.data, dict) else {}
        return self.run_command(
            request,
            DetachDraftDocument(),
            command_name="detach-draft-document",
            target_type="application",
            target_id=document.application_id,
            payload={**body, "document_version_id": str(document.pk)},
            etag_type="application",
        )


class DocumentContentView(ApiView):
    """Ticketed retrieval: signature + age + principal binding + recorded grant + CLEAN state."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, document_id: UUID) -> StreamingHttpResponse:
        principal = _principal(request)
        ticket = request.query_params.get("ticket", "")
        access = verify_access_ticket(ticket, document_id, UUID(str(principal.pk)))
        now = get_clock().now()
        if access is None or access.expires_at <= now:
            raise ResourceNotFound("Document access ticket is not valid")
        # A ticket proves a grant was recorded, not that the holder may still read the file:
        # re-authorise against the CURRENT scope so a revoked binding, an ended delegation or a
        # disabled principal cannot ride a ticket issued moments earlier (security s.5; the
        # export artifact route applies the same rule through `scope_still_covers`).
        document = (
            visible_documents(load_snapshot(principal, now), now).filter(pk=document_id).first()
        )
        if document is None or document.scan_state != ScanState.CLEAN:
            raise ResourceNotFound("Document is not available")
        store = get_object_store()
        digest = hashlib.sha256()

        def body() -> Iterator[bytes]:
            try:
                for chunk in store.read(
                    document.object_key, max_bytes=int(settings.AGNI_UPLOADS["MAX_FILE_BYTES"])
                ):
                    digest.update(chunk)
                    yield chunk
            except (ObjectNotFound, ObjectStoreUnavailable, ObjectTooLarge):
                return

        disposition = "inline" if access.purpose == "PREVIEW" else "attachment"
        response = StreamingHttpResponse(body(), content_type=document.media_type)
        response["Content-Length"] = str(document.size_bytes)
        response["Content-Disposition"] = content_disposition(disposition, document.original_name)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return response
