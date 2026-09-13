"""Audit recording. Called only inside the command transaction; a failure here must abort the
mutation (task card B02: critical audit failure aborts).

Every entity owns one hash chain. Appends are serialised per chain with a transaction-scoped
advisory lock, because not every caller holds an aggregate lock: audit searches record their own
`audit_query` event on the reader's chain from a plain read request, and two overlapping searches
by the same reader forked that chain in the production-readiness run of 2026-09-13 (DEF-015).
The chain is defined by its links (`prior_hash`), never by the caller-supplied event time: a
request that started earlier may commit later, so both the head selection and the verification
follow the links.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import connection, transaction

from .canonical import canonical_sha256
from .models import AuditEvent


def chain_lock_key(entity_type: str, entity_id: UUID) -> int:
    """Stable signed 64-bit key for `pg_advisory_xact_lock(bigint)` derived from the chain id."""
    digest = hashlib.sha256(f"{entity_type}:{entity_id}".encode()).digest()
    return int(struct.unpack(">q", digest[:8])[0])


def chain_head(entity_type: str, entity_id: UUID) -> str | None:
    """Hash of the row nothing chains to yet; None for an empty chain.

    Chosen by following the links, not by event time. A chain that was forked before appends
    were serialised has several heads: the newest branch is extended so new rows stay
    verifiable from there, while `verify_chain` keeps reporting the historical fork."""
    rows = list(
        AuditEvent.objects.filter(entity_type=entity_type, entity_id=entity_id).values_list(
            "hash", "prior_hash", "created_at"
        )
    )
    if not rows:
        return None
    referenced = {prior for _, prior, _ in rows if prior is not None}
    heads = [(created_at, digest) for digest, _, created_at in rows if digest not in referenced]
    if not heads:
        # Every row is referenced (a cycle) - impossible for honest rows; extend the newest.
        heads = [(created_at, digest) for digest, _, created_at in rows]
    return max(heads)[1]


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
    """Append one audit row chained to the entity's current head, serialised per chain."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)", [chain_lock_key(entity_type, entity_id)]
            )
        prior = chain_head(entity_type, entity_id)
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
    """Walk the chain from its root by the links and recompute every hash.

    False when a row was altered or removed, when two rows chain to the same predecessor (a
    fork), or when a row is unreachable from the root. Event-time order plays no part."""
    rows = list(AuditEvent.objects.filter(entity_type=entity_type, entity_id=entity_id))
    by_prior: dict[str | None, list[AuditEvent]] = {}
    for row in rows:
        by_prior.setdefault(row.prior_hash, []).append(row)
    expected_prior: str | None = None
    visited = 0
    while True:
        successors = by_prior.get(expected_prior, [])
        if not successors:
            break
        if len(successors) != 1:
            return False
        row = successors[0]
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
        if row.hash != recomputed:
            return False
        expected_prior = row.hash
        visited += 1
    return visited == len(rows)
