"""ASGI entry point (not used by the initial Gunicorn/WSGI deployment; kept for tooling)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

application = get_asgi_application()
