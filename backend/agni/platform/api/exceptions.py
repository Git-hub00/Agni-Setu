"""DRF exception handler: one HTTP boundary translating typed domain errors and framework
exceptions into RFC 9457 problem details (docs/06 s.5, docs/08 s.7, engineering s.4)."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response

from agni.platform.correlation import current_request_id
from agni.platform.errors import (
    AuthenticationRequired,
    CsrfFailed,
    DomainError,
    Forbidden,
    InternalError,
    MalformedRequest,
    RateLimited,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)

logger = logging.getLogger("agni.api")

PROBLEM_CONTENT_TYPE = "application/problem+json"


def _violations_from_drf(detail: Any, pointer: str = "") -> list[Violation]:
    violations: list[Violation] = []
    if isinstance(detail, dict):
        for key, value in detail.items():
            violations.extend(_violations_from_drf(value, f"{pointer}/{key}"))
    elif isinstance(detail, list):
        for index, value in enumerate(detail):
            if isinstance(value, dict | list):
                violations.extend(_violations_from_drf(value, f"{pointer}/{index}"))
            else:
                violations.append(
                    Violation(pointer or "/", getattr(value, "code", "invalid"), str(value))
                )
    else:
        violations.append(
            Violation(pointer or "/", getattr(detail, "code", "invalid"), str(detail))
        )
    return violations


def _translate(exc: Exception) -> DomainError:
    if isinstance(exc, DomainError):
        return exc
    if isinstance(exc, drf.NotAuthenticated | drf.AuthenticationFailed):
        return AuthenticationRequired()
    if isinstance(exc, drf.PermissionDenied):
        if "CSRF" in str(exc.detail):
            return CsrfFailed()
        return Forbidden()
    if isinstance(exc, DjangoPermissionDenied):
        return Forbidden()
    if isinstance(exc, drf.NotFound | Http404):
        return ResourceNotFound()
    if isinstance(exc, drf.ValidationError):
        return ValidationFailed(violations=_violations_from_drf(exc.detail))
    if isinstance(exc, drf.ParseError | drf.UnsupportedMediaType | drf.NotAcceptable):
        return MalformedRequest(str(exc.detail))
    if isinstance(exc, drf.MethodNotAllowed):
        return MalformedRequest(str(exc.detail), extensions={"status_override": 405})
    if isinstance(exc, drf.Throttled):
        wait_raw = getattr(exc, "wait", None)
        wait = int(wait_raw) if wait_raw else None
        return RateLimited(retry_after_seconds=wait)
    return InternalError()


def problem_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    error = _translate(exc)
    request_id = current_request_id()
    if isinstance(error, InternalError):
        logger.exception("unhandled API error request_id=%s", request_id)
    body = error.to_problem(request_id)
    status = int(body.pop("status_override", error.status))
    body["status"] = status
    response = Response(body, status=status, content_type=PROBLEM_CONTENT_TYPE)
    if error.retry_after_seconds is not None:
        response["Retry-After"] = str(error.retry_after_seconds)
    return response
