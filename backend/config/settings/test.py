"""Settings for automated tests. Uses a dedicated test database, never the developer's
default database (AGENTS.md). Requires DATABASE_URL like the other environments."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-for-any-deployed-environment"  # noqa: S105
ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]
DATABASES["default"]["TEST"] = {"NAME": env.str("TEST_DATABASE_NAME", default="agni_test")}  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
