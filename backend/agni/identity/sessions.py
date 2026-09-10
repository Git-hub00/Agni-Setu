"""Server session establishment and lifetime policy (security s.3; ADR-04).

Session data holds only facts needed to enforce policy: authentication time, last activity,
the authorization epoch seen at login and the login method. Tokens are never stored in the
browser. Successful authentication rotates the session key and the CSRF token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpRequest
from django.middleware.csrf import rotate_token

from agni.platform.clock import Clock

from .models import Principal

KEY_AUTH_TIME = "agni_auth_time"
KEY_LAST_SEEN = "agni_last_seen"
KEY_EPOCH = "agni_authz_epoch"
KEY_METHOD = "agni_auth_method"


@dataclass(frozen=True)
class SessionPolicy:
    idle: timedelta = timedelta(minutes=30)
    absolute: timedelta = timedelta(hours=8)
    step_up: timedelta = timedelta(minutes=15)


def policy_from_settings() -> SessionPolicy:
    return SessionPolicy(
        idle=timedelta(seconds=int(getattr(settings, "SESSION_COOKIE_AGE", 1800))),
        absolute=timedelta(seconds=int(getattr(settings, "AGNI_SESSION_ABSOLUTE_SECONDS", 28800))),
        step_up=timedelta(seconds=int(getattr(settings, "AGNI_STEP_UP_SECONDS", 900))),
    )


def establish_session(
    request: HttpRequest, principal: Principal, *, method: str, clock: Clock
) -> datetime:
    """Log the principal in, rotate session id + CSRF token, stamp policy facts. Returns the
    absolute expiry instant."""
    now = clock.now()
    django_login(request, principal, backend="agni.identity.backends.PrincipalBackend")
    request.session.cycle_key()
    rotate_token(request)
    request.session[KEY_AUTH_TIME] = now.isoformat()
    request.session[KEY_LAST_SEEN] = now.isoformat()
    request.session[KEY_EPOCH] = principal.authz_epoch
    request.session[KEY_METHOD] = method
    policy = policy_from_settings()
    return now + min(policy.absolute, policy.idle)


def terminate_session(request: HttpRequest) -> None:
    django_logout(request)
    rotate_token(request)


def session_expires_at(request: HttpRequest, clock: Clock) -> datetime | None:
    policy = policy_from_settings()
    auth_time = _read_time(request, KEY_AUTH_TIME)
    last_seen = _read_time(request, KEY_LAST_SEEN) or clock.now()
    if auth_time is None:
        return None
    return min(auth_time + policy.absolute, last_seen + policy.idle)


class SessionInvalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_session(request: HttpRequest, principal: Principal, clock: Clock) -> None:
    """Idle/absolute lifetime and authorization-epoch recheck on every authenticated request.
    Raises SessionInvalid; callers flush the session and answer SESSION_EXPIRED."""
    policy = policy_from_settings()
    now = clock.now()
    auth_time = _read_time(request, KEY_AUTH_TIME)
    last_seen = _read_time(request, KEY_LAST_SEEN)
    if auth_time is None or last_seen is None:
        raise SessionInvalid("session lacks policy facts")
    if now - auth_time > policy.absolute:
        raise SessionInvalid("absolute lifetime exceeded")
    if now - last_seen > policy.idle:
        raise SessionInvalid("idle timeout")
    if not principal.is_active:
        raise SessionInvalid("principal disabled")
    if request.session.get(KEY_EPOCH) != principal.authz_epoch:
        raise SessionInvalid("authorization epoch changed")
    request.session[KEY_LAST_SEEN] = now.isoformat()


def recently_authenticated(request: HttpRequest, clock: Clock) -> bool:
    auth_time = _read_time(request, KEY_AUTH_TIME)
    return auth_time is not None and clock.now() - auth_time <= policy_from_settings().step_up


def _read_time(request: HttpRequest, key: str) -> datetime | None:
    raw = request.session.get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
