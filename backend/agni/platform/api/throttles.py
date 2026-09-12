"""Per-principal request throttles for the costly endpoints (security s.9 "resource
exhaustion"; G-05): case search/list, upload reservations and export requests.

The OTP and public-verification routes keep their own fail-closed limiters; everything else
was unbounded for a signed-in principal. `FailClosedScopedRateThrottle` is DRF's scoped
throttle with two changes: the rate is read when the request arrives (so deployment settings
and test overrides apply without restarting), and an outage of the rate-limit store answers
503 DEPENDENCY_UNAVAILABLE (invariant 27: security storage failures fail closed) instead of
either letting the request through or surfacing a 500.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..errors import DependencyUnavailable


class FailClosedScopedRateThrottle(ScopedRateThrottle):
    def get_rate(self) -> str | None:
        scope = self.scope
        if scope is None:
            return None
        rates = api_settings.DEFAULT_THROTTLE_RATES
        try:
            return str(rates[scope])
        except KeyError as exc:
            raise ImproperlyConfigured(f"No default throttle rate set for '{scope}'") from exc

    def allow_request(self, request: Request, view: APIView) -> bool:
        try:
            return bool(super().allow_request(request, view))
        except Exception as exc:  # store outage (connection refused, timeout, protocol error)
            raise DependencyUnavailable(
                "The rate-limit store is unavailable; the request was not processed. "
                "Retry shortly.",
                retry_after_seconds=30,
            ) from exc
