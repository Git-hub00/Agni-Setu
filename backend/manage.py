#!/usr/bin/env python
"""Django management entry point for the Agni Setu backend."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - environment failure, not app logic
        raise ImportError(
            "Django is not importable. Run `uv sync --frozen` inside backend/ and invoke "
            "this script with `uv run python manage.py ...`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
