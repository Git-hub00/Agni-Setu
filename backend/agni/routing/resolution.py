"""Routing resolution (FR-07, data model `routing_entry`): one unambiguous target for the
matching dimensions, otherwise a typed exception the case module records as an owned routing
exception. Pure over already-loaded entries; the caller supplies the artifact's rows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .models import RoutingEntry


class RoutingFailure(StrEnum):
    NO_MATCH = "NO_MATCH"
    MULTIPLE_MATCH = "MULTIPLE_MATCH"
    INACTIVE_TARGET = "INACTIVE_TARGET"


@dataclass(frozen=True)
class RouteResult:
    target_jurisdiction_id: UUID
    target_queue_id: UUID
    entry_id: UUID
    priority: int


class RoutingUnresolvedError(Exception):
    def __init__(self, code: RoutingFailure, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def resolve_route(
    entries: Iterable[RoutingEntry], *, ward_key: str, category_key: str | None, at: datetime
) -> RouteResult:
    """Category-specific rows beat wildcard rows; among candidates the highest priority wins;
    equal-priority ties are an exception, never a coin toss."""
    candidates: list[RoutingEntry] = []
    for entry in entries:
        if entry.ward_key != ward_key:
            continue
        if entry.category_key not in (None, "", category_key):
            continue
        if entry.effective_from and entry.effective_from > at:
            continue
        if entry.effective_until and entry.effective_until <= at:
            continue
        candidates.append(entry)
    if not candidates:
        raise RoutingUnresolvedError(
            RoutingFailure.NO_MATCH, f"No routing entry for ward {ward_key}"
        )
    specific = [c for c in candidates if c.category_key]
    pool = specific or candidates
    best = max(pool, key=lambda e: e.priority)
    ties = [c for c in pool if c.priority == best.priority]
    if len(ties) > 1:
        raise RoutingUnresolvedError(
            RoutingFailure.MULTIPLE_MATCH,
            f"{len(ties)} routing entries match ward {ward_key} with equal priority",
        )
    if not best.target_queue.active:
        raise RoutingUnresolvedError(
            RoutingFailure.INACTIVE_TARGET, "Routing target queue is inactive"
        )
    return RouteResult(
        target_jurisdiction_id=best.target_jurisdiction_id,
        target_queue_id=best.target_queue_id,
        entry_id=best.pk,
        priority=best.priority,
    )
