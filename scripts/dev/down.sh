#!/usr/bin/env bash
# Stop the local stack safely. Volumes are preserved by default (build guide s.5: never use
# `down -v` as a routine restart). Destroying volumes requires the explicit flag AND typing the
# project name.
#   scripts/dev/down.sh                     -> stop containers, keep everything
#   scripts/dev/down.sh --remove            -> remove containers and network, keep volumes
#   scripts/dev/down.sh --destroy-volumes   -> remove containers AND delete data volumes (confirm)

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

[ -f "$ENV_FILE" ] || die "no .env.local found; nothing to stop (or the stack was started differently)"

case "${1:-}" in
  "")
    compose --profile full --profile app stop
    log "containers stopped; data volumes kept. Use --remove or --destroy-volumes for more."
    ;;
  --remove)
    compose --profile full --profile app down --remove-orphans
    log "containers and network removed; data volumes kept."
    ;;
  --destroy-volumes)
    warn "this deletes ALL local data volumes of project $COMPOSE_PROJECT (database, broker, objects, identity)."
    printf 'Type the project name (%s) to confirm: ' "$COMPOSE_PROJECT"
    read -r answer
    [ "$answer" = "$COMPOSE_PROJECT" ] || die "confirmation did not match; nothing deleted"
    compose --profile full --profile app down --volumes --remove-orphans
    log "project $COMPOSE_PROJECT removed including volumes."
    ;;
  *)
    die "unknown option '$1' (use no option, --remove, or --destroy-volumes)"
    ;;
esac
