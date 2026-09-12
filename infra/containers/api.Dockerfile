# syntax=docker/dockerfile:1.7
# Agni Setu API image (docs/12_DEPLOYMENT_AND_OPERATIONS.md s.2): multi-stage, non-root,
# pinned base by digest (infra/images.lock.json "python-base"), frozen dependencies only.
# Build context: backend/  (docker build -f infra/containers/api.Dockerfile backend/)

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder

# uv binary pinned by index digest (infra/images.lock.json "uv-distribution", resolved at B18).
COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------------------------
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime

# Distribution security updates on top of the pinned base, WeasyPrint runtime libraries (document
# rendering) and fonts. No curl: the health probe uses the interpreter that is already present
# (the B18 scan attributed 8 unfixed HIGH advisories to curl/libcurl alone).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system agni \
    && useradd --system --gid agni --home-dir /app --shell /usr/sbin/nologin agni

WORKDIR /app
COPY --from=builder --chown=agni:agni /app/.venv /app/.venv
COPY --chown=agni:agni . .
RUN chmod +x /app/docker-entrypoint.sh && mkdir -p /app/staticfiles && chown agni:agni /app/staticfiles

# The runtime writes nothing under /app: bytecode is precompiled, fontconfig / WeasyPrint caches go
# to XDG_CACHE_HOME and gunicorn's heartbeat files to TMPDIR, so the container runs with a
# read-only root filesystem plus a tmpfs on /tmp (infra/containers/production/compose.prod.yml).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache \
    TMPDIR=/tmp \
    DJANGO_SETTINGS_MODULE=config.settings.production

USER agni
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
