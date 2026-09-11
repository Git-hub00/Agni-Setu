"""Outbox dispatcher (docs/08 s.2). Publishes pending intents by creating the durable fan-out
job (database, always) and sending a best-effort wake-up through the broker port. The outbox
row survives broker acknowledgement; the fan-out job marks it COMPLETE. A broker outage leaves
rows PENDING with a growing attempt count - visible lag, no lost intent - and the next scan
republishes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from django.conf import settings
from django.db import transaction

from . import jobs
from .models import OutboxMessage, OutboxState

REPUBLISH_AFTER = timedelta(minutes=5)


class BrokerPublisher(Protocol):
    name: str

    def publish(self, *, routing_key: str, body: dict[str, Any]) -> None:
        """Send a wake-up. Raise on failure; the caller keeps the intent PENDING."""


class NullBroker:
    """No broker (tests / single-process): the worker polls the database anyway."""

    name = "null"

    def publish(self, *, routing_key: str, body: dict[str, Any]) -> None:
        return None


class AmqpBroker:
    """RabbitMQ wake-ups over kombu (part of the locked celery dependency)."""

    name = "amqp"

    def __init__(self, url: str) -> None:
        self._url = url

    def publish(self, *, routing_key: str, body: dict[str, Any]) -> None:
        from kombu import Connection

        with Connection(self._url, connect_timeout=5) as connection:
            queue = connection.SimpleQueue(routing_key)
            try:
                queue.put(body)
            finally:
                queue.close()


class FailingBroker:
    """Test double: every publish fails (simulated outage)."""

    name = "failing"

    def publish(self, *, routing_key: str, body: dict[str, Any]) -> None:
        raise ConnectionError("broker unavailable")


def get_broker() -> BrokerPublisher:
    provider = getattr(settings, "BROKER_PROVIDER", "null")
    if provider == "amqp":
        return AmqpBroker(settings.CELERY_BROKER_URL)
    return NullBroker()


@dataclass
class DispatchReport:
    scanned: int = 0
    published: int = 0
    failed: int = 0


def dispatch_pending(
    *, now: datetime, limit: int = 100, broker: BrokerPublisher | None = None
) -> DispatchReport:
    """One dispatcher pass. Rows are claimed FOR UPDATE SKIP LOCKED so parallel dispatchers do
    not double-handle; re-publishing an already DISPATCHED row after the republish window is
    allowed and harmless (the fan-out job id is deterministic)."""
    from agni.notifications.application.fanout import FANOUT_JOB, fanout_job_id

    broker = broker or get_broker()
    report = DispatchReport()
    stale = now - REPUBLISH_AFTER
    with transaction.atomic():
        rows = list(
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .filter(available_at__lte=now)
            .filter(models_q_pending() | models_q_stale_dispatched(stale))
            .order_by("available_at", "created_at")[:limit]
        )
        for row in rows:
            report.scanned += 1
            jobs.enqueue_job(
                kind=FANOUT_JOB,
                aggregate_ref={"outbox_id": str(row.pk), "event_type": row.event_type},
                run_at=now,
                logical_action_id=fanout_job_id(row.logical_action_id),
            )
            row.dispatch_attempts += 1
            row.last_dispatched_at = now
            try:
                broker.publish(
                    routing_key="agni.wakeups",
                    body={
                        "logical_action_id": str(row.logical_action_id),
                        "event_type": row.event_type,
                    },
                )
                row.state = OutboxState.DISPATCHED
                report.published += 1
            except Exception:  # noqa: BLE001 - any broker failure keeps the intent pending
                report.failed += 1
            row.save(update_fields=["dispatch_attempts", "last_dispatched_at", "state"])
    return report


def models_q_pending() -> Any:
    from django.db.models import Q

    return Q(state=OutboxState.PENDING)


def models_q_stale_dispatched(stale: datetime) -> Any:
    from django.db.models import Q

    return Q(state=OutboxState.DISPATCHED, last_dispatched_at__lt=stale)


def outbox_lag(now: datetime) -> dict[str, Any]:
    """Operations summary (UI-20): pending count and the age of the oldest undispatched row."""
    pending = OutboxMessage.objects.filter(state=OutboxState.PENDING).order_by("available_at")
    oldest = pending.first()
    return {
        "pending": pending.count(),
        "dispatched_incomplete": OutboxMessage.objects.filter(state=OutboxState.DISPATCHED).count(),
        "oldest_pending_seconds": int((now - oldest.available_at).total_seconds()) if oldest else 0,
    }


_wake_hook: Callable[[], None] | None = None


def install_wake_hook(hook: Callable[[], None]) -> None:
    global _wake_hook  # noqa: PLW0603 - process-wide hook registration
    _wake_hook = hook


def wake_id() -> uuid.UUID:
    return uuid.uuid4()
