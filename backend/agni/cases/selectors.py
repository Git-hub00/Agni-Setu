"""Scoped read selectors (security s.5-6, data model s.7). Every list and detail read starts
from one of these: scope is applied BEFORE filtering, counting or searching. A record outside
the reader's scope is indistinguishable from a missing one (RESOURCE_NOT_FOUND)."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from agni.identity.authz import AuthzSnapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind

from .models import Application, Premises


def visible_premises(snapshot: AuthzSnapshot) -> QuerySet[Premises]:
    if not snapshot.active:
        return Premises.objects.none()
    if snapshot.kind == PrincipalKind.APPLICANT:
        return Premises.objects.filter(owner_id=snapshot.principal_id)
    # Staff read premises only through the cases they may see (B06 joins); none directly.
    return Premises.objects.none()


def visible_applications(snapshot: AuthzSnapshot) -> QuerySet[Application]:
    """Applicant: own or acting-operator cases. Supervisor/leadership: cases whose owner queue
    belongs to a jurisdiction in their role scope (leadership is read-only; enforced at the
    command layer). Officers see assigned attempts only (B07). Admin/policy: none here."""
    if not snapshot.active:
        return Application.objects.none()
    if snapshot.kind == PrincipalKind.APPLICANT:
        return Application.objects.filter(
            Q(applicant_id=snapshot.principal_id) | Q(acting_operator_id=snapshot.principal_id)
        )
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    global_roles = any(
        s.role in (RoleKey.SUPERVISOR, RoleKey.LEADERSHIP) and s.jurisdiction_id is None
        for s in snapshot.roles
    )
    if global_roles:
        # A NULL jurisdiction on a binding never means global access (data model s.3). Deny.
        return Application.objects.none() if not jurisdictions else _by_jurisdiction(jurisdictions)
    if jurisdictions:
        return _by_jurisdiction(jurisdictions)
    return Application.objects.none()


def _by_jurisdiction(jurisdictions: set) -> QuerySet[Application]:  # type: ignore[type-arg]
    return Application.objects.filter(owner_queue__jurisdiction_id__in=jurisdictions).exclude(
        status="DRAFT"
    )
