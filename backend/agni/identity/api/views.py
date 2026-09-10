"""Identity endpoints API-001..007 (FR-01, FR-02)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.platform.api.views import ApiView, client_ip, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    DependencyUnavailable,
    DomainError,
    ValidationFailed,
    Violation,
)

from .. import oidc, otp
from ..authz import load_snapshot, principal_projection
from ..contacts import normalize_contact
from ..models import OtpPurpose, Principal
from ..sessions import establish_session, session_expires_at, terminate_session

logger = logging.getLogger("agni.identity")


def feature_gates() -> dict[str, Any]:
    return {
        "service_mode": settings.SERVICE_MODE,
        "demo_controls": bool(settings.ENABLE_DEMO_CONTROLS),
        "staff_oidc": bool(settings.OIDC_ISSUER),
    }


class CsrfBootstrapView(ApiView):
    """API-001: set the CSRF cookie and return the token; never authenticates."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        return ok({"csrf_token": get_token(request._request)}, request)


class OtpChallengeView(ApiView):
    """API-002: enumeration-safe challenge creation with anti-abuse limits."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def post(self, request: Request) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        channel = str(data.get("channel", "EMAIL")).upper()
        contact = str(data.get("contact", ""))
        started = otp.start_challenge(
            channel=channel,
            contact=contact,
            purpose=OtpPurpose.SIGN_IN,
            source_ip=client_ip(request),
            clock=get_clock(),
        )
        return ok(
            {
                "challenge_id": str(started.challenge_id),
                "masked_destination": started.masked_destination,
                "expires_at": started.expires_at.isoformat(),
                "resend_available_at": started.resend_available_at.isoformat(),
            },
            request,
            status=202,
        )


class OtpVerifyView(ApiView):
    """API-003: consume the single-use challenge and rotate the authenticated session."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def post(self, request: Request) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        challenge_id = str(data.get("challenge_id", ""))
        code = str(data.get("code", ""))
        contact_raw = data.get("contact")
        channel = str(data.get("channel", "EMAIL")).upper()
        if not challenge_id or not code:
            raise ValidationFailed(
                violations=[
                    Violation("/challenge_id", "required", "is required")
                    if not challenge_id
                    else Violation("/code", "required", "is required")
                ]
            )
        clock = get_clock()
        verified = otp.verify_challenge(challenge_id=challenge_id, code=code, clock=clock)
        now = clock.now()
        if (
            verified.challenge.purpose == OtpPurpose.SIGN_IN
            and isinstance(contact_raw, str)
            and contact_raw
        ):
            # Bind the encrypted plaintext only when it matches the challenged contact.
            normalized = normalize_contact(channel, contact_raw)
            if normalized.lookup_hmac == verified.challenge.contact_lookup_hmac:
                otp.record_verified_contact(verified.principal, normalized, now)
        expires = establish_session(request._request, verified.principal, method="otp", clock=clock)
        snapshot = load_snapshot(verified.principal, now)
        return ok(
            principal_projection(
                snapshot, session_expires_at=expires, feature_gates=feature_gates()
            ),
            request,
        )


class OidcStartView(ApiView):
    """API-004: server-side PKCE/state/nonce, redirect to the staff identity provider."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Any:
        if not settings.OIDC_ISSUER:
            raise ValidationFailed(detail="Staff sign-in is not configured")
        request._request.session["agni_oidc_next"] = oidc.safe_next(
            request.query_params.get("next")
        )
        redirect_uri = request.build_absolute_uri("/api/v1/auth/oidc/callback")
        try:
            return oidc.start(request._request, redirect_uri)
        except (requests.RequestException, OSError) as exc:
            # Discovery/JWKS fetch failed: the provider is down, not the user. Fail safely.
            logger.warning("staff identity provider unreachable: %s", type(exc).__name__)
            raise DependencyUnavailable("Staff identity provider is currently unavailable") from exc


class OidcCallbackView(ApiView):
    """API-005: validate the token, map issuer+subject to a provisioned staff principal."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Any:
        next_path = oidc.safe_next(request._request.session.pop("agni_oidc_next", None))
        try:
            identity = oidc.complete(request._request)
            principal = oidc.map_staff(identity)
        except DomainError as exc:
            logger.warning("staff sign-in refused code=%s", exc.code)
            return HttpResponseRedirect(f"/sign-in?error={exc.code.lower()}")
        except Exception:  # noqa: BLE001 - provider/validation failures are not user errors
            logger.exception("oidc callback failed")
            return HttpResponseRedirect("/sign-in?error=oidc_failed")
        establish_session(request._request, principal, method="oidc", clock=get_clock())
        return HttpResponseRedirect(next_path)


class LogoutView(ApiView):
    """API-006: flush the server session (CSRF enforced by ApiView)."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def post(self, request: Request) -> Response:
        terminate_session(request._request)
        return Response(status=204)


class MeView(ApiView):
    """API-007: identity, workspaces, scopes, capabilities, epoch and gates."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        clock = get_clock()
        principal = request.user
        if not isinstance(principal, Principal):
            raise AuthenticationRequired()
        snapshot = load_snapshot(principal, clock.now())
        expires = session_expires_at(request._request, clock)
        return ok(
            principal_projection(
                snapshot, session_expires_at=expires, feature_gates=feature_gates()
            ),
            request,
        )
