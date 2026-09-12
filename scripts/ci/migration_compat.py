"""Migration compatibility check (docs/12 s.5: "test migrations against representative
previous-version data"; expand-contract).

Proves that the CURRENT tree's migrations apply cleanly on top of a database that was migrated by
a PREVIOUS release, and that the previous release's code can still start against the NEW schema
(forward-compatible rollback: application rollback without a schema downgrade).

  1. create an isolated database `agni_migcheck` (dropped at the end; never the live database)
  2. check out BASE_REF into a temporary git worktree, `uv sync --frozen` there, `migrate`
  3. (optional) seed representative data with the previous release's `seed_demo --require-demo`
  4. current tree: `migrate` (upgrade path), `migrate --check`, `makemigrations --check`
  5. previous tree against the upgraded schema: `manage.py check` + a read of every model table
     (`restore_integrity_report`-style count) to show the old code still starts and reads
  6. record the plan (`migrate --plan` from the base) as the migration plan for the release

Usage (repository root):
  uv run --directory backend python ../scripts/ci/migration_compat.py --base <git-ref> [--seed]
  DATABASE_URL (or .env.local) must point at a PostgreSQL server whose user may CREATE DATABASE.
Exit code: 0 compatible, 1 incompatible or a step failed. Never prints credentials.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
CHECK_DB = "agni_migcheck"


def log(message: str) -> None:
    print(f"[migcheck] {message}", flush=True)


def local_env_values() -> dict[str, str]:
    """Key/value pairs of the repository-root .env.local (values are never printed)."""
    env_file = ROOT / ".env.local"
    values: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "") or local_env_values().get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set and .env.local has none")
    return url


def with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def redacted(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "?"
    return f"{parts.scheme}://***@{host}:{parts.port or 5432}{parts.path}"


def run(
    args: list[str], *, cwd: Path, env: dict[str, str], label: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    elapsed = time.monotonic() - started
    status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
    log(f"{label}: {status} ({elapsed:.1f}s)")
    if result.returncode != 0:
        sys.stdout.write(result.stdout[-3000:])
        sys.stderr.write(result.stderr[-3000:])
        if check:
            raise SystemExit(f"step failed: {label}")
    return result


def admin_sql(url: str, sql: str, env: dict[str, str]) -> None:
    """Run one statement against the maintenance database using the backend's psycopg."""
    code = (
        "import sys, psycopg\n"
        "url, sql = sys.argv[1], sys.argv[2]\n"
        "with psycopg.connect(url, autocommit=True) as conn:\n"
        "    conn.execute(sql)\n"
    )
    run(
        [
            "uv",
            "run",
            "--directory",
            str(ROOT / "backend"),
            "python",
            "-c",
            code,
            with_database(url, "postgres"),
            sql,
        ],
        cwd=ROOT,
        env=env,
        label=f"admin: {sql.split()[0]} {sql.split()[1]} {CHECK_DB}",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base", required=True, help="git ref of the previous release (tag or commit)"
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="seed the demo baseline with the previous release before upgrading",
    )
    parser.add_argument("--keep-worktree", action="store_true")
    options = parser.parse_args(argv)

    base_url = database_url()
    check_url = with_database(base_url, CHECK_DB)
    if urlsplit(base_url).path.strip("/") == CHECK_DB:
        raise SystemExit("DATABASE_URL must not already point at the check database")
    # The previous release is checked out into a worktree without the gitignored .env.local, so
    # its settings (OIDC issuer, object store, secrets) are passed through the environment; the
    # process environment wins over the file, and the check database wins over both.
    env = local_env_values()
    env.update(
        {k: v for k, v in os.environ.items() if k not in {"DJANGO_SETTINGS_MODULE", "VIRTUAL_ENV"}}
    )
    env.update(
        {
            "DATABASE_URL": check_url,
            "DJANGO_SETTINGS_MODULE": "config.settings.local",
            "SERVICE_MODE": "DEMO",
            "APP_ENV": "local",
        }
    )
    env.setdefault("PYTHONIOENCODING", "utf-8")
    log(f"check database {redacted(check_url)} (isolated; dropped at the end)")

    base_sha = subprocess.run(
        ["git", "rev-parse", "--verify", options.base + "^{commit}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    log(
        f"previous release {options.base} = {base_sha[:12]}; current HEAD = {head_sha[:12]} (+ working tree)"
    )

    worktree = Path(tempfile.mkdtemp(prefix="agni-migcheck-")) / "prev"
    failures: list[str] = []
    try:
        run(
            ["git", "worktree", "add", "--detach", str(worktree), base_sha],
            cwd=ROOT,
            env=env,
            label="git worktree add (previous release)",
        )
        prev_backend = worktree / "backend"
        cur_backend = ROOT / "backend"

        admin_sql(base_url, f"DROP DATABASE IF EXISTS {CHECK_DB}", env)
        admin_sql(base_url, f"CREATE DATABASE {CHECK_DB}", env)

        run(
            ["uv", "sync", "--frozen", "--directory", str(prev_backend)],
            cwd=worktree,
            env=env,
            label="previous release: uv sync --frozen",
        )
        run(
            [
                "uv",
                "run",
                "--directory",
                str(prev_backend),
                "python",
                "manage.py",
                "migrate",
                "--noinput",
            ],
            cwd=prev_backend,
            env=env,
            label="previous release: migrate (baseline schema)",
        )
        if options.seed:
            run(
                [
                    "uv",
                    "run",
                    "--directory",
                    str(prev_backend),
                    "python",
                    "manage.py",
                    "seed_demo",
                    "--scenario",
                    "baseline",
                    "--require-demo",
                ],
                cwd=prev_backend,
                env=env,
                label="previous release: seed_demo (representative data)",
            )

        plan = run(
            [
                "uv",
                "run",
                "--directory",
                str(cur_backend),
                "python",
                "manage.py",
                "migrate",
                "--plan",
            ],
            cwd=cur_backend,
            env=env,
            label="current: migrate --plan (the release migration plan)",
        )
        planned = [line for line in plan.stdout.splitlines() if line.startswith(("    ", "  "))]
        log(f"migration plan from the previous schema: {len(planned)} operation line(s)")
        sys.stdout.write(plan.stdout)

        run(
            [
                "uv",
                "run",
                "--directory",
                str(cur_backend),
                "python",
                "manage.py",
                "migrate",
                "--noinput",
            ],
            cwd=cur_backend,
            env=env,
            label="current: migrate (upgrade path)",
        )
        run(
            [
                "uv",
                "run",
                "--directory",
                str(cur_backend),
                "python",
                "manage.py",
                "migrate",
                "--check",
            ],
            cwd=cur_backend,
            env=env,
            label="current: migrate --check (nothing pending)",
        )
        run(
            [
                "uv",
                "run",
                "--directory",
                str(cur_backend),
                "python",
                "manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
            ],
            cwd=cur_backend,
            env=env,
            label="current: makemigrations --check (no drift)",
        )
        report = run(
            [
                "uv",
                "run",
                "--directory",
                str(cur_backend),
                "python",
                "manage.py",
                "restore_integrity_report",
                "--json",
            ],
            cwd=cur_backend,
            env=env,
            label="current: integrity report on the upgraded database",
            check=False,
        )
        if report.returncode != 0:
            failures.append("integrity report on the upgraded database failed")

        # Forward-compatible rollback: the previous release must still start and read the NEW schema.
        rollback = run(
            ["uv", "run", "--directory", str(prev_backend), "python", "manage.py", "check"],
            cwd=prev_backend,
            env=env,
            label="rollback: previous release `check` against the upgraded schema",
            check=False,
        )
        if rollback.returncode != 0:
            failures.append("previous release does not start against the upgraded schema")
        read_code = (
            "import django, os; django.setup()\n"
            "from django.apps import apps\n"
            "bad = []\n"
            "for m in apps.get_models():\n"
            "    try: m._default_manager.count()\n"
            "    except Exception as e: bad.append(f'{m._meta.label}: {type(e).__name__}')\n"
            "print('models readable:', len(apps.get_models()) - len(bad), 'unreadable:', bad)\n"
            "raise SystemExit(1 if bad else 0)\n"
        )
        readable = run(
            ["uv", "run", "--directory", str(prev_backend), "python", "-c", read_code],
            cwd=prev_backend,
            env=env,
            label="rollback: previous release reads every model table on the upgraded schema",
            check=False,
        )
        sys.stdout.write(readable.stdout)
        if readable.returncode != 0:
            failures.append(
                "previous release cannot read the upgraded schema (contract step happened too early)"
            )
    finally:
        try:
            admin_sql(base_url, f"DROP DATABASE IF EXISTS {CHECK_DB}", env)
        except SystemExit as exc:  # pragma: no cover - cleanup best effort
            log(f"cleanup warning: {exc}")
        if not options.keep_worktree:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            shutil.rmtree(worktree.parent, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True, check=False)

    if failures:
        log("MIGRATION COMPATIBILITY FAILED: " + "; ".join(failures))
        return 1
    log(
        f"MIGRATION COMPATIBILITY PASSED: {base_sha[:12]} -> {head_sha[:12]} upgrade applies; previous code starts and reads the new schema"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
