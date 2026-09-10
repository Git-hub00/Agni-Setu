# syntax=docker/dockerfile:1.7
# Agni Setu API image (docs/12_DEPLOYMENT_AND_OPERATIONS.md s.2): multi-stage, non-root,
# pinned base by digest (infra/images.lock.json "python-base"), frozen dependencies only.
# Build context: backend/  (docker build -f infra/containers/api.Dockerfile backend/)

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------------------------
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime

# WeasyPrint runtime libraries (document rendering), fonts, and curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        fontconfig fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system agni \
    && useradd --system --gid agni --home-dir /app --shell /usr/sbin/nologin agni

WORKDIR /app
COPY --from=builder --chown=agni:agni /app/.venv /app/.venv
COPY --chown=agni:agni . .
RUN chmod +x /app/docker-entrypoint.sh && mkdir -p /app/staticfiles && chown agni:agni /app/staticfiles

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

USER agni
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/live || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
