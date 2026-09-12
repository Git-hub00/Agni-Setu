# Production packaging and release runbook

This directory is the deployable shape of Agni Setu (docs/12 s.1-3, s.5-6, s.9; docs/19 s.3, s.6;
docs/10 s.13). It packages the **application processes only**; the operating environment
supplies PostgreSQL 17, RabbitMQ, Valkey, the private S3 object service, the staff identity
provider, the malware scanner, TLS termination and backups. A working demo on a laptop is not a
live release: B20 (docs/19 s.2 owner decisions) authorises live use, nothing in this directory does.

| File | Purpose |
| --- | --- |
| `compose.prod.yml` | production-shaped Compose: `api`, `worker-light`, `worker-heavy`, `scheduler`, `web`, one-shot `migrate` (profile `release`) |
| `production.env.example` | application environment contract (`AGNI_ENV_FILE`); placeholders are refused by `config.settings.production` |
| `release/<version>/manifest.json` (repository root) | release manifest: commit, lock hashes, image ids/digests, SBOM hashes, scan summary, migration heads |
| `release/<version>/release.env` | written by the publish stage: `AGNI_API_IMAGE` / `AGNI_WEB_IMAGE` by **digest** |
| `.github/workflows/release.yml` | manual, approval-gated pipeline (verify -> build -> publish under the `production` environment) |
| `scripts/ci/migration_compat.py` | expand-contract proof against the previous release |
| `scripts/ops/prod_boot_check.py` | boots this file read-only against the local infrastructure and checks the hardening contract |
| `scripts/ops/release_manifest.py` | SBOMs (uv CycloneDX, pnpm-lock graph, Trivy image SBOM), scans and the manifest |
| `scripts/ops/backup.sh`, `scripts/ops/restore-check.sh` | logical backup + isolated restore rehearsal with the integrity report |

## 1. Hardening contract (checked by `backend/tests/unit/test_release_packaging.py`)

- Images are referenced only as `<registry>/<image>@sha256:<digest>` through `AGNI_API_IMAGE` /
  `AGNI_WEB_IMAGE`; the Compose file never builds and never uses a mutable tag.
- Every container: read-only root filesystem, explicit tmpfs for `/tmp` (api: gunicorn heartbeat,
  fontconfig / WeasyPrint cache via `XDG_CACHE_HOME`; web: nginx pid and proxy cache), all
  capabilities dropped, `no-new-privileges`, non-root user baked into the image, memory and CPU
  limits, rotated json-file logs.
- `config.settings.production` with `RUN_MIGRATIONS_ON_START=false`: the process refuses to start
  on DEBUG, wildcard hosts, http CSRF origins, short or placeholder secrets, missing object
  storage, and - in LIVE - on any demo sink, sample signer, demo scanner, demo controls or demo
  partner secret. Demo routes are not registered outside `APP_ENV=local`.
- Only `web` publishes a port, on `${WEB_BIND_ADDRESS:-127.0.0.1}:${WEB_BIND_PORT:-8080}`, for the
  approved TLS reverse proxy. The api listens on the internal network only; PostgreSQL, RabbitMQ
  management, Valkey, the object service and the identity provider are never published by this
  stack (docs/12 s.2).
- Two worker pools: `worker-heavy` serves `document.scan`, `certificate.issue`, `export.generate`
  (claim limit 2, 1 GiB); `worker-light` serves every other registered kind. The unit test asserts
  the pools partition the registered kinds so no kind is left unserved. `stop_grace_period` (130 s)
  exceeds the job lease (120 s) so a rolling restart lets in-flight jobs finish or expire.

## 2. Environment contract

`release.env` (operator host, non-secret): `AGNI_API_IMAGE`, `AGNI_WEB_IMAGE`, `AGNI_ENV_FILE`,
optional `WEB_BIND_ADDRESS`, `WEB_BIND_PORT`, `API_WORKERS`, `*_MEMORY_LIMIT`, `*_CPU_LIMIT`,
`WORKER_LIGHT_REPLICAS`, `WORKER_HEAVY_REPLICAS`.

