"""Scoped read selectors (security s.5-6, data model s.7). Every list and detail read starts
from one of these: scope is applied BEFORE filtering, counting or searching. A record outside
the reader's scope is indistinguishable from a missing one (RESOURCE_NOT_FOUND)."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q, QuerySet

from agni.identity.application.delegations import active_delegations_for
from agni.identity.authz import AuthzSnapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind

from .models import Application, Premises


def _delegation_filters(snapshot: AuthzSnapshot, at: datetime | None) -> tuple[Q, Q]:
    """(premises filter, application filter) contributed by ACTIVE delegations held by the
    reader (FR-10). Without an instant, delegations are ignored."""
    if at is None or snapshot.kind != PrincipalKind.APPLICANT:
        return Q(pk__in=[]), Q(pk__in=[])
    delegate = Principal.objects.filter(pk=snapshot.principal_id).first()
    if delegate is None:
        return Q(pk__in=[]), Q(pk__in=[])
    premises_q = Q(pk__in=[])
    application_q = Q(pk__in=[])
    for delegation in active_delegations_for(delegate, at):
        if delegation.premises_id:
            premises_q |= Q(pk=delegation.premises_id)
            application_q |= Q(
                premises_id=delegation.premises_id, applicant_id=delegation.beneficiary_id
            )
        elif delegation.service_id:
            application_q |= Q(
                service_id=delegation.service_id, applicant_id=delegation.beneficiary_id
            )
    return premises_q, application_q


def visible_premises(snapshot: AuthzSnapshot, at: datetime | None = None) -> QuerySet[Premises]:
    if not snapshot.active:
        return Premises.objects.none()
    if snapshot.kind == PrincipalKind.APPLICANT:
        premises_q, _ = _delegation_filters(snapshot, at)
        return Premises.objects.filter(Q(owner_id=snapshot.principal_id) | premises_q)
    # Staff read premises only through the cases they may see (B06 joins); none directly.
    return Premises.objects.none()


def visible_applications(
    snapshot: AuthzSnapshot, at: datetime | None = None
) -> QuerySet[Application]:
    """Applicant: own, acting-operator, or actively delegated cases. Supervisor/leadership:
    received cases whose owner queue belongs to a jurisdiction in their role scope (leadership is
    read-only; enforced at the command layer). Officers see assigned attempts only (B07).
    Admin/policy: none here."""
    if not snapshot.active:
        return Application.objects.none()
    if snapshot.kind == PrincipalKind.APPLICANT:
        _, application_q = _delegation_filters(snapshot, at)
        return Application.objects.filter(
            Q(applicant_id=snapshot.principal_id)
            | Q(acting_operator_id=snapshot.principal_id)
            | application_q
        )
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    if jurisdictions:
        # A NULL jurisdiction on a binding never means global access (data model s.3).
        return Application.objects.filter(owner_queue__jurisdiction_id__in=jurisdictions).exclude(
            status="DRAFT"
        )
    return Application.objects.none()
