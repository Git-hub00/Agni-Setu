"""Audit recording. Called only inside the command transaction; a failure here must abort the
mutation (task card B02: critical audit failure aborts)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from .canonical import canonical_sha256
from .models import AuditEvent


def record_audit(
    *,
    entity_type: str,
    entity_id: UUID,
    action: str,
    actor_id: UUID | None,
    request_id: UUID,
    at: datetime,
    summary: Mapping[str, Any],
    authority_grant_id: UUID | None = None,
) -> AuditEvent:
    """Append one audit row chained to the entity's previous row.

    The caller holds the entity's aggregate lock, which serialises the per-entity chain.
    """
    prior = (
        AuditEvent.objects.filter(entity_type=entity_type, entity_id=entity_id)
        .order_by("-timestamp", "-created_at")
        .values_list("hash", flat=True)
        .first()
    )
    digest = canonical_sha256(
        {
            "prior_hash": prior,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_id": actor_id,
            "request_id": request_id,
            "timestamp": at,
            "summary": summary,
        }
    )
    return AuditEvent.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        authority_grant_id=authority_grant_id,
        request_id=request_id,
        timestamp=at,
        safe_change_summary=dict(summary),
        prior_hash=prior,
        hash=digest,
    )


def verify_chain(entity_type: str, entity_id: UUID) -> bool:
    """Recompute the hash chain for one entity; False means a row was altered or removed."""
    expected_prior: str | None = None
    rows = AuditEvent.objects.filter(entity_type=entity_type, entity_id=entity_id).order_by(
        "timestamp", "created_at"
    )
    for row in rows:
        recomputed = canonical_sha256(
            {
                "prior_hash": expected_prior,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "action": row.action,
                "actor_id": row.actor_id,
                "request_id": row.request_id,
                "timestamp": row.timestamp,
                "summary": row.safe_change_summary,
            }
        )
        if row.prior_hash != expected_prior or row.hash != recomputed:
            return False
        expected_prior = row.hash
    return True
