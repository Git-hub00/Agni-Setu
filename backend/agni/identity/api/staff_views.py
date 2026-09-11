"""Staff and authority governance endpoints (API-087..093; UI-21). Roster reads are scoped
(administrator: all staff; supervisor: staff bound in their jurisdictions); every write is a
kernel command with a reason, a version precondition and separation of duties."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count, Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.inspections.models import Assignment, AssignmentState
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, Forbidden, ResourceNotFound

from ..application.commands import (
    ApproveAuthorityGrant,
    DisablePrincipal,
    ProposeAuthorityGrant,
    ProvisionStaff,
    ReactivatePrincipal,
    RevokeAuthorityGrant,
)
from ..authz import AuthzSnapshot, load_snapshot
from ..domain.roles import RoleKey
from ..models import AuthorityGrant, GrantState, Principal, PrincipalKind, RoleBinding


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _roster_scope(snapshot: AuthzSnapshot) -> set[UUID] | None:
    """None = every staff member (administrator); otherwise the supervisor's jurisdictions."""
    if not snapshot.active or snapshot.kind != PrincipalKind.STAFF:
        raise Forbidden("The team roster is a staff-management view")
    if snapshot.has_role(RoleKey.ADMIN):
        return None
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
    if not jurisdictions:
        raise Forbidden("The team roster needs an administrator or supervisor role")
    return jurisdictions


def grant_body(grant: AuthorityGrant) -> dict[str, Any]:
    return {
        "grant_id": str(grant.pk),
        "subject_id": str(grant.subject_id),
        "capability": grant.capability,
        "scope_kind": grant.scope_kind,
        "jurisdiction_id": str(grant.jurisdiction_id) if grant.jurisdiction_id else None,
        "service_id": str(grant.service_id) if grant.service_id else None,
        "state": grant.state,
        "effective_from": grant.effective_from.isoformat(),
        "effective_until": grant.effective_until.isoformat() if grant.effective_until else None,
        "preparer_id": str(grant.preparer_id),
        "approver_id": str(grant.approver_id) if grant.approver_id else None,
        "approved_at": grant.approved_at.isoformat() if grant.approved_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "version": grant.version,
        "etag": f'"authority_grant:{grant.pk}:v{grant.version}"',
    }


def staff_body(
    principal: Principal,
    bindings: list[RoleBinding],
    grants: list[AuthorityGrant],
    workload: int,
    *,
    now: datetime,
) -> dict[str, Any]:
    return {
        "principal_id": str(principal.pk),
        "display_name": principal.display_name,
        "active": principal.is_active,
        "disabled_at": principal.disabled_at.isoformat() if principal.disabled_at else None,
        "identity_bound": bool(principal.external_subject),
        "roles": [
            {
                "binding_id": str(b.pk),
                "role_key": b.role_key,
                "jurisdiction_id": str(b.jurisdiction_id) if b.jurisdiction_id else None,
                "jurisdiction_code": b.jurisdiction.code if b.jurisdiction else None,
                "service_id": str(b.service_id) if b.service_id else None,
                "effective_from": b.effective_from.isoformat(),
                "effective_until": b.effective_until.isoformat() if b.effective_until else None,
                "revoked_at": b.revoked_at.isoformat() if b.revoked_at else None,
                "in_force": b.revoked_at is None
                and b.effective_from <= now
                and (b.effective_until is None or b.effective_until > now),
            }
            for b in bindings
        ],
        "grants": [grant_body(g) for g in grants],
        "workload": {"active_assignments": workload},
        "version": principal.version,
        "etag": f'"principal:{principal.pk}:v{principal.version}"',
    }


