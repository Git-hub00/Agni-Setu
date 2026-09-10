# Developer build guide and implementation sequence

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Read this before executing commands

This deliverable contains specifications and the reference prototype, not an existing application repository. Commands below define the developer interface that B00-B01 must establish. Do not claim `manage.py`, Compose files or test scripts already exist merely because this guide names them. First inspect the actual repository, create missing scaffold deliberately, and report what was created.

Start with [README](../README.md), [AGENTS.md](../AGENTS.md), [scope](00_PRODUCT_AND_SCOPE.md), [workflow](02_WORKFLOW_AND_POLICY_SPECIFICATION.md), [architecture](04_TECHNICAL_ARCHITECTURE.md) and the current task card. Use the traceability map to load only relevant detailed sections for each slice; do not expect a coding agent to keep every document in one context window.

## 2. Development environment

Preferred execution environment is Linux, macOS or WSL2 on Windows. Use one environment consistently for Git, Python, Node and Docker integration. On Windows, do not alternate Windows Python with Linux virtual environments. Avoid project paths with unusual permission or filesystem synchronization behavior. Keep real case data out of the development repository.

Planning guidance: a 16 GB RAM machine is a reasonable starting point for the full local stack with conservative worker concurrency; 8 GB can run a reduced development profile without identity/scanning/observability services together. This is a planning estimate, not a tested capacity guarantee. No GPU or local LLM is required by the product runtime. Use supported multi-architecture container images on Apple Silicon; verify image manifests rather than forcing slow emulation without noticing it.

Install Git, Docker with Compose v2, Python 3.12, a pinned uv release, Node 24 LTS and a pinned pnpm release through their official distribution channels. Record exact versions and architecture at B00. Do not use unreviewed `curl | bash` installers or an unbounded `latest` command in the release procedure.

```bash
git --version
docker version
docker compose version
python3 --version
uv --version
node --version
pnpm --version
```

Save redacted output to the dependency/environment evidence record. Check available memory, disk and occupied ports before starting services. Reserve at least20 GB free local disk as a development planning allowance; object/test data and container layers can grow.

## 3. Repository initialization and preservation

Inspect `pwd`, directory contents, `git status` and existing source before creating files. If the user supplied a populated repository, map it to this design and ask only about genuine conflicts requiring a decision. Never run destructive reset/clean commands or replace the whole tree blindly. If no repository exists, create `agni-setu`, initialize Git and copy this pack's root documents, `docs/` and `references/` into it.

Create `backend/`, `web/`, `contracts/`, `infra/`, `scripts/`, `tests/` and `evidence/` following the architecture layout. Add .gitignore entries for `.env`, virtual environments, node_modules, build output, browser storage, local database/object volumes and sensitive evidence. Keep schemas, lockfiles, source fixture definitions and migrations tracked.

## 4. Lock the dependency baseline at B00

Resolve the supported release families in the technical spec against official registries and compatibility documentation. Select exact patches, run a small compatibility install/build test, and record them in `docs/DEPENDENCY_LOCK.md`. Commit `backend/uv.lock`, `web/pnpm-lock.yaml`, the Node/pnpm version declarations and `infra/images.lock.json` containing exact image digests and architecture. The lock record must include source, version, license review result, known vulnerability disposition and test evidence.

Only the initial controlled resolution may use bounded ranges such as `Django>=5.2,<5.3`. Subsequent installs use frozen lockfiles. A newer major release discovered later is not automatically adopted. Upgrade through an ADR and compatibility/security tests.

Example first-time Python scaffold, after environment inspection:

```bash
uv init --bare --python 3.12 backend
cd backend
uv add 'Django>=5.2,<5.3' 'djangorestframework>=3.16,<3.17' 'psycopg[binary]>=3,<4'
uv add drf-spectacular django-environ authlib celery boto3 redis weasyprint qrcode
uv add --dev pytest pytest-django hypothesis ruff mypy django-stubs
uv run django-admin startproject config .
cd ..
```

