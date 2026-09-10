"""Settings for automated tests. Uses a dedicated test database, never the developer's
default database (AGENTS.md). Requires DATABASE_URL like the other environments."""

from pathlib import Path

import environ

# Developer convenience: pick up DATABASE_URL/TEST_DATABASE_NAME from the generated local env
# file so integration tests reach the Compose PostgreSQL. Must run BEFORE base.py computes
# DATABASES. Real environment variables always win (CI sets them explicitly).
environ.Env.read_env(str(Path(__file__).resolve().parents[3] / ".env.local"))

from .base import *  # noqa: E402, F403
from .base import env  # noqa: E402

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-for-any-deployed-environment"  # noqa: S105
OTP_PEPPER = "test-only-otp-pepper-0123456789abcdef0123456789"  # noqa: S105
CONTACT_LOOKUP_KEY = "test-only-contact-lookup-key-0123456789abcdef"  # noqa: S105
DATA_ENCRYPTION_KEY = "test-only-data-encryption-key-0123456789abcdef"  # noqa: S105
# Hermetic tests use the in-memory store; the fail-closed path is tested by faulting it.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
ENABLE_DEMO_CONTROLS = True
OIDC_ISSUER = "http://localhost:8080/realms/agni-dev"
ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]
DATABASES["default"]["TEST"] = {"NAME": env.str("TEST_DATABASE_NAME", default="agni_test")}  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
