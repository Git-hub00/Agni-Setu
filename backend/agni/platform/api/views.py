"""API base view: CSRF enforced on every unsafe request (also unauthenticated ones, API s.2),
request-id envelope helpers, and the actor context for commands."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from rest_framework import exceptions as drf
from rest_framework.authentication import CSRFCheck
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agni.platform.commands import ActorContext
from agni.platform.correlation import current_request_id
from agni.platform.errors import CsrfFailed

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def request_id_of(request: Request) -> UUID:
    return current_request_id() or getattr(request._request, "agni_request_id", None) or uuid4()


def envelope(data: Any, request: Request) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": str(request_id_of(request))}}


def ok(
    data: Any, request: Request, status: int = 200, headers: dict[str, str] | None = None
) -> Response:
    response = Response(envelope(data, request), status=status)
    for key, value in (headers or {}).items():
        response[key] = value
    return response


def client_ip(request: Request) -> str:
    """Source address for abuse controls. X-Forwarded-For is honoured only when the deployment
    declares a trusted reverse proxy in front (containers behind nginx)."""
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", ""))
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return str(request.META.get("REMOTE_ADDR", "unknown"))[:64]


class ApiView(APIView):
    """All project endpoints extend this. Unsafe methods require a valid CSRF token even when
    no session exists (login/OTP endpoints are not exempt)."""

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method in UNSAFE_METHODS:
            self._enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def _enforce_csrf(self, request: Request) -> None:
        def noop_response(_request: HttpRequest) -> HttpResponse:  # pragma: no cover
            return HttpResponse()

        check = CSRFCheck(noop_response)
        check.process_request(request._request)
        reason = check.process_view(request._request, noop_response, (), {})
        if reason:
            # DRF's CSRFCheck returns the rejection reason string instead of a response.
            raise CsrfFailed(detail=f"CSRF failed: {reason}")

    def actor_context(self, request: Request) -> ActorContext:
        user = request.user
        if not getattr(user, "is_authenticated", False) or user.pk is None:
            raise drf.NotAuthenticated()
        return ActorContext(principal_id=UUID(str(user.pk)), request_id=request_id_of(request))

    def idempotency_key(self, request: Request) -> str | None:
        key = request.headers.get("Idempotency-Key")
        return key.strip() if key else None

    def expected_version(self, request: Request) -> int | None:
        """Parse `If-Match: "<type>:<uuid>:v<n>"` (API s.3) or a bare integer."""
        raw = request.headers.get("If-Match")
        if not raw:
            return None
        token = raw.strip().strip('"')
        tail = token.rsplit(":v", 1)[-1] if ":v" in token else token
        try:
            return int(tail)
        except ValueError:
            return None
