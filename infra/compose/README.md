# Local development stack (Compose)

This is the **local** stack from docs/10_BUILD_GUIDE.md s.5. It is not the production
deployment (docs/12 s.1, s.13): production uses hardened images, an approved TLS proxy, a
supported PostgreSQL service and approved external providers - see
`infra/containers/production/` (Compose shape, environment contract, release/rollback runbook).

| Profile | Services | Purpose |
| --- | --- | --- |
| default | postgres, rabbitmq, valkey, objectstore | minimal infrastructure for host-run Django/Vite |
| `full` | + keycloak, clamav | staff OIDC issuer and malware scanner (needs ~2 GB more RAM) |
| `app` | + api, worker, scheduler, web | fully containerized application (Windows and macOS, D-004); `worker` runs the durable job loop (`process_jobs`); `scheduler` runs the due-obligation scan (30 s) and the outbox dispatcher (60 s) (`run_schedulers`) |

All ports bind to 127.0.0.1 only.

| Service | Host address | Note |
| --- | --- | --- |
| PostgreSQL | 127.0.0.1:`POSTGRES_HOST_PORT` (default **55432**) | 5432 is often taken by a host PostgreSQL |
| RabbitMQ | 5672; management 15672 | non-default credentials from `.env` |
| Valkey | 6379 | password required; no persistence (disposable cache) |
| SeaweedFS S3 | 8333 | credentials from `.env`; anonymous access denied |
| Keycloak | http://localhost:8080 | `start-dev`, never used live |
| ClamAV | private network only | amd64 image; emulated on Apple Silicon |
| API | 127.0.0.1:8000 | `app` profile; migrations applied on start in dev |
| Worker | no port | `app` profile; same image as the API; scans uploads through ClamAV (`SCANNER_PROVIDER=clamav`) - without the `full` profile uploads stay QUARANTINED and the job retries with backoff; also runs notification fan-out/delivery and obligation threshold jobs (B10) |
| Scheduler | no port | `app` profile; same image as the API; `run_schedulers --loop`: due-obligation scan every 30 s (unique threshold actions -> durable jobs) and outbox dispatch every 60 s (RabbitMQ wake-ups via `BROKER_PROVIDER=amqp`; the database row stays authoritative, so a broker outage only delays). Safe to run more than one instance |
| Web | http://localhost:`WEB_HOST_PORT` (default 5173) | `app` profile; nginx serves the SPA and proxies `/api/` |

Images are pinned by digest from `infra/images.lock.json`. Do not edit tags here; change the
lock record first (docs/DEPENDENCY_LOCK.md s.9).

## Commands

```bash
scripts/dev/doctor.sh          # check toolchain, ports, Docker, .env.local
scripts/dev/up.sh              # minimal profile (generates .env.local on first run)
scripts/dev/up.sh app          # + containerized api and web
scripts/dev/up.sh all          # everything
scripts/dev/down.sh            # stop containers, keep data
scripts/dev/down.sh --remove   # remove containers and network, keep data volumes
scripts/dev/down.sh --destroy-volumes   # delete ALL local data; asks you to type "agni-dev"
```

Smoke-check the identity flows against the running stack (OTP through the demo inbox, and with
`--oidc` the staff sign-in against the local Keycloak realm):

