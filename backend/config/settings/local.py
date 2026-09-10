"""Local developer settings.

Never used in production. Defaults here exist only so that `manage.py check` and local
development work before a `.env` is generated; they are visibly insecure and rejected by
the production settings module.
"""

import environ

from .base import *  # noqa: F403
from .base import env

environ.Env.read_env(str(BASE_DIR / ".env"))  # noqa: F405 - optional; ignored when absent

DEBUG = True
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
SECRET_KEY = env.str(
    "DJANGO_SECRET_KEY",
    default="local-insecure-development-key-do-not-use-outside-localhost",  # noqa: S105
)
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:5173"])
ENABLE_DEMO_CONTROLS = env.bool("ENABLE_DEMO_CONTROLS", default=True)
