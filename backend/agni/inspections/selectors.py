"""Scoped inspection reads: officers see attempts they are (or were) assigned to; supervisors
and leadership see attempts of cases in their jurisdictions; applicants see the appointment facts
of their own cases through the case timeline, not this selector."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q, QuerySet

from agni.identity.authz import AuthzSnapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind

from .models import Inspection


def visible_inspections(snapshot: AuthzSnapshot, at: datetime) -> QuerySet[Inspection]:
    if not snapshot.active or snapshot.kind == PrincipalKind.APPLICANT:
        return Inspection.objects.none()
    scope = Q(pk__in=[])
    if snapshot.has_role(RoleKey.OFFICER):
        scope |= Q(assignments__officer_id=snapshot.principal_id)
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR) | snapshot.jurisdictions_for(
        RoleKey.LEADERSHIP
    )
    if jurisdictions:
        scope |= Q(application__owner_queue__jurisdiction_id__in=jurisdictions)
    return Inspection.objects.filter(scope).distinct()
