"""Premises endpoints API-010..013 (FR-03). Application endpoints live in `case_views`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, ResourceNotFound

from ..application.commands import RegisterPremises, UpdatePremises
from ..models import Premises
from ..selectors import visible_premises


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def premises_projection(p: Premises) -> dict[str, Any]:
    return {
        "premises_id": str(p.pk),
        "owner_id": str(p.owner_id),
        "display_name": p.display_name,
        "address_line1": p.address_line1,
        "address_line2": p.address_line2,
        "locality": p.locality,
        "ward_key": p.ward_key,
        "postal_code": p.postal_code,
        "category_key": p.category_key,
        "area_sqm": str(p.area_sqm),
        "height_m": str(p.height_m),
        "floor_count": p.floor_count,
        "occupancy_count": p.occupancy_count,
        "version": p.version,
        "updated_at": p.updated_at.isoformat(),
    }


class PremisesListView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        rows = visible_premises(load_snapshot(principal, now), now).order_by("-created_at", "-id")[
            :100
        ]
        return ok(
            {
                "items": [premises_projection(p) for p in rows],
                "next_cursor": None,
                "has_more": False,
            },
            request,
        )

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            RegisterPremises(),
            command_name="register-premises",
            target_type="register-premises:scope",
            target_id=principal.pk,
            etag_type="premises",
        )


class PremisesDetailView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, premises_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        premises = (
            visible_premises(load_snapshot(principal, now), now).filter(pk=premises_id).first()
        )
        if premises is None:
            raise ResourceNotFound("Premises not found")
        response = ok(
            {
                **premises_projection(premises),
                "allowed_actions": [
                    {
                        "key": "edit",
                        "enabled": premises.owner_id == principal.pk,
                        "reason_code": None,
                    }
                ],
            },
            request,
        )
        response["ETag"] = premises.etag
        return response

    def patch(self, request: Request, premises_id: UUID) -> Response:
        return self.run_command(
            request,
            UpdatePremises(),
            command_name="update-premises",
            target_type="premises",
            target_id=premises_id,
            etag_type="premises",
        )
