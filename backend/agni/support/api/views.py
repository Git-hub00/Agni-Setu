"""Support endpoints (API-112..118; UI-26). Appeals are profile-gated and answer with the
approved referral instead of a filing form (integrations s.11)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.models import Principal, PrincipalKind
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, ResourceNotFound, ServiceDisabled

from ..application.commands import (
    AddTicketMessage,
    ChangeTicketStatus,
    CreateTicket,
    messages_for,
    support_scope,
    ticket_body,
    visible_tickets,
)
from ..application.conditional import conditional_routes
from ..models import TicketCategory, TicketState


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class TicketListView(ApiView):
    """API-112 (GET) and API-113 (POST)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        queryset = visible_tickets(snapshot)
        state = request.query_params.get("state")
        if state in TicketState.values:
            queryset = queryset.filter(state=state)
        category = request.query_params.get("category")
        if category in TicketCategory.values:
            queryset = queryset.filter(category=category)
        application_id = request.query_params.get("application_id")
        if application_id:
            try:
                queryset = queryset.filter(application_id=UUID(application_id))
            except ValueError:
                queryset = queryset.none()
        staff = snapshot.kind == PrincipalKind.STAFF
        rows = queryset.order_by("-updated_at")[:100]
        return ok(
            {
                "items": [ticket_body(t, staff=staff) for t in rows],
                "as_of": now.isoformat(),
                "support_scope": staff
                and any(support_scope(snapshot, t.owner_queue) for t in rows),
                "routes": conditional_routes(),
            },
            request,
        )

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            CreateTicket(),
            command_name="create-ticket",
            target_type="create-ticket:scope",
            target_id=UUID(str(principal.pk)),
            etag_type="ticket",
        )


class TicketDetailView(ApiView):
    """API-114: audience-filtered conversation."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, ticket_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        ticket = visible_tickets(snapshot).filter(pk=ticket_id).first()
        if ticket is None:
            raise ResourceNotFound("Ticket not found")
        staff = support_scope(snapshot, ticket.owner_queue)
        body: dict[str, Any] = {
            **ticket_body(ticket, staff=staff),
            "messages": messages_for(ticket, staff=staff),
            "is_requester": ticket.requester_id == principal.pk,
            "support_scope": staff,
            "allowed_actions": _allowed(
                ticket.state, requester=ticket.requester_id == principal.pk, staff=staff
            ),
        }
        response = ok(body, request)
        response["ETag"] = ticket.etag
        return response


def _allowed(state: str, *, requester: bool, staff: bool) -> list[dict[str, Any]]:
    from ..application.commands import REQUESTER_REOPEN, STAFF_TRANSITIONS

    actions: list[dict[str, Any]] = [
        {
            "key": "reply",
            "enabled": state != TicketState.CLOSED,
            "reason_code": None if state != TicketState.CLOSED else "CLOSED",
        },
        {
            "key": "internal-note",
            "enabled": staff and state != TicketState.CLOSED,
            "reason_code": None if staff else "STAFF_ONLY",
        },
    ]
    targets = (
        STAFF_TRANSITIONS.get(state, set())
        if staff
        else ({TicketState.IN_PROGRESS} if requester and state in REQUESTER_REOPEN else set())
    )
    for candidate in TicketState.values:
        actions.append(
            {
                "key": f"status:{candidate}",
                "enabled": candidate in targets,
                "reason_code": None if candidate in targets else "NOT_PERMITTED",
            }
        )
    return actions


class TicketMessagesView(ApiView):
    """API-115."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, ticket_id: UUID) -> Response:
        return self.run_command(
            request,
            AddTicketMessage(),
            command_name="ticket-message",
            target_type="ticket",
            target_id=ticket_id,
            etag_type="ticket",
        )


class TicketStatusView(ApiView):
    """API-116."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, ticket_id: UUID) -> Response:
        return self.run_command(
            request,
            ChangeTicketStatus(),
            command_name="ticket-status",
            target_type="ticket",
            target_id=ticket_id,
            etag_type="ticket",
        )


class SupportRoutesView(ApiView):
    """Profile-gated conditional routes for UI-26 (appeals referral, fees, declarations,
    external registration)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return ok(conditional_routes(), request)


class AppealsView(ApiView):
    """API-117: disabled until an approved appeal profile exists. Answers with the referral
    route; no appeal record is created and the source decision is untouched."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, **kwargs: Any) -> Response:
        routes = conditional_routes()
        appeals = routes["appeals"]
        raise ServiceDisabled(
            "Legal appeals are not enabled by the active profile; use the referral route",
            extensions={"feature": "appeals", **appeals},
        )
