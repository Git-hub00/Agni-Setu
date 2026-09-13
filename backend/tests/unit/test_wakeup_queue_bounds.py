"""DEF-011: the outbox wake-up queue must be bounded, because nothing consumes it yet.

Production-readiness regression #1 found `agni.wakeups` holding 105 durable messages with zero
consumers after two hours of the dev stack. The AMQP publisher now declares the queue with a
message TTL, a maximum length (drop-head) and stamps each message with an expiry, so a broker
without consumers never accumulates wake-ups. kombu is replaced by a recording double; the live
broker behaviour is covered by the operations drills.
"""

from __future__ import annotations

from typing import Any

import pytest

from agni.platform import dispatch


class _RecordingQueue:
    def __init__(self, name: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.kwargs = kwargs
        self.puts: list[tuple[Any, dict[str, Any]]] = []
        self.closed = False

    def put(self, body: Any, **kwargs: Any) -> None:
        self.puts.append((body, kwargs))

    def close(self) -> None:
        self.closed = True


class _RecordingConnection:
    instances: list[_RecordingConnection] = []

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.kwargs = kwargs
        self.queues: list[_RecordingQueue] = []
        _RecordingConnection.instances.append(self)

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def SimpleQueue(self, name: str, **kwargs: Any) -> _RecordingQueue:  # noqa: N802 - kombu API
        queue = _RecordingQueue(name, kwargs)
        self.queues.append(queue)
        return queue


@pytest.fixture
def recording_kombu(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingConnection]:
    import kombu

    _RecordingConnection.instances.clear()
    monkeypatch.setattr(kombu, "Connection", _RecordingConnection)
    return _RecordingConnection


def test_wakeup_queue_is_declared_with_ttl_and_length_bounds(
    recording_kombu: type[_RecordingConnection],
) -> None:
    dispatch.AmqpBroker("amqp://guest:guest@broker/agni").publish(
        routing_key=dispatch.WAKEUP_QUEUE, body={"logical_action_id": "x", "event_type": "y"}
    )

    (connection,) = recording_kombu.instances
    assert connection.kwargs == {"connect_timeout": 5}
    (queue,) = connection.queues
    assert queue.name == dispatch.WAKEUP_QUEUE
    arguments = queue.kwargs["queue_args"]
    assert arguments["x-message-ttl"] == dispatch.WAKEUP_TTL_SECONDS * 1000
    assert arguments["x-max-length"] == dispatch.WAKEUP_MAX_LENGTH
    assert arguments["x-overflow"] == "drop-head"
    assert queue.closed is True


def test_each_wakeup_message_carries_its_own_expiry(
    recording_kombu: type[_RecordingConnection],
) -> None:
    body = {"logical_action_id": "x", "event_type": "y"}
    dispatch.AmqpBroker("amqp://guest:guest@broker/agni").publish(
        routing_key=dispatch.WAKEUP_QUEUE, body=body
    )

    (queue,) = recording_kombu.instances[0].queues
    assert queue.puts == [(body, {"expiration": dispatch.WAKEUP_TTL_SECONDS})]


def test_wakeup_bounds_are_short_and_versioned() -> None:
    # A wake-up older than the poll interval is noise; the cap keeps a dead broker consumer from
    # ever costing more than a bounded number of small messages.
    assert 0 < dispatch.WAKEUP_TTL_SECONDS <= 300
    assert 0 < dispatch.WAKEUP_MAX_LENGTH <= 10_000
    # The legacy unbounded queue must not be reused: RabbitMQ rejects inequivalent redeclaration.
    assert dispatch.WAKEUP_QUEUE != "agni.wakeups"