```bash
uv run --directory backend python ../scripts/dev/smoke_identity.py http://127.0.0.1:5173 --oidc
uv run --directory backend python ../scripts/dev/smoke_policy.py   http://127.0.0.1:5173 --oidc   # after seed_demo
uv run --directory backend python ../scripts/dev/smoke_drafts.py   http://127.0.0.1:5173          # add --expect-scan QUARANTINED without ClamAV
uv run --directory backend python ../scripts/dev/smoke_submission.py http://127.0.0.1:5173 --scan-via-demo --oidc   # leaves a SCRUTINY case
uv run --directory backend python ../scripts/dev/smoke_inspections.py http://127.0.0.1:5173      # requires the SCRUTINY case (anita/suresh/priya via Keycloak)
uv run --directory backend python ../scripts/dev/smoke_reports.py     http://127.0.0.1:5173      # schedules the follow-up attempt, evidence, draft, report -> REVIEW_PENDING
uv run --directory backend python ../scripts/dev/smoke_notices.py     http://127.0.0.1:5173 --scan-via-demo   # fresh case -> information notice -> reply -> review -> back to SCRUTINY
uv run --directory backend python ../scripts/dev/smoke_clocks.py      http://127.0.0.1:5173      # obligations, manual escalation, scheduler/dispatcher pass, notifications, operations
uv run --directory backend python ../scripts/dev/smoke_offline.py     http://127.0.0.1:5173      # offline package, failed-visit sync + replay + tamper refusal, conflict proposal/resolution (needs a SCRUTINY case)
uv run --directory backend python ../scripts/dev/smoke_decisions.py   http://127.0.0.1:5173      # all-PASS report -> readiness -> approve -> worker renders the sample PDF -> register, download, public verification
uv run --directory backend python ../scripts/dev/smoke_lifecycle.py   http://127.0.0.1:5173      # suspend/reinstate + public status, holder renewal, hold + release on an open case, support ticket with internal note, appeal referral (needs smoke_decisions first)
uv run --directory backend python ../scripts/dev/smoke_reporting.py   http://127.0.0.1:5173      # reconciled metrics, CSV export generated by the worker + ticketed download, audited audit search, grant propose/approve/revoke (arjun + meera), recovery permissions
uv run --directory backend python ../scripts/dev/smoke_integrations.py http://127.0.0.1:5173     # HMAC-signed partner events (apply, duplicate ack, body mismatch 409, unsigned 401, sequence gap -> conflict), allowlisted probe, evidence-based resolution
uv run --directory backend python ../scripts/dev/acceptance_run.py                              # all of the above in order with a PASS/FAIL table (B19); needs ClamAV healthy or SCANNER_PROVIDER=demo for the worker
```

Reliability drills against the same stack (they stop/start real containers or read the
database; nothing is deleted except the isolated `agni_restore_drill` database they create):

```bash
uv run --directory backend python ../scripts/ops/drill_broker_outage.py   http://127.0.0.1:5173   # stop RabbitMQ, accept commands, watch the outbox republish after restart
uv run --directory backend python ../scripts/ops/drill_worker_restart.py  http://127.0.0.1:5173   # stop / kill the worker around a durable export job; lease recovery
scripts/ops/backup.sh && scripts/ops/restore-check.sh evidence/backups/agni_<utc>.dump           # logical backup + isolated restore + integrity report
uv run --directory backend python ../scripts/ops/measure_load.py          http://127.0.0.1:5173 --users 20 --time 2m   # Locust 70/20/10 workload, reduced size
```

The api runs 4 gunicorn workers by default (`GUNICORN_WORKERS`, measured in B17: 2 workers
queued a 20-user run to p95 5.1 s, 4 workers gave p95 690 ms at ~285 MiB RSS).

Seed the synthetic baseline (idempotent) with
`docker exec agni-dev-api-1 python manage.py seed_demo --scenario baseline --require-demo`.

Volumes (`postgres-data`, `rabbitmq-data`, `objectstore-data`, `keycloak-data`, `clamav-data`)
persist across stop/start. `down -v` is never used as a routine restart.

## Memory

The stack carries `mem_limit`s sized for a Docker Desktop VM with about 3 GB RAM: the minimal
profile needs roughly 1.4 GB; `full` adds Keycloak (768 MB) and ClamAV (1.5 GB) and may not fit
on small machines. ClamAV loads its signature database on first start (several minutes, close
to its 1.5 GB limit); until it is healthy, scans stay QUARANTINED and are retried - never marked
clean. Raise the Docker Desktop memory limit or run `full` on CI / a larger host.

## Secrets

`scripts/dev/up.sh` generates `.env.local` at the repository root from `backend/.env.example` with
random values and renders the SeaweedFS identities file under `infra/volumes/` (both gitignored).
Nothing in this directory contains a real secret.
