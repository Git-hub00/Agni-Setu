"""OPS-1189 / G-06 - the configured statement timeout reaches the PostgreSQL session, a query
that exceeds it fails as a database error, and the API boundary reports that failure as the
uniform 503 DEPENDENCY_UNAVAILABLE problem (never a 500, never a hung worker)."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import OperationalError, connection, transaction

from agni.platform.api.exceptions import problem_exception_handler


@pytest.mark.django_db
def test_configured_statement_timeout_is_applied_to_the_session() -> None:
    expected_ms = int(settings.DB_STATEMENT_TIMEOUT_MS)
    assert expected_ms > 0, "the test settings inherit the request-path bound"
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    assert row is not None
    value = str(row[0])
    # PostgreSQL renders the value with a unit ("30s") or in milliseconds ("30000ms").
    assert value in {f"{expected_ms // 1000}s", f"{expected_ms}ms", str(expected_ms)}


@pytest.mark.django_db
def test_runaway_statement_is_cancelled_and_reported_as_unavailable() -> None:
    with pytest.raises(OperationalError) as excinfo, transaction.atomic(), connection.cursor() as c:
        c.execute("SET LOCAL statement_timeout = 100")
        c.execute("SELECT pg_sleep(2)")
    assert "statement timeout" in str(excinfo.value).lower()
    response = problem_exception_handler(excinfo.value, {})
    assert response.status_code == 503
    assert response.data["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response["Retry-After"] == "30"
