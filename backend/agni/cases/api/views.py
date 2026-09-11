"""Premises endpoints API-010..013 (FR-03) and application endpoints API-020..023 (FR-04/FR-09).
Reads use the scoped selectors; writes use the kernel."""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, MalformedRequest, ResourceNotFound
from agni.policies.selection import evaluate_applicability

from ..application.access import can_edit_draft
from ..application.commands import CreateDraftApplication, RegisterPremises, UpdatePremises
from ..application.drafts import PatchDraft, draft_projection
from ..domain.states import ApplicationStatus, allowed_transitions
from ..models import Application, Premises
from ..selectors import visible_applications, visible_premises

PAGE_SIZE = 20


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


# ---- applications ---------------------------------------------------------------------------


def case_summary(a: Application) -> dict[str, Any]:
    return {
        "application_id": str(a.pk),
        "draft_reference": a.draft_reference,
        "public_reference": a.public_reference,
        "status": a.status,
        "service_key": a.service.key,
        "premises": {
            "premises_id": str(a.premises_id),
            "display_name": a.premises.display_name,
            "category_key": a.premises.category_key,
            "locality": a.premises.locality,
        },
        "owner_queue": a.owner_queue.display_name,
        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
        "version": a.version,
    }


def _encode_cursor(a: Application) -> str:
    raw = f"{a.created_at.isoformat()}|{a.pk}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        created, pk = base64.urlsafe_b64decode(value.encode()).decode().split("|", 1)
        UUID(pk)
        return created, pk
    except Exception as exc:  # noqa: BLE001
        raise MalformedRequest("cursor is not valid") from exc


class ApplicationListView(ApiView):
    """API-020 list (scope before filter/count; stable cursor) and API-021 create."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        queryset = visible_applications(load_snapshot(principal, now), now).select_related(
            "service", "premises", "owner_queue"
        )
        status = request.query_params.get("status")
        if status:
            if status not in ApplicationStatus.__members__:
                raise MalformedRequest("unknown status filter")
            queryset = queryset.filter(status=status)
        query = (request.query_params.get("q") or "").strip()[:80]
        if query:
            queryset = queryset.filter(
                Q(draft_reference__icontains=query)
                | Q(public_reference__icontains=query)
                | Q(premises__display_name__icontains=query)
            )
        cursor = request.query_params.get("cursor")
        if cursor:
            created, pk = _decode_cursor(cursor)
            queryset = queryset.filter(Q(created_at__lt=created) | Q(created_at=created, id__lt=pk))
        rows = list(queryset.order_by("-created_at", "-id")[: PAGE_SIZE + 1])
        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        return ok(
            {
                "items": [case_summary(a) for a in rows],
                "next_cursor": _encode_cursor(rows[-1]) if has_more and rows else None,
                "has_more": has_more,
            },
            request,
        )

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            CreateDraftApplication(),
            command_name="create-draft",
            target_type="create-draft:scope",
            target_id=principal.pk,
            etag_type="application",
        )


class ApplicationDetailView(ApiView):
    """API-022: canonical detail with allowed actions and safe blockers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        application = (
            visible_applications(load_snapshot(principal, now), now)
            .select_related(
                "service__owner_queue", "premises", "owner_queue", "current_draft_revision"
            )
            .filter(pk=application_id)
            .first()
        )
        if application is None:
            raise ResourceNotFound("Application not found")
        editable = application.status == "DRAFT" and can_edit_draft(principal, application, now)
        draft = draft_projection(application, now) if application.status == "DRAFT" else None
        applicability = evaluate_applicability(
            application.service,
            jurisdiction_id=application.service.owner_queue.jurisdiction_id,
            category_key=str(
                (draft or {}).get("fields", {}).get("category_key")
                or application.premises.category_key
            ),
            at=now,
        )
        actions: list[dict[str, Any]] = [
            {
                "key": "edit-draft",
                "enabled": editable,
                "reason_code": None if editable else "NOT_EDITABLE",
            }
        ]
        for _, command, _ in allowed_transitions(application.status_enum):
            reason: str | None
            if command == "submit":
                reason = (
                    "SUBMISSION_NOT_AVAILABLE_YET"  # B06 delivers TR-01
                    if not (draft or {}).get("blockers")
                    else "DRAFT_INCOMPLETE"
                )
            else:
                reason = "NOT_AVAILABLE_YET"
            actions.append({"key": command, "enabled": False, "reason_code": reason})
        body = {
            **case_summary(application),
            "premises_detail": premises_projection(application.premises),
            "policy": {
                "applicable": applicability.applicable,
                "policy_version_id": str(applicability.policy_version_id)
                if applicability.policy_version_id
                else None,
                "policy_number": applicability.policy_number,
                "explanation": applicability.explanation,
                "inspection_required": applicability.inspection_required,
            },
            "draft": draft,
            "allowed_actions": actions,
        }
        response = ok(body, request)
        response["ETag"] = application.etag
        return response


class DraftPatchView(ApiView):
    """API-023."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            PatchDraft(),
            command_name="patch-draft",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )
