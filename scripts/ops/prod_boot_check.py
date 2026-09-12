"""Production packaging boot check (task card B18 "production checks fail unsafe settings";
docs/12 s.2-3). Runs the production-shaped Compose file against the LOCAL infrastructure with a
throwaway production environment and proves, on the real images:

  A. the production image REFUSES the development environment (placeholders / http origins /
     demo controls) - `manage.py check` exits non-zero listing the problems, never a value;
  B. with a complete production environment the stack boots read-only (api, worker-light,
     worker-heavy, scheduler, web): readiness passes, the demo routes are absent, the root
     filesystems are read-only with all capabilities dropped, only the web port is published,
     each worker pool serves exactly its job kinds, and the one-shot `migrate` service is a
     no-op on an up-to-date schema.

Everything runs in its own Compose project `agni-prodcheck` on the existing `agni-dev` network;
the database is the developer database (read + idempotent migrate only). The project is removed
at the end (it owns no volumes). Secrets are generated into a temporary directory and never
printed. Usage (repository root):

  uv run --directory backend python ../scripts/ops/prod_boot_check.py [--api-image X] [--web-image Y]
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "containers" / "production" / "compose.prod.yml"
PROJECT = "agni-prodcheck"
DEV_NETWORK = "agni-dev_default"
WEB_PORT = 18080
PUBLIC_HOST = "agni.example.test"
HEAVY = ["certificate.issue", "document.scan", "export.generate"]
LIGHT = [
    "integration.apply",
    "integration.test",
    "notification.deliver",
    "notification.fanout",
    "obligation.threshold",
]

failures: list[str] = []


def log(message: str) -> None:
    print(f"[prodcheck] {message}", flush=True)


def check(condition: bool, label: str) -> None:
    log(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures.append(label)


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def run(
    args: list[str], *, check_exit: bool = True, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if check_exit and result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(args[:4])} ...\n{result.stderr[-1500:]}"
        )
    return result


def compose(
    release_env: Path, *args: str, check_exit: bool = True, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "docker",
            "compose",
            "-p",
            PROJECT,
            "--env-file",
            str(release_env),
            "-f",
            str(COMPOSE),
            "-f",
            str(release_env.parent / "override.yml"),
            *args,
        ],
        check_exit=check_exit,
        timeout=timeout,
    )


PROBE = (
    "import sys, urllib.request, urllib.error\n"
    "url, host = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)\n"
    "req = urllib.request.Request(url, headers={'Host': host} if host else {})\n"
    "try:\n"
    "    resp = urllib.request.urlopen(req, timeout=30)\n"
    "except urllib.error.HTTPError as err:\n"
    "    resp = err\n"
    "print(resp.status)\n"
    "for key, value in resp.headers.items():\n"
    "    print(f'{key}: {value}')\n"
)


def probe(container: str, url: str, host: str | None = None) -> tuple[str, str]:
    """HTTP status and lower-cased headers of `url` fetched from inside `container`."""
    args = ["docker", "exec", container, "python", "-c", PROBE, url, *([host] if host else [])]
    # One retry: the stack has just come up and the 3 GB VM can stall for seconds right after
    # five containers start; a second timeout is a real failure.
    for attempt in (1, 2):
        result = run(args, check_exit=False)
        lines = result.stdout.strip().splitlines()
        if lines:
            return lines[0], "\n".join(lines[1:]).lower()
        if attempt == 1:
            log(f"probe of {url} produced no response; retrying once in 10 s")
            time.sleep(10)
    return f"ERR {result.stderr.strip()[-160:]}", ""


def service_url(scheme: str, user: str, password: str, host: str, path: str) -> str:
    """Assemble a credentialed service URL from the local values (kept out of any literal)."""
    return "".join([scheme, "://", user, ":", password, "@", host, "/", path])


def write_production_env(dev: dict[str, str], target: Path) -> None:
    lines = {
        "APP_ENV": "production",
        "SERVICE_MODE": "DEMO",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DATABASE_URL": service_url("postgresql", dev["POSTGRES_USER"], dev["POSTGRES_PASSWORD"], "postgres:5432", dev["POSTGRES_DB"]),
        "CELERY_BROKER_URL": service_url("amqp", dev["RABBITMQ_USER"], dev["RABBITMQ_PASSWORD"], "rabbitmq:5672", dev.get("RABBITMQ_VHOST", "agni_dev")),
        "CACHE_URL": service_url("redis", "", dev["VALKEY_PASSWORD"], "valkey:6379", "0"),
        "OTP_PEPPER": secrets.token_urlsafe(48),
        "CONTACT_LOOKUP_KEY": secrets.token_urlsafe(48),
        "DATA_ENCRYPTION_KEY": secrets.token_urlsafe(48),
        "DATA_ENCRYPTION_KEY_REF": "prodcheck-local-reference",
        "OBJECT_STORE_PROVIDER": "s3",
        "OBJECT_ENDPOINT": "http://objectstore:8333",
        "OBJECT_REGION": dev.get("OBJECT_REGION", "local"),
        "OBJECT_BUCKET": dev["OBJECT_BUCKET"],
        "OBJECT_ACCESS_KEY": dev["OBJECT_ACCESS_KEY"],
        "OBJECT_SECRET_KEY": dev["OBJECT_SECRET_KEY"],
        "OIDC_ISSUER": dev.get("OIDC_ISSUER", "http://localhost:8080/realms/agni-dev"),
        "OIDC_METADATA_URL": "http://keycloak:8080/realms/agni-dev/.well-known/openid-configuration",
        "OIDC_CLIENT_ID": dev.get("OIDC_CLIENT_ID", "agni-web"),
        "OIDC_CLIENT_SECRET": dev.get("OIDC_CLIENT_SECRET", secrets.token_urlsafe(24)),
        "PUBLIC_ORIGIN": f"https://{PUBLIC_HOST}",
        "CSRF_TRUSTED_ORIGINS": f"https://{PUBLIC_HOST}",
        "ALLOWED_HOSTS": f"{PUBLIC_HOST},api,127.0.0.1",
        "PUBLIC_VERIFY_BASE_URL": f"https://{PUBLIC_HOST}/verify",
        "TRUST_X_FORWARDED_FOR": "true",
        "OTP_PROVIDER": "demo_sink",
        "NOTIFICATION_PROVIDER": "demo_sink",
        "SIGNING_PROVIDER": "demo_watermark",
        "SCANNER_PROVIDER": "clamav",
        "SCANNER_HOST": "clamav",
        "SCANNER_PORT": "3310",
        "ENABLE_DEMO_CONTROLS": "false",
        "LOG_LEVEL": "INFO",
    }
    target.write_text("".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api-image", default="agni-setu-api:dev")
    parser.add_argument("--web-image", default="agni-setu-web:dev")
    parser.add_argument("--keep", action="store_true", help="leave the check project running")
    options = parser.parse_args(argv)

    dev_env = ROOT / ".env.local"
    if not dev_env.is_file():
        raise SystemExit(".env.local not found (run scripts/dev/up.sh first)")
    dev = env_values(dev_env)
    workdir = Path(tempfile.mkdtemp(prefix="agni-prodcheck-"))
    app_env = workdir / "agni.env"
    release_env = workdir / "release.env"
    write_production_env(dev, app_env)
    release_env.write_text(
        f"AGNI_API_IMAGE={options.api_image}\nAGNI_WEB_IMAGE={options.web_image}\nAGNI_ENV_FILE={app_env.as_posix()}\n"
        f"WEB_BIND_PORT={WEB_PORT}\nWEB_BIND_ADDRESS=127.0.0.1\n",
        encoding="utf-8",
    )
    # The application services additionally join the local infrastructure network to reach
    # postgres / rabbitmq / valkey / objectstore. `internal` stays project-scoped on purpose:
    # the dev stack also has a service called `api`, and Docker DNS would hand the web proxy
    # either container when both share one network (run 5 of this check answered 400 from the
    # DEV api, whose ALLOWED_HOSTS does not know the public host).
    app_services = ("api", "migrate", "worker-light", "worker-heavy", "scheduler")
    (workdir / "override.yml").write_text(
        "# prodcheck only: reach the local infrastructure instead of external services\n"
        "services:\n"
        + "".join(f"  {name}:\n    networks: [internal, devinfra]\n" for name in app_services)
        + f"networks:\n  devinfra:\n    name: {DEV_NETWORK}\n    external: true\n",
        encoding="utf-8",
    )
    log(f"temporary environment in {workdir} (removed at the end; values never printed)")
    started = time.monotonic()
    try:
        # ---- A. the production image refuses the development environment -----------------------
        refused = run(
            [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--network",
                DEV_NETWORK,
                "--env-file",
                str(dev_env),
                "-e",
                "DJANGO_SETTINGS_MODULE=config.settings.production",
                # The development file already carries generated secrets and explicit hosts, so
                # only its http origin trips the check; add the classic unsafe values a LIVE
                # deployment must refuse (placeholder key, wildcard hosts, demo sinks in LIVE).
                "-e",
                "SERVICE_MODE=LIVE",
                "-e",
                "DJANGO_SECRET_KEY=changeme",
                "-e",
                "ALLOWED_HOSTS=*",
                "-e",
                "DATABASE_URL=postgresql://x:y@postgres:5432/z",
                options.api_image,
                "python",
                "manage.py",
                "check",
            ],
            check_exit=False,
        )
        problems = [
            line.strip() for line in refused.stderr.splitlines() if line.strip().startswith("- ")
        ]
        check(
            refused.returncode != 0
            and "Refusing to start with unsafe production configuration" in refused.stderr,
            "A1 production settings refuse the development environment (non-zero exit)",
        )
        named = {
            "DJANGO_SECRET_KEY",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "ENABLE_DEMO_CONTROLS",
            "OTP_PROVIDER",
            "SIGNING_PROVIDER",
        }
        listed = " ".join(problems)
        check(
            len(problems) >= 5 and all(name in listed for name in named),
            f"A2 the refusal lists every problem together ({len(problems)} listed: {'; '.join(p[2:] for p in problems)})",
        )
        check(
            not any(
                v in refused.stderr
                for k, v in dev.items()
                if k.endswith(("PASSWORD", "KEY", "SECRET", "PEPPER")) and len(v) > 8
            ),
            "A3 no secret value appears in the refusal output",
        )

        # ---- B. production-shaped stack boots read-only against the local infrastructure --------
        compose(release_env, "config", "-q")
        check(True, "B1 compose.prod.yml renders with the release variables (config -q)")
        rendered = json.loads(compose(release_env, "config", "--format", "json").stdout)
        services = rendered["services"]
        published = {name: svc.get("ports") for name, svc in services.items() if svc.get("ports")}
        check(
            set(published) == {"web"},
            f"B2 only `web` publishes a port (published: {sorted(published)})",
        )
        check(
            all(svc.get("read_only") is True for svc in services.values()),
            "B3 every service declares read_only",
        )
        check(
            all(svc.get("cap_drop") == ["ALL"] for svc in services.values()),
            "B4 every service drops all capabilities",
        )

        migrate = compose(
            release_env,
            "--profile",
            "release",
            "run",
            "--rm",
            "--no-deps",
            "migrate",
            check_exit=False,
            timeout=900,
        )
        check(
            migrate.returncode == 0
            and ("No migrations to apply" in migrate.stdout or "Applying" in migrate.stdout),
            "B5 one-shot `migrate` service runs with production settings (idempotent on the current schema)",
        )

        up = compose(
            release_env,
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "240",
            "api",
            "worker-light",
            "worker-heavy",
            "scheduler",
            "web",
            check_exit=False,
            timeout=900,
        )
        if up.returncode != 0:
            log(compose(release_env, "logs", "--tail", "60", check_exit=False).stdout[-6000:])
        check(
            up.returncode == 0,
            "B6 api, worker-light, worker-heavy, scheduler and web reach healthy with read-only root filesystems",
        )

        ps = json.loads(
            "["
            + ",".join(
                line
                for line in compose(release_env, "ps", "--format", "json").stdout.splitlines()
                if line.strip()
            )
            + "]"
        )
        names = {row["Service"]: row["Name"] for row in ps}
        api = names.get("api", f"{PROJECT}-api-1")
        inspect = json.loads(run(["docker", "inspect", *names.values()]).stdout)
        check(
            all(c["HostConfig"]["ReadonlyRootfs"] for c in inspect),
            "B7 docker inspect: ReadonlyRootfs on every container",
        )
        check(
            all(
                "no-new-privileges:true" in (c["HostConfig"].get("SecurityOpt") or [])
                for c in inspect
            ),
            "B8 docker inspect: no-new-privileges on every container",
        )
        check(
            all(c["Config"]["User"] not in ("", "root", "0") for c in inspect),
            f"B9 every container runs as a non-root user ({sorted({c['Config']['User'] for c in inspect})})",
        )
        ports = {c["Name"]: c["NetworkSettings"]["Ports"] for c in inspect}
        bound = {
            name: [f"{b['HostIp']}:{b['HostPort']}" for p in (m or {}).values() for b in (p or [])]
            for name, m in ports.items()
        }
        check(
            all(not v or name.endswith("-web-1") for name, v in bound.items())
            and any(v == [f"127.0.0.1:{WEB_PORT}"] for v in bound.values()),
            f"B10 only web is bound, on 127.0.0.1:{WEB_PORT} ({bound})",
        )

        # HTTP probes run inside the api container with its interpreter (the image ships no curl).
        ready_status, headers = probe(api, "http://127.0.0.1:8000/api/v1/health/ready")
        check(
            ready_status == "200",
            f"B11 api readiness 200 with production settings ({ready_status})",
        )
        web_status, _ = probe(api, f"http://{PROJECT}-web-1:8080/")
        check(web_status == "200", f"B12 web serves the shell ({web_status})")
        # The proxy forwards the browser's Host header; the TLS proxy in front of `web` presents
        # the public host, so the probe does too (any other Host is a 400 - Django's
        # ALLOWED_HOSTS refusing an unknown name is the hardening at work).
        proxy_status, _ = probe(api, f"http://{PROJECT}-web-1:8080/api/v1/health/live", PUBLIC_HOST)
        check(
            proxy_status == "200",
            f"B13 web proxies /api/ to the api under the public host ({proxy_status})",
        )
        demo_status, _ = probe(api, "http://127.0.0.1:8000/api/v1/demo/inbox?channel=EMAIL&contact=x")
        check(
            demo_status == "404",
            f"B14 demo inbox route is absent with production settings ({demo_status})",
        )
        check(
            "content-security-policy" in headers and "x-content-type-options: nosniff" in headers,
            "B15 hardening headers present on API responses",
        )
        # Source maps never leave the build (G-07): no *.map in the served tree, no
        # sourceMappingURL in the bundles, and nginx answers 404 for any *.map path.
        web = names.get("web", f"{PROJECT}-web-1")
        maps = run(
            [
                "docker",
                "exec",
                web,
                "sh",
                "-c",
                "find /usr/share/nginx/html -type f -name '*.map' | wc -l;"
                " grep -l sourceMappingURL /usr/share/nginx/html/assets/*.js 2>/dev/null | wc -l",
            ],
            check_exit=False,
        )
        counts = [line.strip() for line in maps.stdout.splitlines() if line.strip()]
        check(
            counts == ["0", "0"],
            f"B21 web image ships no source maps / sourceMappingURL (map files, bundles = {counts})",
        )
        map_status, _ = probe(api, f"http://{PROJECT}-web-1:8080/assets/index-probe.js.map")
        check(map_status == "404", f"B22 nginx refuses *.map paths ({map_status})")
        write = run(
            ["docker", "exec", api, "sh", "-c", "touch /app/prodcheck 2>&1 || echo READONLY"],
            check_exit=False,
        )
        check(
            "READONLY" in write.stdout or "Read-only file system" in write.stdout,
            "B16 writing under /app is refused inside the api container",
        )
        tmp = run(
            [
                "docker",
                "exec",
                api,
                "sh",
                "-c",
                "touch /tmp/prodcheck && rm /tmp/prodcheck && echo TMPOK",
            ],
            check_exit=False,
        )
        check(
            "TMPOK" in tmp.stdout, "B17 /tmp tmpfs is writable (gunicorn heartbeat / render cache)"
        )

        light_log = run(
            ["docker", "logs", names.get("worker-light", f"{PROJECT}-worker-light-1")],
            check_exit=False,
        )
        heavy_log = run(
            ["docker", "logs", names.get("worker-heavy", f"{PROJECT}-worker-heavy-1")],
            check_exit=False,
        )
        light_line = next(
            (
                line
                for line in (light_log.stdout + light_log.stderr).splitlines()
                if "serving:" in line
            ),
            "",
        )
        heavy_line = next(
            (
                line
                for line in (heavy_log.stdout + heavy_log.stderr).splitlines()
                if "serving:" in line
            ),
            "",
        )
        check(
            light_line.split("serving:")[-1].strip() == ", ".join(LIGHT),
            f"B18 worker-light serves exactly the light kinds ({light_line.split('serving:')[-1].strip()})",
        )
        check(
            heavy_line.split("serving:")[-1].strip() == ", ".join(HEAVY),
            f"B19 worker-heavy serves exactly the heavy kinds ({heavy_line.split('serving:')[-1].strip()})",
        )
        sched_log = run(
            ["docker", "logs", "--tail", "20", names.get("scheduler", f"{PROJECT}-scheduler-1")],
            check_exit=False,
        )
        check(
            "Traceback" not in sched_log.stdout + sched_log.stderr,
            "B20 scheduler runs without errors",
        )
    finally:
        elapsed = time.monotonic() - started
        if not options.keep:
            compose(
                release_env, "--profile", "release", "down", "--remove-orphans", check_exit=False
            )
            log("check project removed (no volumes were created)")
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            log(
                f"--keep: project {PROJECT} left running; compose files in {workdir} (contains "
                f"generated secrets - remove it with the project: docker compose -p {PROJECT} "
                f"--env-file {release_env} -f {COMPOSE} -f {workdir / 'override.yml'} down)"
            )
        log(f"elapsed {elapsed:.0f}s")
    if failures:
        log(f"PRODUCTION BOOT CHECK FAILED: {len(failures)} check(s): {failures}")
        return 1
    log("PRODUCTION BOOT CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
