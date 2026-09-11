"""Integration endpoints (API-107..111; UI-25). The partner intake authenticates with the
partner scheme only (no session, no CSRF, no browser exemptions); everything else is an
operations-administrator view or a scoped conflict desk."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, ResourceNotFound

from ..application.commands import ResolveConflict, TestIntegration, conflict_scope
from ..application.inbox import receive_event
from ..application.projections import (
    conflict_body,
    entity_state_body,
    inbox_body,
    integration_body,
)
from ..models import ConflictState, Integration, IntegrationConflict


def _operator(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    require_role(load_snapshot(user, get_clock().now()), RoleKey.ADMIN)
    return user


def _integration_by_ref(reference: str) -> Integration:
    try:
        integration = Integration.objects.filter(pk=UUID(reference)).first()
    except ValueError:
        integration = Integration.objects.filter(key=reference).first()
    if integration is None:
        raise ResourceNotFound("Integration not found")
    return integration


class IntegrationListView(ApiView):
    """API-107: mode, health, ownership and sanitised configuration; never a secret value."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _operator(request)
        now = get_clock().now()
        rows = Integration.objects.select_related("owner_queue").order_by("key")
        return ok(
            {"items": [integration_body(i, now=now) for i in rows], "as_of": now.isoformat()},
            request,
        )


class IntegrationDetailView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, integration_ref: str) -> Response:
        _operator(request)
        now = get_clock().now()
        integration = _integration_by_ref(integration_ref)
        response = ok(
            {
                **integration_body(integration, now=now),
                "recent_inbox": [
                    inbox_body(r) for r in integration.inbox.order_by("-received_at")[:25]
                ],
                "entity_states": [
                    entity_state_body(s)
                    for s in integration.entity_states.order_by("source_entity_id")[:50]
                ],
            },
            request,
        )
        response["ETag"] = integration.etag
        return response


class IntegrationTestView(ApiView):
    """API-108."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, integration_ref: str) -> Response:
        integration = _integration_by_ref(integration_ref)
        return self.run_command(
            request,
            TestIntegration(),
            command_name="integration-test",
            target_type="integration",
            target_id=UUID(str(integration.pk)),
            etag_type="integration",
        )


class PartnerEventView(APIView):
    """API-109: partner inbox. Authenticated by the partner scheme on the raw body; the
    project session/CSRF machinery does not apply here and grants nothing."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    def post(self, request: Request, integration_ref: str) -> Response:
        integration = _integration_by_ref(integration_ref)
        status, body = receive_event(
            integration, bytes(request.body), request.headers, now=get_clock().now()
        )
        response = ok(body, request, status=status)
        response["Cache-Control"] = "no-store"
        return response


class ConflictListView(ApiView):
    """API-110: owned schema, order and source conflicts."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = request.user
        if not isinstance(user, Principal):
            raise AuthenticationRequired()
        now = get_clock().now()
        scope = conflict_scope(load_snapshot(user, now))
        rows = IntegrationConflict.objects.select_related(
            "integration", "inbox", "owner_queue"
        ).order_by("-created_at")
        if scope is not None:
            rows = rows.filter(owner_queue__jurisdiction_id__in=scope)
        state = request.query_params.get("state")
        if state in ConflictState.values:
            rows = rows.filter(state=state)
        integration_ref = request.query_params.get("integration")
        if integration_ref:
            rows = rows.filter(integration__key=integration_ref)
        return ok(
            {
                "items": [conflict_body(c) for c in rows[:100]],
                "as_of": now.isoformat(),
                "scope": "GLOBAL" if scope is None else "JURISDICTIONS",
            },
            request,
        )


class ConflictDetailView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, conflict_id: UUID) -> Response:
        user = request.user
        if not isinstance(user, Principal):
            raise AuthenticationRequired()
        scope = conflict_scope(load_snapshot(user, get_clock().now()))
        conflict = (
            IntegrationConflict.objects.select_related("integration", "inbox", "owner_queue")
            .filter(pk=conflict_id)
            .first()
        )
        if conflict is None or (
            scope is not None
            and (conflict.owner_queue is None or conflict.owner_queue.jurisdiction_id not in scope)
        ):
            raise ResourceNotFound("Conflict not found")
        body: dict[str, Any] = conflict_body(conflict)
        response = ok(body, request)
        response["ETag"] = conflict.etag
        return response


class ConflictResolveView(ApiView):
    """API-111."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, conflict_id: UUID) -> Response:
        return self.run_command(
            request,
            ResolveConflict(),
            command_name="integration-conflict-resolve",
            target_type="integration_conflict",
            target_id=conflict_id,
            etag_type="integration_conflict",
        )
