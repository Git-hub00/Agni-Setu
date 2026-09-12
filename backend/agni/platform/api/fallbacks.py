"""Framework-level fallback responses (Django `handler400/403/404/500`). The API is JSON-only
and the SPA is served by nginx, so every fallback is an RFC 9457 problem with a request id and
no stack trace. `server_error` distinguishes a lost database (503 DEPENDENCY_UNAVAILABLE, docs/08
s.6 "Database unavailable: no false accepted receipt") from any other uncaught error (500)."""

from __future__ import annotations

import logging
import sys
from typing import Any

from django.db import InterfaceError, OperationalError
from django.http import HttpRequest, JsonResponse

from ..correlation import current_request_id
from ..errors import (
    DependencyUnavailable,
    DomainError,
    Forbidden,
    InternalError,
    MalformedRequest,
    ResourceNotFound,
)

logger = logging.getLogger("agni.api")
PROBLEM = "application/problem+json"


def _respond(error: DomainError) -> JsonResponse:
    body = error.to_problem(current_request_id())
    response = JsonResponse(body, status=error.status, content_type=PROBLEM)
    if error.retry_after_seconds is not None:
        response["Retry-After"] = str(error.retry_after_seconds)
    return response


def server_error(request: HttpRequest) -> JsonResponse:
    exc = sys.exc_info()[1]
    if isinstance(exc, OperationalError | InterfaceError):
        return _respond(
            DependencyUnavailable(
                "The service is temporarily unavailable; nothing was recorded. Retry the same "
                "command shortly.",
                retry_after_seconds=30,
            )
        )
    logger.exception("unhandled error outside the API layer request_id=%s", current_request_id())
    return _respond(InternalError())


def not_found(request: HttpRequest, exception: Any = None) -> JsonResponse:
    return _respond(ResourceNotFound())


def permission_denied(request: HttpRequest, exception: Any = None) -> JsonResponse:
    return _respond(Forbidden())


def bad_request(request: HttpRequest, exception: Any = None) -> JsonResponse:
    return _respond(MalformedRequest())
