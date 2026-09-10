"""Deterministic lock ordering (architecture s.7): principal authorization fences in sorted UUID
order, then the service activation fence when needed, then the aggregate, then children in
sorted UUID order. Long transactions, user interaction and network calls never hold these."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from agni.identity.models import Principal, PrincipalFence


def sorted_unique(ids: Iterable[UUID]) -> list[UUID]:
    return sorted(set(ids))


def lock_principal_fences(principal_ids: Iterable[UUID]) -> Sequence[PrincipalFence]:
    """Lock the fence rows FOR UPDATE in sorted order and return them."""
    ordered = sorted_unique(principal_ids)
    fences = list(
        PrincipalFence.objects.select_for_update()
        .filter(principal_id__in=ordered)
        .order_by("principal_id")
    )
    if len(fences) != len(ordered):
        missing = set(ordered) - {f.principal_id for f in fences}
        raise PrincipalFence.DoesNotExist(f"fence missing for principals {sorted(missing)}")
    return fences


def load_locked_principal(principal_id: UUID) -> Principal:
    """Lock the actor's fence, then load the current principal facts (active flag, epoch)."""
    lock_principal_fences([principal_id])
    return Principal.objects.get(pk=principal_id)
