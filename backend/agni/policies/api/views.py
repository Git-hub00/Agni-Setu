"""Policy and service endpoints: API-018/019 (catalogue, applicability), API-095..102 and
API-123 (governance). Reads are scope-filtered; writes go through the kernel."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    Forbidden,
    MalformedRequest,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)

from ..application.commands import (
    ActivatePolicy,
    ApprovePolicy,
    PatchPolicyDraft,
    PreparePolicyDraft,
    ReturnPolicy,
    RunPolicySimulation,
    SubmitPolicyForReview,
)
from ..models import Jurisdiction, PolicyState, PolicyVersion, Service
from ..selection import evaluate_applicability

CATEGORY_KEYS_MAX = 80


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _can_read_policies(principal: Principal) -> bool:
    snapshot = load_snapshot(principal, get_clock().now())
    return (
        snapshot.has_role(RoleKey.ADMIN)
        or snapshot.has_role(RoleKey.SUPERVISOR)
        or snapshot.has_role(RoleKey.POLICY_APPROVER)
        or snapshot.has_role(RoleKey.LEADERSHIP)
        or snapshot.grant_for(Capability.POLICY_APPROVE) is not None
        or snapshot.grant_for(Capability.POLICY_ACTIVATE) is not None
    )


def _policy_summary(v: PolicyVersion) -> dict[str, Any]:
    return {
        "policy_version_id": str(v.pk),
        "service_key": v.service.key,
        "jurisdiction_code": v.jurisdiction.code if v.jurisdiction else None,
        "number": v.number,
        "state": v.state,
        "payload_sha256": v.payload_sha256,
        "effective_from": v.effective_from.isoformat() if v.effective_from else None,
        "effective_until": v.effective_until.isoformat() if v.effective_until else None,
        "prepared_by": str(v.prepared_by_id),
        "approved_by": str(v.approved_by_id) if v.approved_by_id else None,
        "version": v.version,
        "updated_at": v.updated_at.isoformat(),
    }


class ServiceCatalogueView(ApiView):
    """API-018: enabled public services with safe availability explanations."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        category = request.query_params.get("category_key")
        if category is not None and (
            len(category) > CATEGORY_KEYS_MAX
            or not category.replace("-", "").replace("_", "").isalnum()
        ):
            raise MalformedRequest("category_key must be an allowlisted key")
        now = get_clock().now()
        items: list[dict[str, Any]] = []
        for service in Service.objects.select_related("owner_queue__jurisdiction").order_by("key"):
            applicability = (
                evaluate_applicability(
                    service,
                    jurisdiction_id=service.owner_queue.jurisdiction_id,
                    category_key=category or "",
                    at=now,
                )
                if service.active
                else None
            )
            available = bool(
                service.active and applicability and (applicability.policy_version_id is not None)
            )
            items.append(
                {
                    "service_id": str(service.pk),
                    "key": service.key,
                    "title": service.title,
                    "mode": service.mode,
                    "available": available,
                    "explanation": (
                        service.public_summary
                        if available
                        else (
                            applicability.explanation
                            if applicability
                            else "This service is not currently accepting applications."
                        )
                    ),
                    "allowed_categories": list(applicability.allowed_categories)
                    if applicability
                    else [],
                }
            )
        return ok(
            {"items": items, "service_mode": request._request.META.get("SERVICE_MODE", "DEMO")},
            request,
        )


class ApplicabilityView(ApiView):
    """API-019: nonbinding form/document preview; submission revalidates policy."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, service_id: UUID) -> Response:
        _principal(request)
        data = request.data if isinstance(request.data, dict) else {}
        unknown = set(data) - {
            "premises_id",
            "declared_category",
            "jurisdiction_or_ward_key",
            "area_sqm",
            "height_m",
            "occupancy_type",
            "intended_service_date",
        }
        violations = [Violation(f"/{k}", "unknown_field", "unknown field") for k in sorted(unknown)]
        category = str(data.get("declared_category", "")).strip()
        if not category:
            violations.append(Violation("/declared_category", "required", "is required"))
        if violations:
            raise ValidationFailed(violations=violations)
        service = Service.objects.select_related("owner_queue").filter(pk=service_id).first()
        if service is None:
            raise ResourceNotFound("Service not found")
        at = get_clock().now()
        intended = data.get("intended_service_date")
        if intended:
            parsed = parse_datetime(str(intended))
            if parsed is None or parsed.tzinfo is None:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/intended_service_date", "format", "must be an ISO 8601 UTC timestamp"
                        )
                    ]
                )
            at = parsed
        jurisdiction_id: UUID | None = service.owner_queue.jurisdiction_id
        ward_or_jurisdiction = data.get("jurisdiction_or_ward_key")
        if ward_or_jurisdiction:
            match = Jurisdiction.objects.filter(code=str(ward_or_jurisdiction)).first()
            if match is not None:
                jurisdiction_id = match.pk
        result = evaluate_applicability(
            service, jurisdiction_id=jurisdiction_id, category_key=category, at=at
        )
        return ok(result.as_dict(), request)


class PolicyListView(ApiView):
    """API-095 list / API-096 prepare."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        if not _can_read_policies(principal):
            raise Forbidden("Policy workspace is not available to your account")
        queryset = PolicyVersion.objects.select_related("service", "jurisdiction").order_by(
            "-created_at", "-id"
        )
        state = request.query_params.get("state")
        if state:
            if state not in PolicyState.values:
                raise MalformedRequest("unknown state filter")
            queryset = queryset.filter(state=state)
        service_key = request.query_params.get("service_key")
        if service_key:
            queryset = queryset.filter(service__key=service_key[:80])
        items = [_policy_summary(v) for v in queryset[:100]]
        return ok({"items": items, "next_cursor": None, "has_more": False}, request)

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            PreparePolicyDraft(),
            command_name="prepare-policy",
            target_type="prepare-policy:scope",
            target_id=principal.pk,
            etag_type="policy_version",
        )