class StaffListView(ApiView):
    """API-087: roster with roles, grants and workload; contact/IdP identifiers are not shown."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        scope = _roster_scope(snapshot)
        staff = Principal.objects.filter(kind=PrincipalKind.STAFF)
        bindings = RoleBinding.objects.select_related("jurisdiction").order_by("effective_from")
        if scope is not None:
            bindings = bindings.filter(jurisdiction_id__in=scope)
            staff = staff.filter(pk__in=bindings.values("principal_id"))
        active = request.query_params.get("active")
        if active in ("true", "false"):
            staff = staff.filter(is_active=active == "true")
        role = request.query_params.get("role_key")
        if role:
            staff = staff.filter(
                pk__in=bindings.filter(role_key=role, revoked_at__isnull=True).values(
                    "principal_id"
                )
            )
        rows = list(staff.order_by("display_name")[:200])
        ids = [p.pk for p in rows]
        by_principal: dict[UUID, list[RoleBinding]] = {}
        for b in bindings.filter(principal_id__in=ids):
            by_principal.setdefault(b.principal_id, []).append(b)
        grants: dict[UUID, list[AuthorityGrant]] = {}
        grant_rows = AuthorityGrant.objects.filter(subject_id__in=ids).order_by("-created_at")
        if scope is not None:
            grant_rows = grant_rows.filter(Q(jurisdiction_id__in=scope) | Q(scope_kind="GLOBAL"))
        for g in grant_rows:
            grants.setdefault(g.subject_id, []).append(g)
        workload: dict[UUID, int] = {
            row["officer_id"]: row["n"]
            for row in Assignment.objects.filter(officer_id__in=ids, state=AssignmentState.ACTIVE)
            .values("officer_id")
            .annotate(n=Count("id"))
        }
        return ok(
            {
                "items": [
                    staff_body(
                        p,
                        by_principal.get(p.pk, []),
                        grants.get(p.pk, []),
                        workload.get(p.pk, 0),
                        now=now,
                    )
                    for p in rows
                ],
                "scope": "GLOBAL" if scope is None else "JURISDICTIONS",
                "as_of": now.isoformat(),
                "can_manage": snapshot.has_role(RoleKey.ADMIN),
            },
            request,
        )


class StaffDetailView(ApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, staff_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        scope = _roster_scope(snapshot)
        target = Principal.objects.filter(pk=staff_id, kind=PrincipalKind.STAFF).first()
        if target is None:
            raise ResourceNotFound("Staff member not found")
        bindings = list(
            RoleBinding.objects.filter(principal=target)
            .select_related("jurisdiction")
            .order_by("effective_from")
        )
        if scope is not None:
            bindings = [b for b in bindings if b.jurisdiction_id in scope]
            if not bindings:
                raise ResourceNotFound("Staff member not found")
        grants = list(AuthorityGrant.objects.filter(subject=target).order_by("-created_at"))
        workload = Assignment.objects.filter(officer=target, state=AssignmentState.ACTIVE).count()
        response = ok(staff_body(target, bindings, grants, workload, now=now), request)
        response["ETag"] = f'"principal:{target.pk}:v{target.version}"'
        return response


class StaffInvitationView(ApiView):
    """API-088: provision from an approved access request (never self)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            ProvisionStaff(),
            command_name="provision-staff",
            target_type="provision-staff:scope",
            target_id=UUID(str(principal.pk)),
            etag_type="principal",
        )


class StaffDeactivateView(ApiView):
    """API-089."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, staff_id: UUID) -> Response:
        return self.run_command(
            request,
            DisablePrincipal(),
            command_name="disable-principal",
            target_type="principal",
            target_id=staff_id,
            etag_type="principal",
        )


class StaffReactivateView(ApiView):
    """API-090."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, staff_id: UUID) -> Response:
        return self.run_command(
            request,
            ReactivatePrincipal(),
            command_name="reactivate-principal",
            target_type="principal",
            target_id=staff_id,
            etag_type="principal",
        )


class GrantListView(ApiView):
    """API-091 (POST proposes) plus a scoped listing of grants for UI-21."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        scope = _roster_scope(snapshot)
        rows = AuthorityGrant.objects.select_related("subject").order_by("-created_at")
        if scope is not None:
            rows = rows.filter(Q(jurisdiction_id__in=scope) | Q(scope_kind="GLOBAL"))
        state = request.query_params.get("state")
        if state in GrantState.values:
            rows = rows.filter(state=state)
        return ok(
            {
                "items": [
                    {**grant_body(g), "subject_display_name": g.subject.display_name}
                    for g in rows[:200]
                ],
                "as_of": now.isoformat(),
            },
            request,
        )

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            ProposeAuthorityGrant(),
            command_name="propose-grant",
            target_type="propose-grant:scope",
            target_id=UUID(str(principal.pk)),
            etag_type="authority_grant",
        )


class GrantApproveView(ApiView):
    """API-092: independent approval; `reason` is recorded as the approval basis."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, grant_id: UUID) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        return self.run_command(
            request,
            ApproveAuthorityGrant(),
            command_name="approve-grant",
            target_type="authority_grant",
            target_id=grant_id,
            etag_type="authority_grant",
            payload={"approval_basis": data.get("approval_basis") or data.get("reason") or ""},
        )


class GrantRevokeView(ApiView):
    """API-093."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, grant_id: UUID) -> Response:
        return self.run_command(
            request,
            RevokeAuthorityGrant(),
            command_name="revoke-grant",
            target_type="authority_grant",
            target_id=grant_id,
            etag_type="authority_grant",
        )
