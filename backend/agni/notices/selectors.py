"""Scoped notice and finding reads: whoever can see the case can see its notices and findings
(applicant projections drop internal notes at the projection layer)."""

from __future__ import annotations

from datetime import datetime

from django.db.models import QuerySet

from agni.cases.selectors import visible_applications
from agni.identity.authz import AuthzSnapshot

from .models import Finding, Notice


def visible_notices(snapshot: AuthzSnapshot, at: datetime) -> QuerySet[Notice]:
    if not snapshot.active:
        return Notice.objects.none()
    return Notice.objects.filter(application__in=visible_applications(snapshot, at).values("pk"))


def visible_findings(snapshot: AuthzSnapshot, at: datetime) -> QuerySet[Finding]:
    if not snapshot.active:
        return Finding.objects.none()
    return Finding.objects.filter(application__in=visible_applications(snapshot, at).values("pk"))
