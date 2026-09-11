"""Audit reader (API-085/086; UI-23). Scoped, redacted where the role requires it, and every
read is recorded on the reader's own audit chain."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.models import Principal

from .. import audit, audit_reader
from ..clock import get_clock
from ..correlation import current_request_id
from ..errors import AuthenticationRequired, ResourceNotFound, ValidationFailed
from .views import ApiView, ok


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


class AuditListView(ApiView):
    """API-085: permitted event fields; the query itself is audited."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        queryset, redact = audit_reader.audit_scope(snapshot, now)
        filters, violations = audit_reader.parse_audit_filters(request.query_params)
        if violations:
            raise ValidationFailed(violations=violations)
        limit = int(filters.get("limit", 25))
        rows = list(
            audit_reader.apply_filters(queryset, filters).order_by("-timestamp", "-created_at")[
                : limit + 1
            ]
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        with transaction.atomic():
            audit_reader.record_audit_read(
                principal_id=UUID(str(principal.pk)),
                request_id=current_request_id() or UUID(int=0),
                now=now,
                filters=filters,
                count=len(rows),
            )
        return ok(
            {
                "items": [audit_reader.audit_body(r, redact=redact) for r in rows],
                "has_more": has_more,
                "redacted": redact,
                "as_of": now.isoformat(),
                "notice": (
                    "Integrity is checked against the per-entity hash chain; this is tamper "
                    "evidence, not immutability against every administrator."
                ),
            },
            request,
        )


class AuditDetailView(ApiView):
    """API-086: safe redacted detail plus integrity metadata (chain verified on read)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, audit_event_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        queryset, redact = audit_reader.audit_scope(snapshot, now)
        row = queryset.filter(pk=audit_event_id).first()
        if row is None:
            raise ResourceNotFound("Audit event not found")
        chain_valid = audit.verify_chain(row.entity_type, row.entity_id)
        with transaction.atomic():
            audit_reader.record_audit_read(
                principal_id=UUID(str(principal.pk)),
                request_id=current_request_id() or UUID(int=0),
                now=now,
                filters={"entity_type": row.entity_type},
                count=1,
                detail_id=row.pk,
            )
        return ok(
            {
                **audit_reader.audit_body(row, redact=redact),
                "integrity": {
                    "chain_valid": chain_valid,
                    "checked_at": now.isoformat(),
                    "label": "Integrity checked against chain"
                    if chain_valid
                    else "Chain mismatch - investigate",
                },
            },
            request,
        )
