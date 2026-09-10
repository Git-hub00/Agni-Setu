"""Production settings with fail-closed startup validation.

Architecture s.9 / build guide s.6 / document 19: a live process must refuse to start when
it references sample signing, console/demo OTP, unrestricted hosts or CORS, default secrets,
DEBUG or demo reset controls. Every problem found is reported together so an operator can
fix the configuration in one pass. Nothing here reads or prints secret values.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DATABASES, DEMO_PROVIDER_VALUES, SERVICE_MODE, env

DEBUG = False

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="")
# Empty strings from `ALLOWED_HOSTS=` must not count as a configured host.
ALLOWED_HOSTS = [h for h in env.list("ALLOWED_HOSTS", default=[]) if h]
CSRF_TRUSTED_ORIGINS = [o for o in env.list("CSRF_TRUSTED_ORIGINS", default=[]) if o]

# TLS is terminated by the approved reverse proxy (deployment s.2).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

OTP_PROVIDER = env.str("OTP_PROVIDER", default="")
NOTIFICATION_PROVIDER = env.str("NOTIFICATION_PROVIDER", default="")
SIGNING_PROVIDER = env.str("SIGNING_PROVIDER", default="")
ENABLE_DEMO_CONTROLS = env.bool("ENABLE_DEMO_CONTROLS", default=False)

_INSECURE_KEY_MARKERS = ("local-insecure", "test-only", "changeme", "change-me", "<generated")


def _startup_problems() -> list[str]:
    problems: list[str] = []

    if len(SECRET_KEY) < 50 or any(marker in SECRET_KEY for marker in _INSECURE_KEY_MARKERS):
        problems.append(
            "DJANGO_SECRET_KEY missing, shorter than 50 characters or a known placeholder"
        )

    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        problems.append("ALLOWED_HOSTS must list explicit hostnames (no wildcard)")

    if not CSRF_TRUSTED_ORIGINS or any(not o.startswith("https://") for o in CSRF_TRUSTED_ORIGINS):
        problems.append("CSRF_TRUSTED_ORIGINS must be non-empty and https-only")

    db = DATABASES["default"]
    if not db.get("NAME") or not db.get("USER") or not db.get("PASSWORD"):
        problems.append("DATABASE_URL must include database name, user and password")

    if SERVICE_MODE not in {"DEMO", "LIVE"}:
        problems.append("SERVICE_MODE must be DEMO or LIVE")

    if SERVICE_MODE == "LIVE":
        if ENABLE_DEMO_CONTROLS:
            problems.append(
                "ENABLE_DEMO_CONTROLS must be false in LIVE mode (no demo reset routes)"
            )
        for name, value in (
            ("OTP_PROVIDER", OTP_PROVIDER),
            ("NOTIFICATION_PROVIDER", NOTIFICATION_PROVIDER),
            ("SIGNING_PROVIDER", SIGNING_PROVIDER),
        ):
            if not value or value in DEMO_PROVIDER_VALUES:
                problems.append(
                    f"{name} must name an approved live adapter, not a demo/console sink"
                )

    return problems


_problems = _startup_problems()
if _problems:
    raise ImproperlyConfigured(
        "Refusing to start with unsafe production configuration:\n  - " + "\n  - ".join(_problems)
    )