These commands are a bootstrap illustration, not a complete verified requirements file. Immediately constrain/lock the remaining packages to reviewed compatible releases and inspect generated files. Create the custom principal model before first production-worthy migrations. Configure settings modules, transaction/error infrastructure and module directories before implementing features.

For the frontend, create `web/package.json` with the selected React/Vite/TypeScript families, compatible router/query/form/offline dependencies and exact package-manager declaration. Use a pinned official scaffolder only after confirming its version, or write the small Vite scaffold explicitly. Avoid assuming create-vite's major always equals Vite's major. Install once to create the lockfile; CI uses frozen lock.

## 5. Local services and ports

| Service | Host access in default local mode | Purpose |
| --- | --- | --- |
| React Vite | http://localhost:5173 | Browser UI; proxies `/api` to host Django. |
| Django | http://127.0.0.1:8000 | API during local development; not a public production server. |
| PostgreSQL | 127.0.0.1:5432 | Canonical dev database, separate database for automated tests. |
| RabbitMQ | 127.0.0.1:5672; management15672 only local | Task broker; authenticated nondefault credentials. |
| Valkey | 127.0.0.1:6379 | Disposable cache/rate-limit state; authenticated where configured. |
| SeaweedFS local S3 | 127.0.0.1:8333 | Private development objects; explicit access credentials. |
| Keycloak full profile | http://localhost:8080 | Local staff OIDC issuer for host-running Django. |
| ClamAV full profile | Private Docker network; loopback3310 only if host worker requires it | Dedicated scanning adapter. |

Bind infrastructure to loopback/private networks. The source SeaweedFS mini defaults must not be treated as safe production settings; pass explicit credentials, test unauthenticated access denial and use it only locally. Compose volumes persist across normal stop/start. Do not use `down -v` as a routine restart.

The default development API and worker run on the host, so the browser and Authlib can both reach the same local Keycloak issuer. A fully containerized environment needs a canonical issuer hostname reachable by browser and containers through configured DNS/proxy. Do not disable issuer validation or replace the issuer claim with an internal Docker name to bypass this. Production uses the approved HTTPS issuer resolvable from all relevant components.

## 6. Environment contract

Create `.env.example` with safe placeholders and explanations, never working production secrets. The local bootstrap script generates random secrets into a gitignored `.env` and prints only the minimum necessary local connection information. Require separate credentials and databases per environment.

```text
APP_ENV=local
SERVICE_MODE=DEMO
DJANGO_SETTINGS_MODULE=config.settings.local
DJANGO_SECRET_KEY=<generated-local-secret>
DATABASE_URL=postgresql://agni_app:<generated>@127.0.0.1:5432/agni_dev
TEST_DATABASE_NAME=agni_test
CELERY_BROKER_URL=amqp://agni_worker:<generated>@127.0.0.1:5672/agni_dev
CACHE_URL=redis://:<generated>@127.0.0.1:6379/0
OTP_PEPPER=<generated-independent-secret>
CONTACT_LOOKUP_KEY=<generated-independent-secret>
DATA_ENCRYPTION_KEY_REF=<local-secret-reference>
OBJECT_ENDPOINT=http://127.0.0.1:8333
OBJECT_REGION=local
OBJECT_BUCKET=agni-dev-private
OBJECT_ACCESS_KEY=<generated-local-id>
OBJECT_SECRET_KEY=<generated-local-secret>
OIDC_ISSUER=http://localhost:8080/realms/agni-dev
OIDC_CLIENT_ID=agni-web
OIDC_CLIENT_SECRET=<generated-local-client-secret>
PUBLIC_ORIGIN=http://localhost:5173
CSRF_TRUSTED_ORIGINS=http://localhost:5173
OTP_PROVIDER=demo_sink
NOTIFICATION_PROVIDER=demo_sink
SIGNING_PROVIDER=demo_watermark
SCANNER_PROVIDER=clamav
ENABLE_DEMO_CONTROLS=true
```

