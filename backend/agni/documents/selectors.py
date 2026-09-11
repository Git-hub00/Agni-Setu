"""Scoped document reads: a document is visible to its uploader and to every reader who can see
the owning application (cases selectors decide that). Rejected files stay listed with their
state but are never served."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q, QuerySet

from agni.cases.selectors import visible_applications
from agni.identity.authz import AuthzSnapshot

from .models import DocumentVersion


def visible_documents(snapshot: AuthzSnapshot, at: datetime) -> QuerySet[DocumentVersion]:
    if not snapshot.active:
        return DocumentVersion.objects.none()
    applications = visible_applications(snapshot, at).values("pk")
    return DocumentVersion.objects.filter(
        Q(uploaded_by_id=snapshot.principal_id) | Q(application_id__in=applications)
    )
