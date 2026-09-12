"""Session middleware that keeps the outage contract (docs/08 s.6 "database unavailable").

Django's `SessionMiddleware` saves the session row at the end of every request; the database
backend converts any `DatabaseError` during that UPDATE into `UpdateError`, which the middleware
re-raises as `SessionInterrupted` (a `SuspiciousOperation`, answered 400 "bad request"). When
the *connection* was lost - PostgreSQL restarting, a network partition - that blames the
request for an infrastructure failure and breaks the uniform 503 DEPENDENCY_UNAVAILABLE answer
the rest of the API gives (observed live on 2026-09-12 during a PostgreSQL crash: the OTP
verify call answered 400 while the challenge call answered 503).

`ResilientSessionMiddleware` inspects the exception chain: a connection-level error
(`OperationalError` / `InterfaceError`) becomes the 503 problem with `Retry-After` and no
implied receipt; any other interruption (a genuine concurrent logout deleting the row) keeps
Django's 400 path.
"""

from __future__ import annotations

from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import InterfaceError, OperationalError
from django.http import HttpRequest, HttpResponse, JsonResponse

from .correlation import current_request_id
from .errors import DependencyUnavailable


def connection_level_failure(exc: BaseException) -> bool:
    """True when an OperationalError / InterfaceError sits anywhere in the exception chain."""
    seen: BaseException | None = exc
    hops = 0
    while seen is not None and hops < 8:
        if isinstance(seen, OperationalError | InterfaceError):
            return True
        seen = seen.__cause__ or seen.__context__
        hops += 1
    return False


def unavailable_response() -> JsonResponse:
    problem = DependencyUnavailable(
        "The service is temporarily unavailable; nothing was recorded. Retry the same "
        "command shortly.",
        retry_after_seconds=30,
    ).to_problem(current_request_id())
    response = JsonResponse(problem, status=503, content_type="application/problem+json")
    response["Retry-After"] = "30"
    return response


class ResilientSessionMiddleware(SessionMiddleware):
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        try:
            return super().process_response(request, response)
        except SessionInterrupted as exc:
            if connection_level_failure(exc):
                return unavailable_response()
            raise
