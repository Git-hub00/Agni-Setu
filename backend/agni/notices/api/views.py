"""Notice endpoints API-053..062 (minus 059's decision context) with role-audience projections."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.cases.application.access import can_respond_to_notices
from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, ResourceNotFound

from ..application.commands import (
    AcceptInformation,
    CompleteCorrections,
    PublishNotice,
    RequireReinspection,
    ReviewItem,
    SubmitResponse,
    VerifyFinding,
)
from ..application.projections import finding_body, notice_body
from ..domain.rules import EVIDENCE_TYPES, pending_required_items
from ..models import ItemState, NoticeState, NoticeType
from ..selectors import visible_findings, visible_notices


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class NoticeListView(ApiView):
    """API-053 (GET) and API-054 (POST) on the case."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        staff = snapshot.kind != PrincipalKind.APPLICANT
        notices = (
            visible_notices(snapshot, now)
            .filter(application_id=application_id)
            .select_related("due_obligation")
            .order_by("type", "round_number")
        )
        return ok(
            {
                "items": [notice_body(n, staff=staff) for n in notices],
                "evidence_types": list(EVIDENCE_TYPES),
                "as_of": now.isoformat(),
            },
            request,
        )

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            PublishNotice(),
            command_name="publish-notice",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class NoticeDetailView(ApiView):
    """API-055."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, notice_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        staff = snapshot.kind != PrincipalKind.APPLICANT
        notice = (
            visible_notices(snapshot, now)
            .select_related("application__owner_queue__jurisdiction", "due_obligation")
            .filter(pk=notice_id)
            .first()
        )
        if notice is None:
            raise ResourceNotFound("Notice not found")
        application = notice.application
        jurisdiction_id = application.owner_queue.jurisdiction_id
        supervisor_here = snapshot.has_role(RoleKey.SUPERVISOR, jurisdiction_id=jurisdiction_id)
        publisher = supervisor_here and (
            snapshot.grant_for(Capability.NOTICE_PUBLISH, jurisdiction_id=jurisdiction_id)
            is not None
        )
        open_notice = notice.state == NoticeState.PUBLISHED
        items = list(notice.items.select_related("finding").all())
        can_respond = (
            open_notice
            and can_respond_to_notices(principal, application, now)
            and any(
                i.state in (ItemState.OPEN, ItemState.RETURNED, ItemState.RESPONSE_RECEIVED)
                for i in items
            )
        )
        reviewable = any(
            i.state in (ItemState.RESPONSE_RECEIVED, ItemState.UNDER_REVIEW) for i in items
        )
        pending = pending_required_items(items)
        actions: list[dict[str, Any]] = [
            {
                "key": "respond",
                "enabled": can_respond,
                "reason_code": None
                if can_respond
                else ("NOTICE_NOT_OPEN" if not open_notice else "NOT_AUTHORIZED"),
            },
            {
                "key": "review-item",
                "enabled": supervisor_here and open_notice and reviewable,
                "reason_code": None
                if (supervisor_here and open_notice and reviewable)
                else "NOTHING_TO_REVIEW",
            },
            {
                "key": "verify-finding",
                "enabled": publisher and open_notice and notice.type == NoticeType.DEFICIENCY,
                "reason_code": None if publisher else "NOT_AUTHORIZED",
            },
            {
                "key": "accept-information",
                "enabled": supervisor_here
                and open_notice
                and notice.type == NoticeType.INFORMATION
                and not pending
                and application.status == "INFO_REQUIRED",
                "reason_code": None
                if (
                    supervisor_here
                    and open_notice
                    and notice.type == NoticeType.INFORMATION
                    and not pending
                )
                else ("RESPONSE_NOT_VERIFIED" if pending else "NOT_AVAILABLE"),
            },
        ]
        body = {
            **notice_body(notice, staff=staff),
            "application_status": application.status,
            "application_version": application.version,
            "public_reference": application.public_reference,
            "evidence_types": list(EVIDENCE_TYPES),
            "allowed_actions": actions,
        }
        response = ok(body, request)
        response["ETag"] = notice.etag
        return response


class NoticeResponsesView(ApiView):
    """API-056."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, notice_id: UUID) -> Response:
        return self.run_command(
            request,
            SubmitResponse(),
            command_name="submit-response",
            target_type="notice",
            target_id=notice_id,
            etag_type="notice",
        )


class AcceptInformationView(ApiView):
    """API-057."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, notice_id: UUID) -> Response:
        return self.run_command(
            request,
            AcceptInformation(),
            command_name="accept-information",
            target_type="notice",
            target_id=notice_id,
            etag_type="notice",
        )


class ItemReviewView(ApiView):
    """API-058."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, item_id: UUID) -> Response:
        return self.run_command(
            request,
            ReviewItem(),
            command_name="review-notice-item",
            target_type="notice_item",
            target_id=item_id,
            etag_type="notice_item",
        )


class FindingListView(ApiView):
    """API-059."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        staff = snapshot.kind != PrincipalKind.APPLICANT
        findings = (
            visible_findings(snapshot, now)
            .filter(application_id=application_id)
            .order_by("checklist_item_code", "created_at")
        )
        rows = [finding_body(f, staff=staff) for f in findings]
        for row, finding in zip(rows, findings, strict=True):
            row["etag"] = finding.etag
        return ok({"items": rows, "as_of": now.isoformat()}, request)


class FindingVerifyView(ApiView):
    """API-060."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, finding_id: UUID) -> Response:
        return self.run_command(
            request,
            VerifyFinding(),
            command_name="verify-finding",
            target_type="finding",
            target_id=finding_id,
            etag_type="finding",
        )


class CompleteCorrectionsView(ApiView):
    """API-061."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            CompleteCorrections(),
            command_name="complete-corrections",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class ReinspectView(ApiView):
    """API-062."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            RequireReinspection(),
            command_name="require-reinspection",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )
