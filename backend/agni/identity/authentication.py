"""DRF authentication: cookie session + per-request policy recheck (security s.3).

A session that fails the idle/absolute/epoch/active check is flushed and the request is
answered with SESSION_EXPIRED. CSRF for authenticated unsafe requests is enforced here; the
public unsafe login endpoints enforce it separately in `ApiView` (API s.2)."""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from agni.platform.clock import get_clock
from agni.platform.errors import SessionExpired

from .models import Principal
from .sessions import SessionInvalid, terminate_session, validate_session


class PrincipalSessionAuthentication(SessionAuthentication):
    def authenticate(self, request: Request) -> tuple[Principal, None] | None:
        user = getattr(request._request, "user", None)
        if user is None or not user.is_authenticated or not isinstance(user, Principal):
            return None
        try:
            validate_session(request._request, user, get_clock())
        except SessionInvalid as exc:
            terminate_session(request._request)
            raise SessionExpired(
                detail="Your session has expired; sign in again", extensions={"reason": exc.reason}
            ) from exc
        self.enforce_csrf(request)
        return user, None
