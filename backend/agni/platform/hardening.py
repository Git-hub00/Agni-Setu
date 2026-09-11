"""Request guard and response security headers for the API (security s.4, s.9 "resource
exhaustion", s.10 "validate response headers").

- JSON request bodies are capped (`API_MAX_JSON_BODY_BYTES`) before any view runs; file bytes
  travel through the dedicated upload endpoint, which enforces the reservation size itself.
- Every API response carries a restrictive Content-Security-Policy (the API serves data, never
  documents to render), `frame-ancestors 'none'`, nosniff, a same-origin referrer policy and a
  locked-down Permissions-Policy. Authenticated responses default to `Cache-Control: no-store`
  so shared caches and the browser never keep scoped data.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .correlation import current_request_id
from .errors import MalformedRequest

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
UPLOAD_CONTENT_SUFFIX = "/content"


def _json_like(content_type: str) -> bool:
    media = content_type.split(";")[0].strip().lower()
    return media in ("application/json", "application/problem+json", "text/plain", "")


class HardeningMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        too_big = self._body_too_large(request)
        if too_big is not None:
            return too_big
        response = self.get_response(request)
        self._add_headers(request, response)
        return response

    def _body_too_large(self, request: HttpRequest) -> HttpResponse | None:
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if request.path.startswith("/api/v1/uploads/") and request.path.endswith(
            UPLOAD_CONTENT_SUFFIX
        ):
            return None  # file bytes: bounded by the reservation, not by this cap
        raw = request.META.get("CONTENT_LENGTH") or "0"
        try:
            length = int(raw)
        except ValueError:
            length = 0
        limit = int(getattr(settings, "API_MAX_JSON_BODY_BYTES", 1024 * 1024))
        if length <= limit:
            return None
        problem = MalformedRequest(
            f"Request body exceeds the {limit // 1024} KiB limit for API commands",
            extensions={"max_bytes": limit},
        ).to_problem(current_request_id())
        problem["status"] = 413
        response = JsonResponse(problem, status=413, content_type="application/problem+json")
        self._add_headers(request, response)
        return response

    @staticmethod
    def _add_headers(request: HttpRequest, response: HttpResponse) -> None:
        if not request.path.startswith("/api/"):
            return
        response.headers.setdefault("Content-Security-Policy", API_CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and "Cache-Control" not in response.headers:
            if _json_like(response.headers.get("Content-Type", "")):
                response.headers["Cache-Control"] = "private, no-store"
