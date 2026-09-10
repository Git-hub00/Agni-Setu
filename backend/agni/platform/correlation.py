"""Request correlation (engineering standards s.4).

One request ID propagates through command receipt, events, jobs, provider attempts and audit.
Set by `RequestIdMiddleware` for HTTP requests and explicitly by workers/schedulers.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[UUID | None] = ContextVar("agni_request_id", default=None)


def current_request_id() -> UUID | None:
    return _request_id.get()


def bind_request_id(value: UUID) -> Token[UUID | None]:
    return _request_id.set(value)


def reset_request_id(token: Token[UUID | None]) -> None:
    _request_id.reset(token)


def parse_request_id(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


class RequestIdMiddleware:
    """Accept a well-formed inbound X-Request-ID or mint one; echo it on the response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = parse_request_id(request.headers.get(REQUEST_ID_HEADER)) or uuid4()
        request.agni_request_id = request_id  # type: ignore[attr-defined]
        token = bind_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response[REQUEST_ID_HEADER] = str(request_id)
        return response
