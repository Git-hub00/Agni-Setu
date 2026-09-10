"""Health probes (API-121 liveness, API-122 readiness).

Liveness proves the process answers. Readiness proves the database is reachable and the
mandatory startup configuration is present. Neither response includes environment values,
credentials or hostnames. Operational degradation of optional services (broker, cache,
object store) is reported separately by the operations module, not here.
"""

from __future__ import annotations

from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

_REQUIRED_SETTINGS = ("SECRET_KEY", "SERVICE_MODE", "OTP_PROVIDER", "SIGNING_PROVIDER")


@require_GET
def live(_request: HttpRequest) -> HttpResponse:
    return JsonResponse({"status": "ok"})


def _database_ready() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return bool(cursor.fetchone() == (1,))
    except DatabaseError:
        return False


def _schema_ready() -> bool:
    """Deployment s.3: readiness includes migration/schema compatibility.

    Unapplied migrations mean this code version must not serve traffic yet.
    """
    try:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return not executor.migration_plan(targets)
    except DatabaseError:
        return False


def _configuration_ready() -> bool:
    return all(getattr(settings, name, None) for name in _REQUIRED_SETTINGS) and (
        settings.SERVICE_MODE in {"DEMO", "LIVE"}
    )


@require_GET
def ready(_request: HttpRequest) -> HttpResponse:
    database_ok = _database_ready()
    checks = {
        "database": database_ok,
        "schema": database_ok and _schema_ready(),
        "configuration": _configuration_ready(),
    }
    ready_state = all(checks.values())
    body = {
        "status": "ready" if ready_state else "not_ready",
        "checks": {name: ("pass" if ok else "fail") for name, ok in checks.items()},
        "service_mode": settings.SERVICE_MODE,
    }
    return JsonResponse(body, status=200 if ready_state else 503)