`AGNI_ENV_FILE` (mode 0600, rendered from the approved secret store, never committed): see
`production.env.example`. `ALLOWED_HOSTS` lists the public host, `api` (used by the web proxy) and
`127.0.0.1` (the container's own readiness probe). `SERVICE_MODE=LIVE` additionally requires the
approved OTP / notification / signing / scanner adapters and the docs/19 gate evidence.

## 3. Release procedure (docs/12 s.5)

1. **Tag a reviewed commit on `main`** (`git tag -a v0.18.0 -m ...`; push the tag). CI must be
   green on that commit.
2. **Dispatch `Release`** with `version=<tag>`, `previous_release=<previous tag>`,
   `publish=false` first. The `verify` job re-runs every gate and the full backend suite on real
   PostgreSQL and runs `migration_compat.py` (previous release migrates + seeds, current release
   upgrades, `migrate --check`, `makemigrations --check`, integrity report, then the previous
   release's code starts and reads every model table on the upgraded schema). The `build` job
   builds both images from the frozen lockfiles, produces the CycloneDX SBOMs, scans with Trivy
   (any HIGH / CRITICAL finding **with a fix available** fails the run; unfixed ones are recorded
   for treatment in the release notes) and uploads `release/<version>/` + `evidence/release/<version>/`.
3. **Review the evidence artifact**: manifest, SBOM component counts, scan findings and their
   treatment, migration plan output. Record the go/no-go inputs of docs/19 s.6 (restore result,
   role matrix sign-off, policy hash, accessibility review, runbooks, rollback decision).
4. **Dispatch again with `publish=true`.** The `publish` job waits for the required reviewers of
   the GitHub `production` environment (configure them in the repository settings; the workflow
   cannot bypass them), pushes both images to GHCR under the immutable version tag, records the
   registry digests in `manifest.json` and writes `release.env`.
5. **Stage first.** On the staging host: `pull`, `run --rm migrate`, `up -d --wait`, then the role
   and fault smoke checks (`scripts/dev/smoke_*.py`, `scripts/ops/drill_*.py`) and a backup +
   `restore-check.sh`.
6. **Production roll** (after the approval in step 3-4):

   ```bash
   cd /etc/agni && docker compose -p agni-prod --env-file release.env -f compose.prod.yml pull
   docker compose -p agni-prod --env-file release.env -f compose.prod.yml --profile release run --rm migrate
   docker compose -p agni-prod --env-file release.env -f compose.prod.yml up -d --wait
   docker compose -p agni-prod --env-file release.env -f compose.prod.yml ps
   curl -fsS https://<public-host>/api/v1/health/ready
   ```

   Then confirm outbox lag (`/api/v1/operations/summary` as an operator), public verification of
   a known certificate, and one role smoke test per journey. Keep the previous `release.env` as
   `release.env.previous`.

## 4. Migrations: expand-contract rules

- Every migration must be safe to apply **while the previous release is still running**
  (`migrate` runs before the new containers start): add columns as nullable or with defaults, add
  tables and indexes (concurrently when large), never rename or drop something the previous
  release reads.
- The **contract** step (drop / rename / NOT NULL tightening) ships in a later release, after the
  previous release can no longer be rolled back to. `migration_compat.py` enforces this by
  starting the previous release's code against the upgraded schema and reading every table.
- Migrations never rewrite accepted business records (decisions, certificates, audit events,
  outbox rows, receipts). Data backfills run as idempotent management commands, not in
  `migrate`.
- Rollback is **application rollback, not schema downgrade**: reinstate `release.env.previous`
  and `up -d --wait`; leave the schema. A destructive migration or accepted events under the new
  code require an explicit recovery decision (docs/12 s.5) before anything else - never delete
  accepted cases to make an old version start.

## 5. Rollback playbook

1. Decide: symptom, blast radius, whether accepted events exist under the new release.
2. `cp release.env release.env.failed && cp release.env.previous release.env`.
3. `docker compose -p agni-prod --env-file release.env -f compose.prod.yml up -d --wait`
   (pulls the previous digests; the schema stays as upgraded - see s.4).
4. Verify `/health/ready`, outbox lag, public verification, one role smoke.
5. Record the rollback decision, the affected interval and any reconciliation needed
   (issuance requests in UNKNOWN, partner conflicts) in the incident record; reconcile through
   the operator routes, never by editing rows.

## 6. Backup and restore

`scripts/ops/backup.sh` (pg_dump custom format) and `scripts/ops/restore-check.sh <dump>`
(isolated `agni_restore_drill` database, `restore_integrity_report`: schema, counts, canonical
relationships, audit chains, object hashes; measured restore time) are the rehearsal tools. The
pilot objective (RPO <= 15 min, RTO <= 4 h) needs encrypted backups, WAL / PITR, versioned object
retention and off-host custody from the operating environment; a daily logical dump alone does
not meet it (docs/12 s.6) and this repository does not claim it does.

## 7. Local proof of this packaging

```bash
uv run --directory backend python ../scripts/ops/prod_boot_check.py --api-image agni-setu-api:dev --web-image agni-setu-web:dev
uv run --directory backend python ../scripts/ci/migration_compat.py --base <previous commit or tag> --seed
uv run --directory backend python ../scripts/ops/release_manifest.py --version <id> --scan
```

`prod_boot_check.py` proves on the real images that production settings refuse the development
environment, and that the stack boots read-only (readiness 200, demo routes absent, hardening
headers present, `/app` unwritable, only `web` bound on loopback, each worker pool logging exactly
its kinds) in its own Compose project `agni-prodcheck`, which it removes afterwards.