The angle-bracket values are deliberate secrets to generate, not strings to paste into a live environment. Settings validation rejects missing or default production secrets. Demo reset and fault controls are registered only when APP_ENV and service mode permit them. A live startup rejects sample signer, demo OTP, unrestricted hosts/CORS, DEBUG and insecure identity settings.

## 7. Required scripts to implement at B01

- `scripts/dev/doctor.sh`: check runtime versions, locks, ports, Docker, environment, database/provider reachability and mode separation; redact secrets.
- `scripts/dev/up.sh`: start the selected local infrastructure profile without deleting volumes; wait for health and report addresses.
- `scripts/dev/down.sh`: stop local services safely; destructive volume deletion requires a separate explicit command and confirmation.
- `scripts/ci/verify.sh`: lint, type-check, migration drift check, unit/integration/contracts, frontend tests/build and schema consistency.
- `scripts/fixtures/seed.sh`: load deterministic demo scenario through guarded fixture builders; refuse non-demo database.
- `scripts/ops/backup.sh` and `restore-check.sh`: approved backup and isolated restore rehearsal, never overwrite live by default.

Scripts return nonzero on failure, explain the failing step, avoid shell tracing of secrets and are executable. They must work from the repository root and validate destructive target names before any modification.

## 8. First boot sequence after scaffold exists

```bash
docker compose -p agni-dev -f infra/compose/compose.dev.yml up -d postgres rabbitmq valkey objectstore
docker compose -p agni-dev -f infra/compose/compose.dev.yml --profile full up -d keycloak clamav
cd backend
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py seed_demo --scenario baseline --require-demo
uv run python manage.py runserver 127.0.0.1:8000
```

Run each long-lived process in a separate terminal. Use startup checks to ensure the seed command cannot target a non-demo service. The command creates synthetic accounts/grants and validated case histories; it never sends real messages.

Worker terminal:

```bash
cd backend
uv run celery -A config.celery worker -Q default,notifications,documents,issuance --concurrency=2
```

Scheduler/dispatcher terminal (custom management command implemented at B10):

```bash
cd backend
uv run python manage.py run_schedulers --tick-seconds 30
```

Frontend terminal:

```bash
cd web
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --port 5173
```

The scheduler command runs the obligation scanner, outbox dispatcher and reconciler at their documented intervals with database locking. It must handle SIGTERM cleanly. Do not accidentally run uncoordinated Celery Beat copies and custom schedulers both creating the same business actions without shared uniqueness controls.

## 9. Build order and gates

| Task | Slice | Depends on | Required deliverable |
| --- | --- | --- | --- |
| B00 | Baseline and dependency lock | None | Inspect repository, preserve user work, approve stack ADRs, record exact package/image versions and local environment. |
| B01 | Repository and runnable skeleton | B00 | Create Django/React workspaces, Compose infrastructure, health probes and reproducible task commands. |
| B02 | Domain persistence and command kernel | B01 | Create foundational migrations, authorization fences, command receipts, audit, outbox and deterministic clock tests. |
| B03 | Identity, sessions and scoped permissions | B02 | Implement applicant OTP, staff OIDC, approved grants, anti-abuse, CSRF and cross-user access tests. |
| B04 | Service policy and master data | B03 | Build immutable policy packages, independent approval, applicability, routing versions and premises delegation. |
| B05 | Drafts, files and application wizard | B04 | Build real server drafts, versioned documents, quarantined uploads, scan jobs and accessible wizard. |
| B06 | Submission, routing and case visibility | B05 | Commit atomic submission and receipt, route exceptions, case lists and audience-filtered timeline. |
| B07 | Assignment and appointment management | B06 | Create inspection attempts, availability checks, conflict-safe booking, cancellation and failed-visit flows. |
| B08 | Inspection reports and checklist evaluation | B07 | Implement observations, evidence, immutable report revisions and deterministic mandatory blockers. |
| B09 | Notices, responses and correction cycles | B08 | Build itemized information and deficiencies, response versions, verification and reinspection. |
| B10 | Clocks, outbox dispatch and notifications | B09 | Deliver persistent obligation calculations, unique escalation actions, retry-safe jobs and delivery tracking. |
| B11 | Offline field application | B10 | Installable PWA, minimum local packages, explicit synchronization and version/authority conflict workflows. |
| B12 | Decisions, issuance and verification | B11 | Implement guarded decisions, durable sample issuance, registry, status-safe verification and signer adapter boundary. |
| B13 | Lifecycle, support and conditional routes | B12 | Build renewal and status instruments, support, withdrawal, hold controls and disabled/referral appeal pathways. |
| B14 | Reporting, audit and operational UI | B13 | Build reconciled metrics, scoped exports, read auditing, job recovery and responsive role workspaces. |
| B15 | Integration contracts and reconciliation | B14 | Implement local simulators, signed partner inbox, ownership rules, ordered processing and controlled reconciliation. |
| B16 | Security and accessibility hardening | B15 | Validate threat scenarios, accessible journeys, browser matrix, uploads, identity revocation and secrets scans. |
| B17 | Reliability, performance and recovery proof | B16 | Run concurrency/fault/load suites, object/database recovery drill and measurement reports. |
| B18 | Production packaging and release evidence | B17 | Create hardened images, CI/CD approvals, upgrade/rollback runbooks, SBOM and release evidence. |
| B19 | Full demonstration acceptance | B18 | Validate all role journeys and mapped prototype controls with deterministic fixtures; fix and retest defects. |
| B20 | Agency pilot activation | B19 | Complete legal/policy/integration/security/operations approvals before any official live case or certificate. |


