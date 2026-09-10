#!/usr/bin/env bash
# Environment doctor (docs/10_BUILD_GUIDE.md s.7): toolchain versions against the lock, lockfiles,
# ports, Docker, .env completeness and mode separation. Redacts secrets. Nonzero exit on hard
# failures; warnings do not fail.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

failures=0
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; failures=$((failures + 1)); }
note() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }

expect_uv="0.11.28"; expect_pnpm="12.3.4"; expect_node_major="24"; expect_python="3.12"

echo "Toolchain"
if v="$(git --version 2>/dev/null)"; then ok "$v"; else bad "git missing"; fi
if v="$(docker --version 2>/dev/null)"; then ok "$v"; else bad "docker missing"; fi
if v="$(docker compose version 2>/dev/null)"; then ok "$v"; else bad "docker compose v2 missing"; fi
if v="$(uv --version 2>/dev/null)"; then
  case "$v" in *"$expect_uv"*) ok "$v" ;; *) note "$v (locked toolchain used uv $expect_uv)" ;; esac
else bad "uv missing (https://docs.astral.sh/uv/)"; fi
if v="$(python --version 2>/dev/null || python3 --version 2>/dev/null)"; then
  case "$v" in *"$expect_python"*) ok "$v" ;; *) bad "$v (need Python $expect_python.x)" ;; esac
else bad "python missing"; fi
if v="$(node --version 2>/dev/null)"; then
  case "$v" in v${expect_node_major}.*) ok "node $v" ;; *) bad "node $v (need $expect_node_major.x LTS)" ;; esac
else bad "node missing"; fi
if v="$(corepack --version 2>/dev/null)"; then ok "corepack $v (pnpm $expect_pnpm is pinned in web/package.json)"; else bad "corepack missing (ships with Node 24)"; fi

echo "Lockfiles"
for f in backend/uv.lock web/pnpm-lock.yaml infra/images.lock.json; do
  [ -f "$REPO_ROOT/$f" ] && ok "$f" || bad "$f missing"
done

echo "Docker daemon"
if docker info >/dev/null 2>&1; then
  ok "daemon reachable ($(docker info --format '{{.OSType}}/{{.Architecture}}, {{.NCPU}} CPU, {{.MemTotal}} bytes'))"
  mem="$(docker info --format '{{.MemTotal}}')"
  if [ "${mem:-0}" -lt 6000000000 ]; then note "Docker VM has < 6 GB RAM: use the minimal profile; 'full' (Keycloak+ClamAV) may not fit"; fi
else
  bad "Docker daemon not reachable (start Docker Desktop)"
fi

echo "Ports (127.0.0.1)"
pg_port="$( [ -f "$ENV_FILE" ] && env_value POSTGRES_HOST_PORT || echo 55432 )"
for p in "${pg_port:-55432}" 5672 15672 6379 8333 8080 5173 8000; do
  if (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then
    if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$p->"; then ok "$p in use by a Docker container (this stack?)"; else note "$p already in use by another process (override the host port in .env)"; fi
  else ok "$p free"; fi
done 3>&-

echo "Environment file"
if [ -f "$ENV_FILE" ]; then
  ok ".env.local present"
  missing=""
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    if ! grep -q "^${key}=" "$ENV_FILE"; then missing="$missing $key"; fi
  done < "$ENV_EXAMPLE"
  [ -z "$missing" ] && ok "all variables from backend/.env.example are present" || bad "missing variables:$missing"
  if grep -q '<[^>]*>' "$ENV_FILE"; then bad "placeholders remain in: $(grep -o '^[A-Z_]*=<' "$ENV_FILE" | tr -d '=<' | tr '\n' ' ')"; else ok "no <placeholder> values remain"; fi
  mode="$(env_value SERVICE_MODE)"; appenv="$(env_value APP_ENV)"
  if [ "$mode" = "LIVE" ]; then
    for k in OTP_PROVIDER NOTIFICATION_PROVIDER SIGNING_PROVIDER; do
      case "$(env_value $k)" in demo_sink|demo_watermark|console|"") bad "SERVICE_MODE=LIVE but $k is a demo sink" ;; esac
    done
    [ "$(env_value ENABLE_DEMO_CONTROLS)" = "true" ] && bad "SERVICE_MODE=LIVE with ENABLE_DEMO_CONTROLS=true"
    [ "$(env_value DJANGO_SETTINGS_MODULE)" = "config.settings.production" ] || bad "LIVE mode must use config.settings.production"
  else
    ok "mode separation: APP_ENV=${appenv:-?} SERVICE_MODE=${mode:-?} (demo providers allowed)"
  fi
else
  note ".env.local not found - scripts/dev/up.sh will generate it"
fi

echo
if [ "$failures" -eq 0 ]; then log "doctor: no hard failures"; else die "doctor: $failures hard failure(s)"; fi
