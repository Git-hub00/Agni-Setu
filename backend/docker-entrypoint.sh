#!/bin/sh
# Agni Setu API container entrypoint. Runs migrations only when explicitly requested
# (development default via Compose); production applies migrations as a deliberate release step
# (docs/12_DEPLOYMENT_AND_OPERATIONS.md s.5). Never prints environment values.
set -eu

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  echo "[entrypoint] applying migrations (RUN_MIGRATIONS_ON_START=true)"
  python manage.py migrate --noinput
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout 60 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