class PolicyDetailView(ApiView):
    """API-097 detail / API-098 patch."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, policy_id: UUID) -> Response:
        principal = _principal(request)
        if not _can_read_policies(principal):
            raise Forbidden("Policy workspace is not available to your account")
        version = (
            PolicyVersion.objects.select_related("service", "jurisdiction")
            .filter(pk=policy_id)
            .first()
        )
        if version is None:
            raise ResourceNotFound("Policy version not found")
        detail = _policy_summary(version)
        detail.update(
            {
                "payload": version.payload,
                "schema_version": version.schema_version,
                "review_candidate_sha256": version.review_candidate_sha256 or None,
                "approval_basis": version.approval_basis,
                "returned_reason": version.returned_reason,
                "source_references": version.source_references,
                "contributors": [
                    {
                        "principal_id": str(c.principal_id),
                        "action": c.action,
                        "at": c.created_at.isoformat(),
                    }
                    for c in version.contributors.order_by("created_at")
                ],
                "simulations": [
                    {
                        "simulation_id": str(s.pk),
                        "candidate_sha256": s.candidate_sha256,
                        "suite": s.fixture_suite_key,
                        "passed": s.passed,
                        "completed_at": s.completed_at.isoformat(),
                    }
                    for s in version.simulations.order_by("-completed_at")[:10]
                ],
                "allowed_actions": _allowed_actions(version),
            }
        )
        response = ok(detail, request)
        response["ETag"] = f'"policy_version:{version.pk}:v{version.version}"'
        return response

    def patch(self, request: Request, policy_id: UUID) -> Response:
        return self.run_command(
            request,
            PatchPolicyDraft(),
            command_name="patch-policy",
            target_type="policy_version",
            target_id=policy_id,
            etag_type="policy_version",
        )


def _allowed_actions(version: PolicyVersion) -> list[dict[str, Any]]:
    """UI hints only; every command revalidates (functional spec s.2)."""
    return [
        {
            "key": "edit",
            "enabled": version.is_editable,
            "reason_code": None if version.is_editable else "NOT_EDITABLE",
        },
        {
            "key": "submit-review",
            "enabled": version.is_editable,
            "reason_code": None if version.is_editable else "NOT_EDITABLE",
        },
        {
            "key": "simulate",
            "enabled": version.state
            in (PolicyState.DRAFT, PolicyState.RETURNED, PolicyState.IN_REVIEW),
            "reason_code": None,
        },
        {
            "key": "approve",
            "enabled": version.state == PolicyState.IN_REVIEW,
            "reason_code": None if version.state == PolicyState.IN_REVIEW else "NOT_IN_REVIEW",
        },
        {
            "key": "return",
            "enabled": version.state == PolicyState.IN_REVIEW,
            "reason_code": None if version.state == PolicyState.IN_REVIEW else "NOT_IN_REVIEW",
        },
        {
            "key": "activate",
            "enabled": version.state in (PolicyState.APPROVED, PolicyState.SCHEDULED),
            "reason_code": None
            if version.state in (PolicyState.APPROVED, PolicyState.SCHEDULED)
            else "NOT_APPROVED",
        },
    ]


class _PolicyCommandView(ApiView):
    permission_classes = [IsAuthenticated]
    handler_factory: Any = None
    command_name = ""

    def post(self, request: Request, policy_id: UUID) -> Response:
        return self.run_command(
            request,
            self.handler_factory(),
            command_name=self.command_name,
            target_type="policy_version",
            target_id=policy_id,
            etag_type="policy_version",
        )


class PolicySubmitReviewView(_PolicyCommandView):
    handler_factory = SubmitPolicyForReview
    command_name = "submit-policy-review"


class PolicySimulateView(_PolicyCommandView):
    handler_factory = RunPolicySimulation
    command_name = "simulate-policy"


class PolicyApproveView(_PolicyCommandView):
    handler_factory = ApprovePolicy
    command_name = "approve-policy"


class PolicyReturnView(_PolicyCommandView):
    handler_factory = ReturnPolicy
    command_name = "return-policy"


class PolicyActivateView(_PolicyCommandView):
    handler_factory = ActivatePolicy
    command_name = "activate-policy"
