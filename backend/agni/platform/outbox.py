"""Transactional outbox writes (docs/08 s.2). Publishing happens outside the transaction in
B10's dispatcher; `notify_dispatcher` is the on_commit wake-up hook (never the only trigger)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from .models import OutboxMessage


def enqueue_intent(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: Mapping[str, Any],
    available_at: datetime,
    logical_action_id: UUID | None = None,
    payload_version: int = 1,
) -> OutboxMessage:
    """Persist one intent. `logical_action_id` is the stable identity a retry must reuse."""
    return OutboxMessage.objects.create(
        logical_action_id=logical_action_id or uuid4(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload_version=payload_version,
        payload=dict(payload),
        available_at=available_at,
    )


def notify_dispatcher() -> None:
    """Best-effort wake-up after commit. The periodic scan is the recovery mechanism."""
    # B10 wires the dispatcher; keeping the hook here fixes the call site in the kernel.
    return None


def schedule_dispatcher_wakeup() -> None:
    transaction.on_commit(notify_dispatcher)
