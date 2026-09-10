#!/usr/bin/env bash
# Shared helpers for scripts/dev/*.sh. Sourced, not executed.
# Resolves the repository root from the script location so every script works from any cwd.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_PROJECT="agni-dev"
COMPOSE_FILE="$REPO_ROOT/infra/compose/compose.dev.yml"
# Local secrets file (gitignored via `.env.*`). Named .env.local so tooling that guards `.env`
# for production secrets does not collide with the generated development file.
ENV_FILE="$REPO_ROOT/.env.local"
ENV_EXAMPLE="$REPO_ROOT/backend/.env.example"
IDENTITIES_FILE="$REPO_ROOT/infra/volumes/objectstore/s3-identities.json"

compose() {
  docker compose -p "$COMPOSE_PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

log()  { printf '\033[1;34m[agni]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[agni] WARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[agni] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Read a variable's value from the env file without exporting anything or echoing secrets.
env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | head -1
}

# Generate the repository-root .env from backend/.env.example: every <...> placeholder becomes an
# independent random secret, then the composite URLs are rebuilt from the discrete credentials so
# Compose services and the host-run Django agree. Never prints a secret.
generate_env_file() {
  [ -f "$ENV_EXAMPLE" ] || die "missing $ENV_EXAMPLE"
  local tmp; tmp="$(mktemp)"
  while IFS= read -r line || [ -n "$line" ]; do
    while [[ "$line" =~ \<[^\>]*\> ]]; do
      line="${line/"${BASH_REMATCH[0]}"/$(random_secret)}"
    done
    printf '%s\n' "$line" >> "$tmp"
  done < "$ENV_EXAMPLE"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true

  local pg_user pg_pass pg_db pg_port mq_user mq_pass mq_vhost vk_pass
  pg_user="$(env_value POSTGRES_USER)"; pg_pass="$(env_value POSTGRES_PASSWORD)"
  pg_db="$(env_value POSTGRES_DB)";     pg_port="$(env_value POSTGRES_HOST_PORT)"
  mq_user="$(env_value RABBITMQ_USER)"; mq_pass="$(env_value RABBITMQ_PASSWORD)"
  mq_vhost="$(env_value RABBITMQ_VHOST)"; vk_pass="$(env_value VALKEY_PASSWORD)"
  set_env_value DATABASE_URL "postgresql://${pg_user}:${pg_pass}@127.0.0.1:${pg_port:-55432}/${pg_db}"
  set_env_value CELERY_BROKER_URL "amqp://${mq_user}:${mq_pass}@127.0.0.1:5672/${mq_vhost}"
  set_env_value CACHE_URL "redis://:${vk_pass}@127.0.0.1:6379/0"
  log "generated $ENV_FILE with fresh random secrets (values not shown)"
}

set_env_value() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" 'BEGIN{done=0} index($0,k"=")==1 {print k"="v; done=1; next} {print} END{if(!done) print k"="v}' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# SeaweedFS S3 identities file (gitignored under infra/volumes/), rendered from the .env values.
render_objectstore_identities() {
  local access secret
  access="$(env_value OBJECT_ACCESS_KEY)"; secret="$(env_value OBJECT_SECRET_KEY)"
  [ -n "$access" ] && [ -n "$secret" ] || die "OBJECT_ACCESS_KEY/OBJECT_SECRET_KEY missing in .env"
  mkdir -p "$(dirname "$IDENTITIES_FILE")"
  cat > "$IDENTITIES_FILE" <<EOF
{
  "identities": [
    {
      "name": "agni-local",
      "credentials": [{"accessKey": "${access}", "secretKey": "${secret}"}],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
EOF
  chmod 600 "$IDENTITIES_FILE" 2>/dev/null || true
}

# Wait until every container of the project reports healthy (or running, when it has no
# healthcheck). Prints the failing service's recent logs on timeout.
wait_for_health() {
  local timeout="${1:-180}" elapsed=0 ids id name status pending
  while :; do
    pending=""
    ids="$(compose ps -q 2>/dev/null || true)"
    for id in $ids; do
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
      name="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")"
      case "$status" in
        healthy|running) ;;
        *) pending="$pending $name($status)" ;;
      esac
    done
    if [ -z "$pending" ] && [ -n "$ids" ]; then
      return 0
    fi
    if [ "$elapsed" -ge "$timeout" ]; then
      warn "timed out after ${timeout}s waiting for:$pending"
      for id in $ids; do
        status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
        name="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")"
        if [ "$status" != "healthy" ] && [ "$status" != "running" ]; then
          warn "--- last 20 log lines of $name ---"
          docker logs --tail 20 "$id" 2>&1 | sed 's/^/    /' || true
        fi
      done
      return 1
    fi
    sleep 3; elapsed=$((elapsed + 3))
  done
}
