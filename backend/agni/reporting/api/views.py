"""Reporting endpoints: API-081 metrics, API-082..084 exports plus the ticketed CSV retrieval
(UI-22 / UI-05). A failed query is reported as unavailable, never as zero."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.core import signing
from django.db import DatabaseError, transaction
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.documents.adapters import get_object_store
from agni.documents.ports import ObjectNotFound, ObjectStoreUnavailable
from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.platform import audit
from agni.platform.api.throttles import FailClosedScopedRateThrottle
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.correlation import current_request_id
from agni.platform.errors import (
    AuthenticationRequired,
    DependencyUnavailable,
    ExportExpired,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
)

from ..application.exports import (
    ACCESS_SALT,
    MAX_ARTIFACT_BYTES,
    CreateExport,
    access_ttl,
    export_body,
    scope_still_covers,
)
from ..application.metrics import metrics_snapshot, parse_filters
from ..models import ExportJob, ExportState


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class MetricsView(ApiView):
    """API-081: single-cutoff reconciled metrics for the reader's scope."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        if snapshot.kind == PrincipalKind.STAFF and not (
            snapshot.has_role(RoleKey.SUPERVISOR)
            or snapshot.has_role(RoleKey.LEADERSHIP)
            or snapshot.has_role(RoleKey.ADMIN)
        ):
            raise Forbidden("Metrics are a supervisor, leadership or operations view")
        filters, as_of, violations = parse_filters(request.query_params, now=now)
        if violations:
            raise ValidationFailed(violations=violations)
        try:
            body = metrics_snapshot(snapshot, as_of=as_of, filters=filters)
        except DatabaseError as exc:  # report unavailable, never zero (FR-25 recovery)
            raise DependencyUnavailable("Reporting is temporarily unavailable") from exc
        response = ok(body, request)
        response["Cache-Control"] = "no-store"
        return response


def _visible_export(principal: Principal, export_id: UUID) -> ExportJob:
    export = ExportJob.objects.select_related("requester").filter(pk=export_id).first()
    if export is None:
        raise ResourceNotFound("Export not found")
    snapshot = load_snapshot(principal, get_clock().now())
    if export.requester_id != principal.pk and not snapshot.has_role(RoleKey.ADMIN):
        raise ResourceNotFound("Export not found")  # guessing an id learns nothing
    return export


class ExportListView(ApiView):
    """API-082 (POST) and the requester's export list for UI-22 tracking."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [FailClosedScopedRateThrottle]
    throttle_scope = "export-request"

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        queryset = (
            ExportJob.objects.all()
            if snapshot.has_role(RoleKey.ADMIN)
            else ExportJob.objects.filter(requester=principal)
        )
        rows = list(queryset.order_by("-created_at")[:50])
        items = []
        for job in rows:
            valid = (
                scope_still_covers(snapshot, job, now) if job.requester_id == principal.pk else None
            )
            items.append(export_body(job, scope_valid=valid))
        return ok({"items": items, "as_of": now.isoformat()}, request)

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            CreateExport(),
            command_name="create-export",
            target_type="create-export:scope",
            target_id=UUID(str(principal.pk)),
            etag_type="export",
        )


class ExportDetailView(ApiView):
    """API-083: owner (or operations administrator) status with the current-scope check."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, export_id: UUID) -> Response:
        principal = _principal(request)
        export = _visible_export(principal, export_id)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        valid = (
            scope_still_covers(snapshot, export, now)
            if export.requester_id == principal.pk
            else None
        )
        if export.state == ExportState.COMPLETE and export.expires_at <= now:
            ExportJob.objects.filter(pk=export.pk, state=ExportState.COMPLETE).update(
                state=ExportState.EXPIRED
            )
            export.state = ExportState.EXPIRED
        response = ok(export_body(export, scope_valid=valid), request)
        response["ETag"] = export.etag
        return response


class ExportAccessView(ApiView):
    """API-084: reauthorise requester, scope, expiry and purpose; audit; short-lived ticket."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, export_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        export = ExportJob.objects.filter(pk=export_id, requester=principal).first()
        if export is None:
            raise ResourceNotFound("Export not found")
        if export.state == ExportState.EXPIRED or export.expires_at <= now:
            ExportJob.objects.filter(pk=export.pk).exclude(state=ExportState.EXPIRED).update(
                state=ExportState.EXPIRED
            )
            raise ExportExpired("The export has expired; regenerate it under your current scope")
        if export.state != ExportState.COMPLETE or not export.artifact_object_key:
            raise InvalidTransition("The export is not complete")
        snapshot = load_snapshot(principal, now)
        if not scope_still_covers(snapshot, export, now):
            raise Forbidden("Your current scope no longer covers this export; regenerate it")
        data: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
        reason = str(data.get("reason") or "")[:500]
        ticket = signing.TimestampSigner(salt=ACCESS_SALT).sign(f"{export.pk}:{principal.pk}")
        with transaction.atomic():
            audit.record_audit(
                entity_type="export_job",
                entity_id=export.pk,
                action="export.access_granted",
                actor_id=UUID(str(principal.pk)),
                request_id=current_request_id() or UUID(int=0),
                at=now,
                summary={
                    "reason": reason,
                    "row_count": export.row_count,
                    "ttl_seconds": access_ttl(),
                },
            )
        return ok(
            {
                "url": f"/api/v1/exports/{export.pk}/artifact?ticket={quote(ticket)}",
                "expires_in_seconds": access_ttl(),
                "media_type": "text/csv",
                "sha256": export.artifact_sha256,
                "row_count": export.row_count,
            },
            request,
        )


class ExportArtifactView(ApiView):
    """Ticketed CSV retrieval bound to the requester; integrity-checked; never cached."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, export_id: UUID) -> HttpResponse:
        principal = _principal(request)
        ticket = request.query_params.get("ticket", "")
        try:
            value = signing.TimestampSigner(salt=ACCESS_SALT).unsign(ticket, max_age=access_ttl())
        except signing.BadSignature as exc:
            raise ResourceNotFound("Export access ticket is not valid") from exc
        if value != f"{export_id}:{principal.pk}":
            raise ResourceNotFound("Export access ticket is not valid")
        export = ExportJob.objects.filter(pk=export_id, requester=principal).first()
        if export is None or not export.artifact_object_key or not export.artifact_sha256:
            raise ResourceNotFound("Export not found")
        if export.expires_at <= get_clock().now():
            raise ExportExpired("The export has expired")
        store = get_object_store()
        try:
            data = b"".join(store.read(export.artifact_object_key, max_bytes=MAX_ARTIFACT_BYTES))
        except ObjectStoreUnavailable as exc:
            raise DependencyUnavailable("Export storage is temporarily unavailable") from exc
        except ObjectNotFound as exc:
            raise ResourceNotFound("Export artifact is missing") from exc
        if hashlib.sha256(data).hexdigest() != export.artifact_sha256:
            raise DependencyUnavailable("Export integrity check failed")
        response = HttpResponse(data, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="agni-export-{export.kind.lower()}-{str(export.pk)[:8]}.csv"'
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
