"""Delegation endpoints API-014..017 (FR-10)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.platform.api.views import ApiView, ok
from agni.platform.errors import AuthenticationRequired

from ..application.delegations import ConfirmDelegation, ProposeDelegation, RevokeDelegation, _body
from ..models import Delegation, Principal


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class DelegationListView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        rows = Delegation.objects.filter(Q(beneficiary=principal) | Q(delegate=principal)).order_by(
            "-created_at"
        )[:100]
        items: list[dict[str, Any]] = [
            {
                **_body(d),
                "role": "beneficiary" if d.beneficiary_id == principal.pk else "delegate",
                "reason": d.reason,
            }
            for d in rows
        ]
        return ok({"items": items, "next_cursor": None, "has_more": False}, request)

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            ProposeDelegation(),
            command_name="propose-delegation",
            target_type="propose-delegation:scope",
            target_id=principal.pk,
            etag_type="delegation",
        )


class DelegationConfirmView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, delegation_id: UUID) -> Response:
        return self.run_command(
            request,
            ConfirmDelegation(),
            command_name="confirm-delegation",
            target_type="delegation",
            target_id=delegation_id,
            etag_type="delegation",
        )


class DelegationRevokeView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, delegation_id: UUID) -> Response:
        return self.run_command(
            request,
            RevokeDelegation(),
            command_name="revoke-delegation",
            target_type="delegation",
            target_id=delegation_id,
            etag_type="delegation",
        )
