#!/usr/bin/env bash
# Isolated restore rehearsal (docs/12 s.6): restore a backup archive into the SEPARATE database
# `agni_restore_drill` inside the local PostgreSQL container, run the read-only integrity report
# against it and drop the drill database. Never touches the live database.
# Thin wrapper: the implementation is scripts/ops/backup_restore.py.
#
#   scripts/ops/restore-check.sh evidence/backups/agni_<utc>.dump
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec uv run --directory "$REPO_ROOT/backend" python "$REPO_ROOT/scripts/ops/backup_restore.py" restore-check "$@"
