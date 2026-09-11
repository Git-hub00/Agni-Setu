"""Officer eligibility and scheduling checks (FR-08). Pure reads over current facts; callers
hold the officer's scheduling fence (principal fence) before booking."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet

from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind, RoleBinding

from .models import Assignment, AssignmentState, Availability, AvailabilityKind


def eligible_officers(jurisdiction_id: UUID | None, at: datetime) -> QuerySet[Principal]:
    """Active STAFF principals with an effective OFFICER binding in the jurisdiction. A NULL
    jurisdiction on a binding never means global (data model s.3), so a case without a
    jurisdiction has no eligible officers."""
    if jurisdiction_id is None:
        return Principal.objects.none()
    bindings = RoleBinding.objects.filter(
        role_key=RoleKey.OFFICER,
        jurisdiction_id=jurisdiction_id,
        revoked_at__isnull=True,
        effective_from__lte=at,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
    return Principal.objects.filter(
        kind=PrincipalKind.STAFF, is_active=True, pk__in=bindings.values("principal_id")
    ).order_by("display_name")


def is_eligible(officer_id: UUID, jurisdiction_id: UUID | None, at: datetime) -> bool:
    return eligible_officers(jurisdiction_id, at).filter(pk=officer_id).exists()


def unavailable_between(officer_id: UUID, starts_at: datetime, ends_at: datetime) -> bool:
    return Availability.objects.filter(
        officer_id=officer_id,
        kind=AvailabilityKind.UNAVAILABLE,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exists()


def overlapping_bookings(
    officer_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_inspection_id: UUID | None = None,
) -> QuerySet[Assignment]:
    """Half-open overlap of ACTIVE bookings; the database exclusion constraint is the final
    guard under concurrency, this query gives the human-readable conflict."""
    queryset = Assignment.objects.filter(
        officer_id=officer_id,
        state=AssignmentState.ACTIVE,
        booking_start__lt=ends_at,
        booking_end__gt=starts_at,
    )
    if exclude_inspection_id:
        queryset = queryset.exclude(inspection_id=exclude_inspection_id)
    return queryset
