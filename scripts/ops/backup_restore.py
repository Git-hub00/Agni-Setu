"""Backup and isolated restore rehearsal for the LOCAL Compose database (docs/12 s.6; build
guide s.9). Python implementation behind `scripts/ops/backup.sh` and `scripts/ops/restore-check.sh`
so it runs identically from Git Bash, PowerShell or CI. Reads credentials from the repository
`.env.local` and never prints them.

  backup            -> pg_dump -Fc of the live database to evidence/backups/agni_<utc>.dump
  restore-check DUMP -> restore DUMP into the isolated database `agni_restore_drill` inside the
                       PostgreSQL container, run `manage.py restore_integrity_report --json`
                       against it from the api container, record restore/report durations,
                       drop the drill database. Exit code follows the report (1 = check failed).

The only database this tool ever drops or creates is `agni_restore_drill`; the live database is
read (backup) and never written.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env.local"
POSTGRES = "agni-dev-postgres-1"
API = "agni-dev-api-1"
DRILL_DB = "agni_restore_drill"


def env_value(key: str) -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :].strip()
    raise SystemExit(f"{key} missing in .env.local")


def log(message: str) -> None:
    print(f"[ops] {message}", flush=True)


def docker(args: list[str], *, stdin: bytes | None = None) -> bytes:
    command = ["docker", *args]
    result = subprocess.run(command, input=stdin, capture_output=True, check=False)
    if result.returncode != 0:
        # Never echo the command (it may carry -e PGPASSWORD=...); stderr is safe.
        raise SystemExit(f"docker step failed: {result.stderr.decode(errors='replace')[-600:]}")
    return result.stdout


def backup(target: Path | None) -> Path:
    user, database, password = env_value("POSTGRES_USER"), env_value("POSTGRES_DB"), env_value("POSTGRES_PASSWORD")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = target or ROOT / "evidence" / "backups" / f"agni_{stamp}.dump"
    out.parent.mkdir(parents=True, exist_ok=True)
    log(f"pg_dump of database '{database}' (custom format) -> {out.relative_to(ROOT)}")
    started = time.monotonic()
    data = docker(["exec", "-e", f"PGPASSWORD={password}", POSTGRES, "pg_dump", "-U", user, "-d", database, "-Fc", "--no-owner", "--no-acl"])
    out.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    log(f"backup complete: {len(data)} bytes in {time.monotonic() - started:.1f}s, sha256 {digest}")
    return out


def psql(password: str, user: str, sql: str) -> None:
    docker(["exec", "-e", f"PGPASSWORD={password}", POSTGRES, "psql", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", "postgres", "-qtA", "-c", sql])


def restore_check(archive: Path) -> int:
    user, live_db, password = env_value("POSTGRES_USER"), env_value("POSTGRES_DB"), env_value("POSTGRES_PASSWORD")
    if DRILL_DB == live_db:
        raise SystemExit("drill database must differ from the live database")
    data = archive.read_bytes()
    log(f"cutoff: archive {archive.name} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]}...)")
    started = time.monotonic()
    log(f"recreating isolated target database '{DRILL_DB}' (live '{live_db}' untouched)")
    psql(password, user, f"DROP DATABASE IF EXISTS {DRILL_DB}")
    psql(password, user, f"CREATE DATABASE {DRILL_DB} OWNER {user}")
    log(f"pg_restore into '{DRILL_DB}'")
    docker(["exec", "-i", "-e", f"PGPASSWORD={password}", POSTGRES, "pg_restore", "-U", user, "-d", DRILL_DB, "--no-owner", "--no-acl"], stdin=data)
    restored = time.monotonic() - started
    log(f"restore finished in {restored:.1f}s; running the integrity report against '{DRILL_DB}'")
    result = subprocess.run(
        ["docker", "exec", "-e", "DATABASE_URL=" + "".join(["postgresql://", user, ":", password, "@postgres:5432/", DRILL_DB]), "-e", "RUN_MIGRATIONS_ON_START=false", API, "python", "manage.py", "restore_integrity_report", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    total = time.monotonic() - started
    report_text = result.stdout.strip()
    try:
        report = json.loads(report_text)
        log(f"report status {report.get('status')} counts={report.get('counts')} audit_chains={report.get('audit_chains')} artifacts={[a.get('status') for a in report.get('certificate_artifacts', [])]} documents={report.get('document_versions')}")
        if report.get("failures"):
            log(f"failures: {report['failures']}")
    except json.JSONDecodeError:
        log(f"report output was not JSON: {report_text[-400:]} {result.stderr[-400:]}")
    log(f"restore drill total {total:.1f}s (restore {restored:.1f}s + report {total - restored:.1f}s); report exit {result.returncode}")
    log(f"dropping the drill database '{DRILL_DB}'")
    psql(password, user, f"DROP DATABASE IF EXISTS {DRILL_DB}")
    return result.returncode


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("backup", "restore-check"):
        print(__doc__)
        return 2
    if argv[0] == "backup":
        target = Path(argv[1]) if len(argv) > 1 else None
        print(backup(target))
        return 0
    if len(argv) < 2:
        raise SystemExit("usage: backup_restore.py restore-check <backup.dump>")
    archive = Path(argv[1])
    if not archive.is_file():
        archive = ROOT / argv[1]  # relative to the repository root when run from backend/
    if not archive.is_file():
        raise SystemExit(f"backup archive not found: {argv[1]}")
    return restore_check(archive.resolve())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
