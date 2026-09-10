"""Shared Django settings for every environment.

Environment-specific modules (local/test/production) import from here and override.
No secret has a default in this module; environment modules decide what is acceptable
for their environment (docs/10_BUILD_GUIDE.md s.6, docs/07_SECURITY_PRIVACY_AND_ACCESS.md).

B00 scope: enough configuration for `manage.py check` to pass against the locked
dependency set. Business modules, Celery, storage and identity adapters arrive in B01+.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

APP_ENV = env.str("APP_ENV", default="local")
# DEMO or LIVE. Checked at startup and on live activation (architecture s.9, document 19).
SERVICE_MODE = env.str("SERVICE_MODE", default="DEMO")

# Provider adapters. The defaults are the safe local sinks from build guide s.6; the
# production settings module refuses to start a LIVE service with any of them.
OTP_PROVIDER = env.str("OTP_PROVIDER", default="demo_sink")
NOTIFICATION_PROVIDER = env.str("NOTIFICATION_PROVIDER", default="demo_sink")
SIGNING_PROVIDER = env.str("SIGNING_PROVIDER", default="demo_watermark")
SCANNER_PROVIDER = env.str("SCANNER_PROVIDER", default="clamav")
ENABLE_DEMO_CONTROLS = env.bool("ENABLE_DEMO_CONTROLS", default=False)

DEMO_PROVIDER_VALUES = frozenset({"demo_sink", "demo_watermark", "console"})

DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    # Agni Setu modules (architecture s.4). Order: platform kernel, identity (custom user model
    # before anything that references it), master data, then case aggregates.
    "agni.platform",
    "agni.identity",
    "agni.policies",
    "agni.routing",
    "agni.cases",
]

# Custom principal is the user model from the first migration (data model s.8).
AUTH_USER_MODEL = "identity.Principal"

# Injected clock; tests override with agni.platform.clock.FrozenClock via fixtures.
AGNI_CLOCK = env.str("AGNI_CLOCK", default="agni.platform.clock.SystemClock")

MIDDLEWARE = [
    "agni.platform.correlation.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# PostgreSQL is the only supported database (ADR-02). There is deliberately no SQLite
# fallback. The default below carries NO credentials: it lets `manage.py check` run before
# a `.env` exists, while any real connection requires DATABASE_URL from the environment.
# The production settings module (B01) rejects a missing or credential-less DATABASE_URL.
DATABASES = {
    "default": env.db_url("DATABASE_URL", default="postgresql://127.0.0.1:5432/agni_dev"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Database-backed sessions; no browser token storage (ADR-04).
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[])

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "agni.platform.api.exceptions.problem_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Agni Setu API",
    "DESCRIPTION": (
        "Fire-safety certificate case management. Contracts: docs/06_API_AND_EVENT_CONTRACTS.md"
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}
