"""Staff OIDC via Authlib (security s.3; API-004/005). Authorization-code flow with PKCE
(S256), state and nonce handled server-side by Authlib; ID token validated against the
issuer's JWKS. Identity is issuer+subject; only a previously provisioned staff principal with
that exact mapping may sign in - group/email claims never create powers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.http import HttpRequest

from agni.platform.errors import AuthorityRevoked, Forbidden

from .models import Principal, PrincipalKind

_oauth: OAuth | None = None


def _client() -> Any:
    global _oauth
    if _oauth is None:
        _oauth = OAuth()
        # The issuer is the canonical (browser-facing) URL that appears in the `iss` claim. In
        # containers the backchannel (metadata, token, JWKS) may need a different reachable
        # host; Keycloak's dynamic backchannel keeps `issuer` canonical while advertising
        # container-reachable endpoints (build guide s.5). Issuer validation is never disabled.
        metadata_url = settings.OIDC_METADATA_URL or (
            f"{settings.OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"
        )
        _oauth.register(
            name="staff",
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET or None,
            server_metadata_url=metadata_url,
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )
    return _oauth.staff


def reset_client() -> None:
    """Test hook."""
    global _oauth
    _oauth = None


def safe_next(raw: str | None, default: str = "/") -> str:
    """Only relative, same-origin paths are honoured as return routes (UI-02)."""
    if not raw:
        return default
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not raw.startswith("/") or raw.startswith("//"):
        return default
    return raw


def start(request: HttpRequest, redirect_uri: str) -> Any:
    return _client().authorize_redirect(request, redirect_uri)


@dataclass(frozen=True)
class StaffIdentity:
    issuer: str
    subject: str
    display_name: str


def complete(request: HttpRequest) -> StaffIdentity:
    token = _client().authorize_access_token(request)
    claims = token.get("userinfo") or {}
    issuer = str(claims.get("iss") or settings.OIDC_ISSUER)
    subject = str(claims.get("sub") or "")
    if not subject:
        raise Forbidden("Identity provider returned no subject")
    display_name = str(claims.get("name") or claims.get("preferred_username") or subject)
    return StaffIdentity(issuer=issuer, subject=subject, display_name=display_name)


def map_staff(identity: StaffIdentity) -> Principal:
    """Resolve an approved staff mapping. Unknown or disabled identities are refused; nothing
    is auto-provisioned (FR-02)."""
    principal = Principal.objects.filter(
        external_issuer=identity.issuer, external_subject=identity.subject, kind=PrincipalKind.STAFF
    ).first()
    if principal is None:
        raise Forbidden("This staff identity has not been provisioned")
    if not principal.is_active:
        raise AuthorityRevoked("This staff account is disabled")
    return principal
