from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from agni.platform.clock import FrozenClock, SystemClock, get_clock
from agni.platform.correlation import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    current_request_id,
    parse_request_id,
)


def test_frozen_clock_is_deterministic_and_advances() -> None:
    clock = FrozenClock(datetime(2026, 9, 10, 9, 0, tzinfo=UTC))
    assert clock.now() == clock.now()
    clock.advance(timedelta(minutes=240))
    assert clock.now() == datetime(2026, 9, 10, 13, 0, tzinfo=UTC)


def test_frozen_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 9, 10, 9, 0))


def test_system_clock_is_utc_aware() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_get_clock_reads_settings(settings: object) -> None:
    settings.AGNI_CLOCK = "agni.platform.clock.SystemClock"  # type: ignore[attr-defined]
    assert isinstance(get_clock(), SystemClock)


def test_middleware_mints_or_echoes_request_id() -> None:
    seen: list[UUID | None] = []

    def view(request: HttpRequest) -> HttpResponse:
        seen.append(current_request_id())
        return HttpResponse("ok")

    middleware = RequestIdMiddleware(view)
    factory = RequestFactory()

    response = middleware(factory.get("/"))
    minted = UUID(response[REQUEST_ID_HEADER])
    assert seen[-1] == minted

    supplied = uuid4()
    response = middleware(factory.get("/", headers={REQUEST_ID_HEADER: str(supplied)}))
    assert response[REQUEST_ID_HEADER] == str(supplied) and seen[-1] == supplied

    response = middleware(factory.get("/", headers={REQUEST_ID_HEADER: "not-a-uuid"}))
    assert response[REQUEST_ID_HEADER] != "not-a-uuid"
    assert current_request_id() is None  # reset after the request


def test_parse_request_id() -> None:
    assert parse_request_id(None) is None
    assert parse_request_id("junk") is None
    value = uuid4()
    assert parse_request_id(f" {value} ") == value
