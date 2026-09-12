#!/usr/bin/env bash
# Logical PostgreSQL backup of the LOCAL Compose database (docs/12 s.6; build guide s.9).
# Thin wrapper: the implementation is scripts/ops/backup_restore.py (same behaviour from Git
# Bash, PowerShell or CI). Writes evidence/backups/agni_<utc>.dump; never prints credentials.
#
#   scripts/ops/backup.sh                -> evidence/backups/agni_<utc>.dump
#   scripts/ops/backup.sh /path/out.dump -> explicit target file
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec uv run --directory "$REPO_ROOT/backend" python "$REPO_ROOT/scripts/ops/backup_restore.py" backup "$@"
