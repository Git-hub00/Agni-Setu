"""Shared pytest fixtures.

Unit tests must not touch the database. Integration tests use the dedicated test database
that pytest-django creates from `TEST_DATABASE_NAME` (never the developer database).
"""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def anonymous_client() -> Client:
    return Client()
