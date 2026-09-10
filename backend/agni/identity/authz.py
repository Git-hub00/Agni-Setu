"""Authorization snapshot and checks (security s.5-6). Deny by default. The snapshot is
loaded from current server records (active flag, epoch, effective role bindings, approved
effective grants) - never from the session or the request."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from django.db.models import Q

from agni.platform.errors import AuthorityRevoked, AuthorityScopeMismatch, Forbidden

from .domain.roles import ROLE_WORKSPACE, Capability, RoleKey, ScopeKind, Workspace
from .models import AuthorityGrant, GrantState, Principal, PrincipalKind, RoleBinding


@dataclass(frozen=True)
class RoleScope:
    role: RoleKey
    jurisdiction_id: UUID | None
    service_id: UUID | None


@dataclass(frozen=True)
class GrantScope:
    grant_id: UUID
    capability: Capability
    scope_kind: ScopeKind
    jurisdiction_id: UUID | None
    service_id: UUID | None
    category_keys: tuple[str, ...]


@dataclass(frozen=True)
class AuthzSnapshot:
    principal_id: UUID
    kind: str
    active: bool
    authz_epoch: int
    evaluated_at: datetime
    roles: tuple[RoleScope, ...] = ()
    grants: tuple[GrantScope, ...] = ()
    display_name: str = ""
    _: None = field(default=None, repr=False, compare=False)

    @property
    def workspaces(self) -> list[Workspace]:
        spaces: list[Workspace] = []
        if self.kind == PrincipalKind.APPLICANT:
            spaces.append(Workspace.APPLICANT)
        for scope in self.roles:
            ws = ROLE_WORKSPACE[scope.role]
            if ws not in spaces:
                spaces.append(ws)
        return spaces

    def has_role(
        self, role: RoleKey, *, jurisdiction_id: UUID | None = None, service_id: UUID | None = None
    ) -> bool:
        for scope in self.roles:
            if scope.role != role:
                continue
            if jurisdiction_id is not None and scope.jurisdiction_id not in (None, jurisdiction_id):
                continue
            if service_id is not None and scope.service_id not in (None, service_id):
                continue
            return True
        return False

    def jurisdictions_for(self, role: RoleKey) -> set[UUID]:
        return {
            s.jurisdiction_id
            for s in self.roles
            if s.role == role and s.jurisdiction_id is not None
        }

    def grant_for(
        self,
        capability: Capability,
        *,
        jurisdiction_id: UUID | None = None,
        service_id: UUID | None = None,
        category_key: str | None = None,
    ) -> GrantScope | None:
        for grant in self.grants:
            if grant.capability != capability:
                continue
            if (
                grant.scope_kind == ScopeKind.JURISDICTION
                and grant.jurisdiction_id != jurisdiction_id
            ):
                continue
            if grant.scope_kind == ScopeKind.SERVICE and grant.service_id != service_id:
                continue
            if (
                grant.category_keys
                and category_key is not None
                and category_key not in grant.category_keys
            ):
                continue
            return grant
        return None


def load_snapshot(principal: Principal, at: datetime) -> AuthzSnapshot:
    roles = tuple(
        RoleScope(RoleKey(b.role_key), b.jurisdiction_id, b.service_id)
        for b in RoleBinding.objects.filter(
            principal=principal, revoked_at__isnull=True, effective_from__lte=at
        )
        .filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
        .order_by("created_at")
    )
    grants = tuple(
        GrantScope(
            g.id,
            Capability(g.capability),
            ScopeKind(g.scope_kind),
            g.jurisdiction_id,
            g.service_id,
            tuple(g.category_keys or ()),
        )
        for g in AuthorityGrant.objects.filter(
            subject=principal,
            state=GrantState.APPROVED,
            revoked_at__isnull=True,
            effective_from__lte=at,
        )
        .filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
        .order_by("created_at")
    )
    return AuthzSnapshot(
        principal_id=principal.pk,
        kind=principal.kind,
        active=principal.is_active,
        authz_epoch=principal.authz_epoch,
        evaluated_at=at,
        roles=roles,
        grants=grants,
        display_name=principal.display_name,
    )


def require_active(snapshot: AuthzSnapshot) -> None:
    if not snapshot.active:
        raise AuthorityRevoked("Account is disabled")


def require_role(
    snapshot: AuthzSnapshot, *roles: RoleKey, jurisdiction_id: UUID | None = None
) -> RoleKey:
    require_active(snapshot)
    for role in roles:
        if snapshot.has_role(role, jurisdiction_id=jurisdiction_id):
            return role
    raise Forbidden("This workspace is not available to your account")


def require_capability(
    snapshot: AuthzSnapshot,
    capability: Capability,
    *,
    jurisdiction_id: UUID | None = None,
    service_id: UUID | None = None,
    category_key: str | None = None,
) -> GrantScope:
    require_active(snapshot)
    grant = snapshot.grant_for(
        capability,
        jurisdiction_id=jurisdiction_id,
        service_id=service_id,
        category_key=category_key,
    )
    if grant is None:
        if any(g.capability == capability for g in snapshot.grants):
            raise AuthorityScopeMismatch("Your authority does not cover this scope")
        raise Forbidden("This action requires an approved authority grant")
    return grant


def require_different_actor(actor_id: UUID, *others: UUID | None) -> None:
    from agni.platform.errors import SeparationOfDuties

    if any(other == actor_id for other in others if other is not None):
        raise SeparationOfDuties()


def principal_projection(
    snapshot: AuthzSnapshot,
    *,
    session_expires_at: datetime | None,
    feature_gates: dict[str, object],
) -> dict[str, object]:
    """API-007 `Principal` projection: safe labels only; no tokens, hashes or other users'
    grants."""
    return {
        "id": str(snapshot.principal_id),
        "display_name": snapshot.display_name,
        "kind": snapshot.kind,
        "workspaces": [w.value for w in snapshot.workspaces],
        "active_workspace": snapshot.workspaces[0].value
        if snapshot.workspaces
        else Workspace.PUBLIC.value,
        "scopes": sorted({_scope_label(r) for r in snapshot.roles}),
        "capabilities": sorted({g.capability.value for g in snapshot.grants}),
        "authz_epoch": snapshot.authz_epoch,
        "session_expires_at": session_expires_at.isoformat() if session_expires_at else None,
        "feature_gates": feature_gates,
    }


def _scope_label(scope: RoleScope) -> str:
    parts = [scope.role.value.lower()]
    if scope.jurisdiction_id:
        parts.append(f"jurisdiction:{scope.jurisdiction_id}")
    if scope.service_id:
        parts.append(f"service:{scope.service_id}")
    return "/".join(parts)


def visible_principal_ids(snapshot: AuthzSnapshot, candidates: Iterable[UUID]) -> set[UUID]:
    """Applicants only ever see themselves; staff visibility of identities is scope-specific
    and decided by the feature that exposes it."""
    if snapshot.kind == PrincipalKind.APPLICANT:
        return {snapshot.principal_id} & set(candidates)
    return set()
