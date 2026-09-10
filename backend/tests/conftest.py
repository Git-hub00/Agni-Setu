"""Shared pytest fixtures.

Unit tests must not touch the database. Integration tests use the dedicated test database
that pytest-django creates from `TEST_DATABASE_NAME` (never the developer database).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from django.test import Client

from agni.platform.clock import FrozenClock

FIXED_NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def anonymous_client() -> Client:
    return Client()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(FIXED_NOW)


@pytest.fixture
def request_id() -> UUID:
    return uuid4()
