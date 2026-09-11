"""Decision endpoints (API-064 readiness, API-065 record, API-066 list; UI-14)."""

from __future__ import annotations

from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.cases.api.case_views import _principal, _scoped
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import Forbidden, ResourceNotFound

from ..application.commands import RecordDecision, decision_body, readiness_body
from ..models import Decision


class DecisionReadinessView(ApiView):
    """API-064: the server-calculated guard list for the current supervisor. The read result
    never authorises the later command by itself."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot, queryset = _scoped(principal, now)
        application = queryset.filter(pk=application_id).first()
        if application is None:
            raise ResourceNotFound("Application not found")
        if snapshot.kind != PrincipalKind.STAFF or not snapshot.has_role(
            RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
        ):
            raise Forbidden("Decision readiness is a supervisor view")
        response = ok(readiness_body(application, snapshot, now), request)
        response["ETag"] = application.etag
        response["Cache-Control"] = "no-store"
        return response


class DecisionsView(ApiView):
    """API-066 (GET: published decision plus authorised internal context) and API-065 (POST)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot, queryset = _scoped(principal, now)
        application = queryset.filter(pk=application_id).first()
        if application is None:
            raise ResourceNotFound("Application not found")
        staff = snapshot.kind != PrincipalKind.APPLICANT
        items = [
            decision_body(d, staff=staff)
            for d in Decision.objects.filter(application=application).order_by("decision_number")
        ]
        return ok({"items": items, "as_of": now.isoformat()}, request)

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            RecordDecision(),
            command_name="record-decision",
            target_type="application",
            target_id=application_id,
        )
