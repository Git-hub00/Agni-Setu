"""Offline package, synchronisation and conflict endpoints (API-048..052; UI-12/UI-13)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.inspections.application.commands import inspection_body
from agni.inspections.models import (
    FAILED_VISIT_REASONS,
    AssignmentState,
    Inspection,
    InspectionStatus,
)
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
)

from ..application.conflicts import ProposeConflict, ResolveConflict, conflict_body
from ..application.sync import SUPPORTED_SCHEMA_VERSIONS, operation_receipt, process_operation
from ..models import ReportConflict

PACKAGE_TTL = timedelta(hours=24)  # docs/09 s.2 demo default


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class OfflinePackageView(ApiView):
    """API-048: minimal authorised assignment snapshot with expiry and versions for the current
    ACTIVE assignee of an open attempt. Reads only; the package is not proof of anything."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, inspection_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        if principal.kind != PrincipalKind.STAFF:
            raise Forbidden("Offline packages are for field officers")
        inspection = (
            Inspection.objects.select_related(
                "application__premises",
                "application__owner_queue",
                "checklist_artifact",
                "current_assignment__officer",
            )
            .filter(pk=inspection_id)
            .first()
        )
        current = inspection.current_assignment if inspection else None
        if (
            inspection is None
            or current is None
            or current.state != AssignmentState.ACTIVE
            or current.officer_id != principal.pk
        ):
            raise ResourceNotFound("Inspection not found")
        if inspection.status not in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS):
            raise InvalidTransition("Only an open attempt can be packaged for offline work")
        snapshot = load_snapshot(principal, now)
        if not snapshot.active or not snapshot.has_role(RoleKey.OFFICER):
            raise Forbidden("Current authority is required to download a package")
        application = inspection.application
        body: dict[str, Any] = {
            "package_id": f"{inspection.pk}:{inspection.version}:{current.version}",
            "issued_at": now.isoformat(),
            "expires_at": (now + PACKAGE_TTL).isoformat(),
            "schema_version": "1.0",
            "supported_schema_versions": sorted(SUPPORTED_SCHEMA_VERSIONS),
            "principal_id": str(principal.pk),
            "authz_epoch": snapshot.authz_epoch,
            "inspection": inspection_body(inspection),
            "checklist_items": inspection.checklist_artifact.payload.get("items", []),
            "versions": {
                "application_version": application.version,
                "inspection_version": inspection.version,
                "assignment_version": current.version,
                "checklist_version": inspection.checklist_artifact.reference,
            },
            "case": {
                "application_id": str(application.pk),
                "public_reference": application.public_reference,
                "status": application.status,
                "premises_display_name": application.premises.display_name,
                "locality": application.premises.locality,
                "category_key": application.premises.category_key,
                "owner_queue": application.owner_queue.queue_key,
            },
            "failed_visit_reasons": list(FAILED_VISIT_REASONS),
            "operations": ["SUBMIT_INSPECTION_REPORT", "RECORD_FAILED_VISIT"],
            "limits": {
                "max_file_bytes": int(settings.AGNI_UPLOADS["MAX_FILE_BYTES"]),
                "allowed_media_types": list(settings.AGNI_UPLOADS["ALLOWED_MEDIA_TYPES"]),
            },
            "notice": (
                "Package contents are a snapshot; the server re-checks authority, versions "
                "and evidence at synchronisation."
            ),
        }
        response = ok(body, request)
        response["ETag"] = inspection.etag
        response["Cache-Control"] = "no-store"
        return response


class SyncOperationsView(ApiView):
    """API-049."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        if principal.kind != PrincipalKind.STAFF:
            raise Forbidden("Synchronisation is for field officers")
        data = request.data if isinstance(request.data, dict) else {}
        status, body, resulting_version = process_operation(
            principal=principal,
            actor=self.actor_context(request),
            data=dict(data),
            header_version=self.expected_version(request),
            clock=get_clock(),
        )
        headers: dict[str, str] = {}
        inspection_id = data.get("inspection_id")
        if resulting_version is not None and inspection_id:
            headers["ETag"] = f'"inspection:{inspection_id}:v{resulting_version}"'
        return ok(body, request, status=status, headers=headers)


class SyncOperationDetailView(ApiView):
    """API-050: owner-scoped canonical outcome or absence."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, operation_id: UUID) -> Response:
        principal = _principal(request)
        receipt = operation_receipt(principal=principal, operation_id=operation_id)
        if receipt is None:
            raise ResourceNotFound("No accepted or recorded operation with this id for you")
        return ok(receipt, request)


class ConflictProposalView(ApiView):
    """API-051."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, inspection_id: UUID) -> Response:
        return self.run_command(
            request,
            ProposeConflict(),
            command_name="propose-inspection-conflict",
            target_type="inspection",
            target_id=inspection_id,
        )


class ConflictListView(ApiView):
    """Conflicts visible to the supervisor of the case jurisdiction (UI-14 / UI-13 review)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        if snapshot.kind != PrincipalKind.STAFF:
            raise Forbidden("Conflicts are a staff view")
        jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
        queryset = ReportConflict.objects.filter(
            inspection__application__owner_queue__jurisdiction_id__in=jurisdictions
        )
        if snapshot.has_role(RoleKey.OFFICER):
            queryset = queryset | ReportConflict.objects.filter(proposer=principal)
        state = request.query_params.get("state")
        if state in ("OPEN", "RESOLVED"):
            queryset = queryset.filter(state=state)
        rows = queryset.distinct().order_by("-created_at")[:100]
        return ok(
            {
                "items": [{**conflict_body(c), "etag": c.etag} for c in rows],
                "as_of": now.isoformat(),
            },
            request,
        )


class ConflictResolveView(ApiView):
    """API-052."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, conflict_id: UUID) -> Response:
        return self.run_command(
            request,
            ResolveConflict(),
            command_name="resolve-inspection-conflict",
            target_type="conflict",
            target_id=conflict_id,
            etag_type="conflict",
        )
