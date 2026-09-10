#!/usr/bin/env bash
# Full verification gate (docs/10_BUILD_GUIDE.md s.11). Stops at the first failure. Works from any
# cwd. Never prints secrets. Integration tests need DATABASE_URL to reach a PostgreSQL server
# (scripts/dev/up.sh provides one on 127.0.0.1:55432); pass --unit-only to skip them.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

unit_only=false
[ "${1:-}" = "--unit-only" ] && unit_only=true

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "backend: frozen sync";          uv sync --frozen --directory backend
step "backend: ruff lint";            uv run --directory backend ruff check .
step "backend: ruff format";          uv run --directory backend ruff format --check .
step "backend: mypy";                 uv run --directory backend mypy config agni tests
step "backend: django check";         uv run --directory backend python manage.py check
step "backend: migration drift";      uv run --directory backend python manage.py makemigrations --check --dry-run
step "backend: unit tests";           uv run --directory backend pytest tests/unit -q
if [ "$unit_only" = false ]; then
  if [ -n "${DATABASE_URL:-}" ] || { [ -f "$REPO_ROOT/.env.local" ] && grep -q '^DATABASE_URL=' "$REPO_ROOT/.env.local"; }; then
    step "backend: integration tests (real PostgreSQL)"
    if [ -z "${DATABASE_URL:-}" ]; then
      DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "$REPO_ROOT/.env.local" | head -1)"; export DATABASE_URL
    fi
    uv run --directory backend pytest tests/integration -q
  else
    step "backend: integration tests SKIPPED (no DATABASE_URL and no .env.local; run scripts/dev/up.sh first)"
  fi
fi
step "backend: dependency audit";     uv run --directory backend pip-audit --progress-spinner off

step "web: frozen install";           corepack pnpm install --dir web --frozen-lockfile
step "web: lint";                     corepack pnpm --dir web lint
step "web: typecheck";                corepack pnpm --dir web typecheck
step "web: unit tests";               corepack pnpm --dir web test --run
step "web: build";                    corepack pnpm --dir web build
step "web: dependency audit";         corepack pnpm --dir web audit --audit-level low

step "compose: configuration (all profiles)"
tmp_env="$(mktemp)"; trap 'rm -f "$tmp_env"' EXIT
sed -e 's/<[^>]*>/verify-placeholder/g' backend/.env.example > "$tmp_env"
docker compose -p agni-verify --env-file "$tmp_env" -f infra/compose/compose.dev.yml --profile full --profile app config -q

printf '\n\033[1;32mALL GATES PASSED\033[0m\n'