Use [the task cards](17_AGENT_TASK_CARDS.md) for per-slice files, tests and stop conditions. Complete a narrow vertical workflow, reload it from the server and prove a failure case before moving on. Keep unfinished navigation behind feature gates; do not create all screens with success-only dummy handlers and postpone backend integrity.

## 10. Per-slice development loop

Read relevant FR/TR/UI/API/schema contracts. Identify concrete files to change. Write failing tests for the command and at least its permission, validation, duplicate and concurrency cases. Implement domain/application code and migrations. Implement screen/loading/error behavior against the real API. Run relevant tests, restart affected long-lived processes and manually verify the slice. Update traceability/status with actual evidence. Commit a coherent change. Do not proceed while a critical safety invariant test remains broken.

After changes to worker task code, restart workers. After scheduler or policy-evaluation code changes, restart scheduler and workers as appropriate. After Django settings/model/migration changes, apply migrations and restart the API/worker processes using those models. After frontend dependency/config changes, restart Vite and rebuild. Reloading a web tab does not reload a Python worker.

## 11. Required verification commands

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy agni
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest tests/unit tests/properties
uv run pytest tests/integration tests/contracts tests/security
uv run python manage.py spectacular --file ../contracts/openapi.yaml --validate
cd ../web
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
pnpm test:e2e
```

Configure actual scripts to match these names before claiming they are executable. CI schema validation must compare generated output to committed contracts and fail on unexplained drift. Browser tests start a dedicated test environment and use synthetic accounts; they do not reset a developer's existing demo unless explicitly requested.

## 12. Troubleshooting without weakening controls

Port already used: identify the process and choose a documented local port override; do not kill unknown processes. Database connection failure: check credentials, host versus container addressing and readiness. OIDC issuer mismatch: fix canonical host/DNS and redirect URI, not verification checks. CSRF failure: verify proxy origin, cookie path and trusted origin. Queue not dispatching: inspect database outbox, broker health and worker queue subscription. Upload stuck: inspect reservation/object version/scan job. Issuance unknown: reconcile provider, never set completed manually. Stale frontend types: regenerate schema/client under review.

## 13. Production packaging is a separate gate

Development runserver, Keycloak start-dev, loopback object emulator and demo credentials are not the production deployment. B18 creates hardened images, production settings, private service networking, approved external adapters, secret management, backup/restore and release approvals. B20 alone authorizes live use after owner decisions; successfully opening the demo homepage is not a live release.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
