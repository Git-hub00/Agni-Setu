"""Django auth backend that only resolves principals for sessions. It never authenticates
credentials itself (OTP and OIDC services do) and grants no Django permissions."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import BaseBackend
from django.http import HttpRequest

from .models import Principal


class PrincipalBackend(BaseBackend):
    def authenticate(self, request: HttpRequest | None, **credentials: Any) -> Principal | None:
        return None

    def get_user(self, user_id: Any) -> Principal | None:
        try:
            return Principal.objects.get(pk=user_id)
        except (Principal.DoesNotExist, ValueError):
            return None
