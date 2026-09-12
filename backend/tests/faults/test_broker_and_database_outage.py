"""Broker unavailable after the outbox commit; database unavailable before a command
(docs/08 s.6 rows 2-3, s.10 "stop the broker after an application is accepted")."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.db import OperationalError
from django.db.backends.utils import CursorWrapper
from django.test import Client

from agni.identity.models import Principal
from agni.platform import dispatch
from agni.platform.clock import FrozenClock
from agni.platform.models import CommandReceipt, LogicalJob, OutboxMessage, OutboxState
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture import
from tests.integration.test_submission import cmd

JSON = "application/json"
REASON = "Fault drill: synthetic demonstration data only, no legal effect."


@pytest.mark.django_db
def test_broker_outage_after_commit_keeps_intents_pending_and_republishes_once(
    visit: dict[str, Any],  # noqa: F811
    clock: FrozenClock,
) -> None:
    boss, app_id = visit["boss"], visit["app_id"]
    before = OutboxMessage.objects.count()
    # An accepted command while the broker is down: the receipt and the outbox row commit.
    detail = boss.get(f"/api/v1/applications/{app_id}")
    held = boss.post(
        f"/api/v1/applications/{app_id}/holds",
        data={"kind": "ADMINISTRATIVE", "reason": REASON, "affected_obligation_ids": []},
        content_type=JSON,
        headers=cmd(etag=detail["ETag"]),
    )
    assert held.status_code == 201, held.content
    new_rows = OutboxMessage.objects.count() - before
    assert new_rows >= 1
    pending_ids = set(
        OutboxMessage.objects.filter(state=OutboxState.PENDING).values_list("pk", flat=True)
    )
    assert pending_ids
    # Dispatcher pass with the broker failing: nothing lost, nothing marked dispatched.
    outage = dispatch.dispatch_pending(now=clock.now(), broker=dispatch.FailingBroker())
    assert outage.failed >= 1 and outage.published == 0
    still_pending = OutboxMessage.objects.filter(pk__in=pending_ids)
    assert all(row.state == OutboxState.PENDING for row in still_pending)
    assert all(row.dispatch_attempts == 1 for row in still_pending)
    fanout_jobs = LogicalJob.objects.filter(kind="notification.fanout").count()
    # Broker recovers: the same intents publish exactly once; the fan-out job ids are
    # deterministic so the earlier enqueue is reused, not duplicated.
    recovered = dispatch.dispatch_pending(now=clock.now(), broker=dispatch.NullBroker())
    assert recovered.published >= 1 and recovered.failed == 0
    assert all(
        row.state == OutboxState.DISPATCHED and row.dispatch_attempts == 2
        for row in OutboxMessage.objects.filter(pk__in=pending_ids)
    )
    assert LogicalJob.objects.filter(kind="notification.fanout").count() == fanout_jobs
    # A third pass has nothing to do.
    assert dispatch.dispatch_pending(now=clock.now(), broker=dispatch.NullBroker()).scanned == 0


@pytest.mark.django_db
def test_database_unavailable_is_503_without_a_false_receipt(
    visit: dict[str, Any],  # noqa: F811
    supervisor: Principal,
    signed_client: Callable[[Principal], Client],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boss, app_id = visit["boss"], visit["app_id"]
    detail = boss.get(f"/api/v1/applications/{app_id}")
    receipts_before = CommandReceipt.objects.count()
    original = CursorWrapper.execute
    # A browser-like client: the framework answers instead of re-raising into the test.
    browser = Client(enforce_csrf_checks=True, raise_request_exception=False)
    browser.cookies["sessionid"] = boss.cookies["sessionid"].value
    browser.defaults["HTTP_X_CSRFTOKEN"] = boss.defaults["HTTP_X_CSRFTOKEN"]
    browser.cookies["csrftoken"] = boss.cookies["csrftoken"].value

    def unavailable(self: CursorWrapper, sql: Any, params: Any = None) -> Any:
        raise OperationalError("connection to server was lost (fault drill)")

    monkeypatch.setattr(CursorWrapper, "execute", unavailable)
    try:
        read = browser.get(f"/api/v1/applications/{app_id}")
        command = browser.post(
            f"/api/v1/applications/{app_id}/holds",
            data={"kind": "ADMINISTRATIVE", "reason": REASON, "affected_obligation_ids": []},
            content_type=JSON,
            headers=cmd(etag=detail["ETag"]),
        )
    finally:
        monkeypatch.setattr(CursorWrapper, "execute", original)
    for response in (read, command):
        assert response.status_code == 503, response.content
        body = response.json()
        assert body["code"] == "DEPENDENCY_UNAVAILABLE" and body["retry_after_seconds"] == 30
        assert "Traceback" not in response.content.decode()
        assert response["Retry-After"] == "30"
    # Nothing was accepted: no receipt, no hold; the same key can be retried later.
    assert CommandReceipt.objects.count() == receipts_before
    after = boss.get(f"/api/v1/applications/{app_id}").json()["data"]
    assert after["on_hold"] is False
