#!/usr/bin/env bash
# Start the local Agni Setu stack (docs/10_BUILD_GUIDE.md s.7).
#   scripts/dev/up.sh            -> minimal infrastructure (postgres, rabbitmq, valkey, objectstore)
#   scripts/dev/up.sh full       -> + keycloak, clamav
#   scripts/dev/up.sh app        -> minimal + containerized api and web
#   scripts/dev/up.sh all        -> everything
# Never deletes volumes. Generates a gitignored .env with random secrets on first run.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

profile="${1:-minimal}"
profile_args=()
case "$profile" in
  minimal) ;;
  full) profile_args=(--profile full) ;;
  app) profile_args=(--profile app) ;;
  all) profile_args=(--profile full --profile app) ;;
  *) die "unknown profile '$profile' (use minimal|full|app|all)" ;;
esac

command -v docker >/dev/null 2>&1 || die "docker not found"
docker info >/dev/null 2>&1 || die "Docker daemon is not reachable (start Docker Desktop)"

if [ ! -f "$ENV_FILE" ]; then
  generate_env_file
else
  log "using existing $ENV_FILE"
  if grep -q '<[^>]*>' "$ENV_FILE"; then
    die ".env.local still contains <placeholder> values; fix them or delete .env.local to regenerate"
  fi
fi
render_objectstore_identities

log "starting profile '$profile' (project $COMPOSE_PROJECT)"
compose "${profile_args[@]}" up -d --remove-orphans

if wait_for_health 240; then
  log "all services healthy"
else
  die "some services did not become healthy; see logs above (scripts/dev/down.sh stops the stack)"
fi

pg_port="$(env_value POSTGRES_HOST_PORT)"; web_port="$(env_value WEB_HOST_PORT)"
cat <<EOF

  PostgreSQL   127.0.0.1:${pg_port:-55432}   (db $(env_value POSTGRES_DB), user $(env_value POSTGRES_USER))
  RabbitMQ     amqp://127.0.0.1:5672   management http://127.0.0.1:15672 (user $(env_value RABBITMQ_USER))
  Valkey       127.0.0.1:6379 (password required)
  Object store http://127.0.0.1:8333 (S3, bucket $(env_value OBJECT_BUCKET))
EOF
case "$profile" in
  full|all) echo "  Keycloak     http://localhost:8080 (admin $(env_value KC_BOOTSTRAP_ADMIN_USERNAME)); ClamAV on the private network" ;;
esac
case "$profile" in
  app|all) echo "  Web          http://localhost:${web_port:-5173}    API http://127.0.0.1:8000/api/v1/health/ready" ;;
esac
echo
echo "  Secrets live in .env.local (never commit it). Host-run API: cd backend && uv run python manage.py runserver 127.0.0.1:8000"
