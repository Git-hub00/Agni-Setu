"""Injected clock (engineering standards s.2; workflow s.8).

Business code never calls `datetime.now()` directly: it receives a `Clock`, so deterministic
tests can freeze or advance time and the demonstration clock can never leak into audit records.
All instants are timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall clock in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests: fixed until explicitly advanced."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at.astimezone(UTC)


def get_clock() -> Clock:
    """Resolve the configured clock (`AGNI_CLOCK` dotted path, default SystemClock)."""
    path = getattr(settings, "AGNI_CLOCK", "agni.platform.clock.SystemClock")
    factory = import_string(path)
    clock: Clock = factory()
    return clock
