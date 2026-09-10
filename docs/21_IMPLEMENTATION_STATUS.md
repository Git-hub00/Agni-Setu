# Implementation progress, evidence and unresolved decisions

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Initial status

**Documentation baseline:** 2.0.0. **New production implementation:** NOT_STARTED in this deliverable. **Application test execution:** NOT_RUN. A browser prototype exists as reference; it is not the Django/PostgreSQL application. No build phase is marked complete on the basis of this documentation alone.

Update this file at the end of each agent task. Read actual repository/branch/diff first: a later developer may already have implemented work, and this initial status must not cause an agent to overwrite it. A phase is DONE only after the specified acceptance evidence exists for the current commit.

## 2. Phase ledger

| Phase | Deliverable | Initial status | Evidence/commit | Next action |
| --- | --- | --- | --- | --- |
| B00 | Baseline and dependency lock | READY_FOR_REVIEW (2026-09-10T19:1xZ; PR pending) | Repository inspected, user work preserved, ADR-01..15 accepted (`docs/DEPENDENCY_LOCK.md` s.3). Environment: Python 3.12.7, Node 24.14.1, uv 0.11.28, pnpm 12.3.4, Git 2.45.2, Docker 28.5.1 + Compose v2.40.3, WSL2 Ubuntu; host RAM 5.9 GB (L-05), port 5432 occupied (L-06). Locks: `backend/uv.lock` (100 pkgs: Django 5.2.17, DRF 3.17.2, psycopg 3.3.5, celery 5.6.3, ...), `web/pnpm-lock.yaml` (164 pkgs: React 19.3.0, Vite 8.2.2, TS 5.9.3, ...), `infra/images.lock.json` (postgres 17.11, rabbitmq 4.3.5-management, valkey 8.1.10, seaweedfs 4.46, keycloak 26.7.3, clamav 1.5.4 with registry digests). Proofs PASS: `uv sync --frozen`, `manage.py check`, `ruff check`, `ruff format --check`, `mypy` strict, `pip-audit` (after DEV-01..03 security bumps), `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm build`, `pnpm audit`. Evidence EV-B00-02..08 in DEPENDENCY_LOCK s.7; handoff record s.3b below | Open PR `feat/b00-baseline-lock`, self-review, merge; then B01 |
| B01 | Repository and runnable skeleton | READY_FOR_REVIEW (2026-09-10T19:5xZ; PR pending) | Compose stack `infra/compose/compose.dev.yml` (profiles default/full/app; digest-pinned images; loopback ports; PostgreSQL on 55432; healthchecks; mem limits) - minimal and app profiles brought up locally: **6/6 services healthy**. Images `agni-setu-api:dev` (543 MB, non-root, gunicorn) and `agni-setu-web:dev` (94 MB, unprivileged nginx). API-121/122 probes: live 200, ready 200 (database/schema/configuration pass) both directly and through nginx; SPA index and deep-route fallback 200; security headers present. Settings base/local/test/production with fail-closed production validation; `.env.example` contract; `backend/docker-entrypoint.sh`. Tests: backend **22 passed** (18 unit incl. 12 bad-production-config refusals + 4 integration on real PostgreSQL), web **10 passed** (shell landmarks, 7 placeholders, readiness states, api client CSRF/If-Match/idempotency); ruff, `ruff format`, `mypy --strict` (incl. tests), eslint (0 warnings), tsc all PASS. Scripts `scripts/dev/{doctor,up,down}.sh`, `scripts/ci/verify.sh`, CI workflow `.github/workflows/ci.yml`, root README quick start (Windows/macOS). Evidence EV-B01-01..06 in `handover.md` B7; record s.3c | Open PR `feat/b01-runnable-skeleton`; then B02. Limitations: shell scripts could not be executed by the agent (harness gate) - syntax/behaviour UNVERIFIED until run by CI or user; `full` profile (Keycloak/ClamAV) not started locally (RAM) |
| B02 | Domain persistence and command kernel | READY_FOR_REVIEW (2026-09-10T20:23Z; PR pending) | Custom `identity.Principal` (AUTH_USER_MODEL, no client-writable role) + `PrincipalFence` lock row; `platform` tables `CommandReceipt`, `OutboxMessage`, `AuditEvent` (per-entity hash chain); master data `Jurisdiction`, `Service` (activation fence), `DutyQueue`; cases `Premises`, `Application` (eleven-state enum + DB check, received-has-submitted_at check, source-tuple uniqueness), `StageInstance` (one open stage per case), `CaseEvent` (append-only, ordered by aggregate version). Kernel `agni.platform.commands.execute`: fence lock -> authorize -> receipt replay/conflict -> FOR UPDATE target -> 428/412 version checks -> apply -> version bump -> audit (abort on failure) -> outbox -> immutable receipt (same command_id referenced by events in-transaction) -> on_commit wake-up. Typed error catalogue (51 codes) + RFC 9457 problem handler + request-id middleware + injected clock. First commands RegisterPremises (API-011) and CreateDraftApplication (API-021). Migrations 0001/0002 per app; applied forward on the local dev DB (7 migrations, readiness schema pass). Tests: **64 passed** (unit 33, properties 6, integration 25 on real PostgreSQL incl. rollback-leaves-nothing, duplicate-command-one-result, stale-version-412, missing-precondition-428, audit-failure-aborts, disabled-principal, cross-principal-not-found, per-principal receipt scope, 2-thread same-key race -> exactly one receipt); ruff/format/mypy strict clean; `makemigrations --check` clean. Record s.3d | Push `feat/b02-command-kernel`, PR; then B03 |
| B03 | Identity, sessions and scoped permissions | READY_FOR_REVIEW (2026-09-10T22:0xZ; PR pending) | Applicant OTP (6-digit keyed-MAC challenge, 5 min, 5 attempts, 60 s resend, 5/contact/h + 20/IP/h in Valkey/cache failing closed, demo sink, enumeration-safe), staff OIDC via Authlib (PKCE/state/nonce, issuer+subject mapping to provisioned principals only), DB sessions with key+CSRF rotation, 30 min idle / 8 h absolute / epoch recheck, CSRF enforced on every unsafe request incl. anonymous login endpoints, `/me` projection, logout, role bindings + authority grants (DB separation-of-duties constraints) + access requests, governance commands (provision from approved request, approve/revoke grant, disable with epoch bump), scope-first selectors, encrypted verified contacts, demo-only inbox route and `provision_demo_staff` command (refuse outside demo). Web: `/sign-in` (OTP form, countdowns, staff OIDC link, error mapping), `/account`, route guard, granted-workspace nav. Tests: backend **105 passed** (AT-01-01..05, AT-02-01..05 incl. two race tests), web **15 passed**, lint/mypy/tsc clean. **End-to-end against the containers via nginx** (`scripts/dev/smoke_identity.py`): OTP 11/11 steps PASS; OIDC against real Keycloak 26.7.3 realm import: unprovisioned subject refused, provisioned subject signs in, `/me` STAFF ['supervisor']. Fixes found only by the container run: `requests` runtime dep (DEV-04), nginx dynamic upstream + `$http_host`, Keycloak full-URL hostname for dynamic backchannel, 503 for unreachable provider. Record s.3e | Push `feat/b03-identity`, PR; then B04 |
| B04 | Service policy and master data | READY_FOR_REVIEW (2026-09-10T23:25Z; PR pending) | Policy packages as data: `PolicyArtifact` (FORM/CHECKLIST/CALENDAR/ROUTING, content-hashed, append-only numbers), `PolicyVersion` (DRAFT -> IN_REVIEW -> APPROVED -> SCHEDULED/ACTIVE -> RETIRED, RETURNED loop; DB checks approver != preparer, interval order, effective-requires-approval), append-only `PolicyContributor` and `PolicySimulation`. Draft 2020-12 JSON Schema (`additionalProperties: false`, 29 required keys, cross-field rules) - no executable constructs. Deterministic simulation suite `demo-baseline-v1` (schema, artifacts, checklist mandatory/unique, calendar, documents per category, routing coverage + equal-priority overlap, clock budgets, transition subsets). Governance commands through the kernel: prepare, patch (DRAFT/RETURNED only; review hash cleared), submit-review (freezes candidate hash), simulate (exact hash), approve (independent approver with POLICY_APPROVE grant; separation of duties against every contributor; passed simulation of the exact candidate required; interval validation; half-open overlap check; explicit `close_predecessor` supersession; live mode requires reviewed gate evidence ids), return, activate (POLICY_ACTIVATE grant; service fence `SELECT ... FOR UPDATE`; SCHEDULED vs ACTIVE by effective time; activation epoch bump; ended predecessor RETIRED). Selection `select_policy` refuses 0 (POLICY_UNAVAILABLE) or >1 (POLICY_AMBIGUOUS) effective versions; nonbinding `evaluate_applicability` (API-019) returns exact documents or explicit uncertainty. Routing versions: `RoutingEntry` rows per artifact + `resolve_route` (specific beats wildcard, priority, equal-priority tie -> MULTIPLE_MATCH, NO_MATCH, INACTIVE_TARGET). Delegation (FR-10): beneficiary resolved by verified contact (enumeration-safe), delegate proposes, only the beneficiary confirms, revocation immediate, capabilities allowlisted, visibility selectors include active delegations. Premises API-010..013 (`UpdatePremises` with If-Match). APIs: `/services`, `/services/{id}/applicability`, `/policies` (+detail/patch/submit-review/simulate/approve/return/activate), `/delegations` (+confirm/revoke), `/premises` (+detail/patch). `seed_demo --scenario baseline --require-demo` (refuses outside demo): CENTRAL-PILOT, 3 queues, `demo-fire-noc`, 4 artifacts + 8 routing rows, 9 staff personas with fixed Keycloak ids (realm import pins the same ids), grants (Meera approve, Anita activate), applicant Rakesh + 4 premises, policy v1 taken through the real commands to ACTIVE (effective 2026-01-01). Web: UI-04 `/applicant/premises` (list, register, applicability preview with nonbinding badge), UI-24 `/policy` + `/policy/:id` (record, contributors, simulations, server-allowed actions with If-Match + idempotency key), workspace nav links only for granted workspaces. Tests: backend **122 passed** (AT-27-01/02/05 incl. self-approval blocked, stale hash, overlap, invalid interval, supersession boundary, immutability, ambiguity refusal, threaded activation-vs-submission on real PostgreSQL; AT-03 applicability; routing rules; AT-10-01..03 delegation; premises API idempotency/428/412/422/cross-owner 404), web **18 passed**; ruff/mypy strict/tsc/eslint clean; `makemigrations --check` clean. **Container proof PASS:** api image rebuilt, migrations applied on start, `seed_demo` in the container (v1 ACTIVE via kernel commands; rerun idempotent), Keycloak realm re-imported with fixed ids, `scripts/dev/smoke_policy.py` through nginx: applicant 15/15 (catalogue, OTP as Rakesh, applicability, premises idempotency/428/412, 403 on policies) and staff 7/7 (Meera via real Keycloak, policy list/detail, approve on ACTIVE -> 409 INVALID_TRANSITION). Evidence `handover.md` B7 EV-B04-01..08; record s.3f | Push `feat/b04-policy`, PR; then B05 |
| B05 | Drafts, files and application wizard | NOT_STARTED | None | Complete prerequisites and task card |
| B06 | Submission, routing and case visibility | NOT_STARTED | None | Complete prerequisites and task card |
| B07 | Assignment and appointment management | NOT_STARTED | None | Complete prerequisites and task card |
| B08 | Inspection reports and checklist evaluation | NOT_STARTED | None | Complete prerequisites and task card |
| B09 | Notices, responses and correction cycles | NOT_STARTED | None | Complete prerequisites and task card |
| B10 | Clocks, outbox dispatch and notifications | NOT_STARTED | None | Complete prerequisites and task card |
| B11 | Offline field application | NOT_STARTED | None | Complete prerequisites and task card |
| B12 | Decisions, issuance and verification | NOT_STARTED | None | Complete prerequisites and task card |
| B13 | Lifecycle, support and conditional routes | NOT_STARTED | None | Complete prerequisites and task card |
| B14 | Reporting, audit and operational UI | NOT_STARTED | None | Complete prerequisites and task card |
| B15 | Integration contracts and reconciliation | NOT_STARTED | None | Complete prerequisites and task card |
| B16 | Security and accessibility hardening | NOT_STARTED | None | Complete prerequisites and task card |
| B17 | Reliability, performance and recovery proof | NOT_STARTED | None | Complete prerequisites and task card |
| B18 | Production packaging and release evidence | NOT_STARTED | None | Complete prerequisites and task card |
| B19 | Full demonstration acceptance | NOT_STARTED | None | Complete prerequisites and task card |
| B20 | Agency pilot activation | NOT_STARTED | None | Complete prerequisites and task card |

## 3. Required handoff record

```text
Task: Bxx / requirement IDs / issue reference
Baseline: implementation spec 2.0.0
Branch and start commit:
Files inspected:
Changes made and architecture decisions:
Migrations/data impact:
Tests actually executed (exact command, environment and result):
Tests not executed and concrete reason:
Screens inspected (role, viewport, state):
Processes restarted and smoke-check result:
Security/privacy or external-effect considerations:
Remaining defects and reproduction:
Required human input (no secrets pasted into chat):
Next safe task:
End commit and worktree status:
```

## 3a. Handoff record - B00 session claude-20260910T150325Z-b00a (2026-09-10, partial)

```text
Task: B00 - Baseline and dependency lock (docs/17_AGENT_TASK_CARDS.md; docs/10_BUILD_GUIDE.md s.2-4)
Baseline: implementation spec 2.0.0
Branch and start commit: main @ 338248f (only commit); pre-existing unstaged deletion of root
  Agni_Setu_Interactive_Prototype.html and untracked docs pack preserved, not staged.
Files inspected: AGENTS.md, CLAUDE.md, README.md, handover.md, docs 00/04/10/12/14/17/18/20/21,
  references/README.md, MANIFEST.sha256.
Changes made and architecture decisions: added .gitignore; added docs/DEPENDENCY_LOCK.md
  (inspection, environment inventory, ADR-01..15 ACCEPTED for implementation, unresolved
  dependency/image tables, proof ledger, open items L-01..L-04); handover.md Part B updated;
  this row. No backend/, web/, infra/ created. No framework change.
Migrations/data impact: NONE.
Tests actually executed: `sha256sum -c MANIFEST.sha256` (repo root) -> PASS 30/30;
  `python --version` -> 3.12.7; `node --version` -> v24.14.1; `uname -a`, `df -h .` observed.
Tests not executed and concrete reason: git/docker/compose/uv/pnpm version probes, registry
  resolution, `uv lock`, `pnpm install`, `docker manifest inspect`, `manage.py check`,
  `pnpm build`, vulnerability scans - the Claude Code permission classifier was unavailable
  and rejected Bash (except trivial read-only commands) and all WebFetch calls 15:03-15:10Z.
Screens inspected: NONE (no UI exists).
Processes restarted and smoke-check result: NONE started.
Security/privacy or external-effect considerations: no secrets created; no network side effects.
Remaining defects and reproduction: NONE in code (no code). Environment deviation: Windows 11
  + Git Bash host vs guide-preferred Linux/macOS/WSL2 (DEPENDENCY_LOCK L-03).
Required human input: restore agent tool access (permission mode/allowlist); confirm
  Windows-native dev environment or provide WSL2 (L-03).
Next safe task: finish B00 (see DEPENDENCY_LOCK s.7-8). B01 not started.
End commit and worktree status: no commit made; new untracked files .gitignore,
  docs/DEPENDENCY_LOCK.md; modified docs/21_IMPLEMENTATION_STATUS.md, handover.md.
```

## 3b. Handoff record - B00 session claude-20260910T172516Z-b00b (2026-09-10, completion)

```text
Task: B00 - Baseline and dependency lock (docs/17_AGENT_TASK_CARDS.md; docs/10_BUILD_GUIDE.md s.2-4)
Baseline: implementation spec 2.0.0
Branch and start commit: main @ 338248f; work committed on feat/b00-baseline-lock (see handover B12).
Files inspected: AGENTS.md, CLAUDE.md, README.md, handover.md, docs 04/06/07/10/12/14/17/18/19/21,
  DEPENDENCY_LOCK.md, installed-tool metadata, registry tag lists (Docker Hub, quay.io).
Changes made and architecture decisions: backend/ (pyproject with bounded initial ranges, uv.lock,
  requirements.txt export, .python-version, manage.py, config/settings base/local/test/production,
  urls, wsgi, asgi, agni/platform/health.py, .env.example, README); web/ (package.json exact pins +
  packageManager pnpm@12.3.4, pnpm-lock.yaml, .nvmrc, index.html, vite.config.ts, tsconfig.json,
  src/main.tsx, App.tsx, vite-env.d.ts, design/global.css, README); infra/images.lock.json;
  evidence/README.md; .gitignore; docs/DEPENDENCY_LOCK.md completed; this file. Security-driven
  deviations DEV-01..03 (DRF 3.17.2, weasyprint 70.0, pytest 9.1.1) recorded in DEPENDENCY_LOCK s.9.
  No framework change; ADR-01..15 accepted.
Migrations/data impact: NONE (no models, no migrations, no database created).
Tests actually executed (repo root, Windows 11 host, 2026-09-10T18:27-19:1xZ):
  uv lock --directory backend -> Resolved 100 packages
  uv sync --frozen --directory backend -> Installed 98 packages
  uv run --directory backend python manage.py check -> System check identified no issues (0 silenced)
  uv run --directory backend ruff check . -> All checks passed!
  uv run --directory backend ruff format --check . -> 14 files already formatted
  uv run --directory backend mypy config agni -> Success: no issues found in 12 source files
  uv run --directory backend pip-audit -> No known vulnerabilities found (first run had 5; fixed)
  corepack pnpm install --dir web --frozen-lockfile -> Lockfile is up to date
  corepack pnpm --dir web typecheck -> PASS; corepack pnpm --dir web build -> built in 4.18s
  corepack pnpm --dir web audit --audit-level low -> No known vulnerabilities found
  docker buildx imagetools inspect x6 -> digests recorded
Tests not executed and concrete reason: no application tests exist yet (B01+); production.py
  negative test and health endpoint tests are B01 deliverables; no service was started (no Compose yet).
Screens inspected: NONE (hello-world shell built, not served).
Processes restarted and smoke-check result: NONE started.
Security/privacy or external-effect considerations: no secrets created (.env.example placeholders
  only); network use limited to PyPI, npm, Docker Hub, quay.io, GitHub; pip-audit findings resolved
  by upgrade, not suppression. Agent tooling installed at user scope per D-008 (see handover B10).
Remaining defects and reproduction: NONE known in code. Environment limits L-05 (RAM), L-06 (port
  5432), L-07 (ClamAV amd64-only) carried into B01 design.
Required human input: review/merge of the B00 PR; optional: raise Docker Desktop memory limit.
Next safe task: B01 - Repository and runnable skeleton.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3c. Handoff record - B01 session claude-20260910T172516Z-b00b (2026-09-10)

```text
Task: B01 - Repository and runnable skeleton (docs/17_AGENT_TASK_CARDS.md B01; build guide s.5-8, s.11)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b01-runnable-skeleton from feat/b00-baseline-lock @ 92faf9b
Files inspected: build guide s.5-12, deployment 12 s.1-5, API 06 s.1 + API-120..122, UI 03 s.1-4,
  engineering 18 s.3, architecture 04 s.5/s.9, DEPENDENCY_LOCK, images.lock.json.
Changes made and architecture decisions: infra/compose/compose.dev.yml (+README); infra/containers/
  {api,web}.Dockerfile; backend/docker-entrypoint.sh, .dockerignore; web/nginx/{default,
  security-headers}.conf, .dockerignore; scripts/dev/{_lib,up,down,doctor}.sh; scripts/ci/verify.sh;
  .github/workflows/ci.yml; backend settings (local/test read env files before base; production
  filters empty hosts), tests/{conftest,unit/*,integration/*}; web shell (router, providers,
  AppShell, HomePage w/ real readiness query, NotFound, RouteErrorBoundary, api client/errors/health,
  locales t(), tokens.css, global.css), eslint/vitest configs + tests, exact-pinned dev tooling;
  README quick start; DEPENDENCY_LOCK s.5; images.lock.json base images. Decision: local secrets
  file is `.env.local` (agent tooling guards `.env`); PostgreSQL host port 55432 default.
Migrations/data impact: only Django built-in apps' migrations applied to the LOCAL dev database
  (agni_dev) by the api container entrypoint; no project models yet.
Tests actually executed (Windows 11 host, 2026-09-10T19:3x-19:5xZ, all PASS unless noted):
  uv run --directory backend pytest tests -q -> 22 passed
  uv run --directory backend ruff check . / ruff format --check . / mypy config agni tests -> PASS
  corepack pnpm --dir web install --frozen-lockfile / lint / typecheck / test --run (10 passed) / build
  docker build api (543 MB) and web (94.1 MB) images
  docker compose -p agni-dev --env-file .env.local -f infra/compose/compose.dev.yml [--profile app]
    up -d --wait -> 6/6 healthy
  curl live -> {"status": "ok"}; ready -> 200 ready; via nginx :5173 -> 200; deep route -> 200;
  headers X-Content-Type-Options/X-Frame-Options/Referrer-Policy/Permissions-Policy present
Tests not executed and concrete reason: scripts/dev/*.sh and scripts/ci/verify.sh - every attempt
  to execute them was refused by the Claude Code auto-mode classifier (not by the OS); `full`
  profile (Keycloak, ClamAV) not started: Docker VM has 3 GB RAM (L-05); CI workflow not yet run
  (branch push pending at time of writing).
Screens inspected: web index via curl only (200, SPA shell); no browser screenshot this session.
Processes restarted and smoke-check result: web container rebuilt twice (pid path fix, headers
  fix) and re-probed healthy; api container healthy.
Security/privacy or external-effect considerations: containers non-root; all ports loopback;
  secrets only in gitignored .env.local / infra/volumes; production settings fail closed (tested);
  demo mode visibly labelled in UI footer.
Remaining defects and reproduction: NONE known. Risks: scripts unverified; rabbitmq needs ~60-90 s
  to boot on this VM (start_period 90s).
Required human input: review/merge PRs (gh not authenticated); optional Docker memory increase.
Next safe task: B02 - Domain persistence and command kernel.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3d. Handoff record - B02 session claude-20260910T172516Z-b00b (2026-09-10)

```text
Task: B02 - Domain persistence and command kernel (task card B02; docs 05 s.1-3/8, 06 s.1-5, 07 s.6, 08 s.2/7, 02 s.1-3/9, 18 s.2)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b02-command-kernel from feat/b01-runnable-skeleton @ e8ef365
Files inspected: docs 05 (full), 08 (full), 06 s.1-5, 02 s.1-3 + s.8-9, 07 s.6, 17 B02/B03, 18 s.2.
Changes made and architecture decisions: agni/platform/{apps,clock,errors,canonical,correlation,
  models,audit,outbox,locks,commands}.py, agni/platform/api/exceptions.py; agni/identity/{apps,models};
  agni/policies/{apps,models}; agni/routing/{apps,models}; agni/cases/{apps,models,domain/states,
  application/commands}; migrations platform/identity/routing 0001, policies 0001+0002, cases
  0001+0002 (Django split the policies<->routing and cases<->stage-instance cycles); settings:
  INSTALLED_APPS, AUTH_USER_MODEL=identity.Principal, RequestIdMiddleware first, DRF
  EXCEPTION_HANDLER, AGNI_CLOCK; pyproject ruff ignores (DJ001 with reason, migrations I001/E501).
  Decisions: receipt key hash stored as hex char(64) (equivalent to spec bytea); audit hash chain is
  per entity (serialised by the aggregate lock); principal fence is a separate 1:1 row; creation
  commands scope receipts to target_type "<command>:scope" + actor id; command_id is minted before
  apply so events can reference the receipt inside one transaction (deferred FK); replay is
  resolved before the version check (API s.4).
Migrations/data impact: 7 new migrations, forward-applied on LOCAL dev DB by the api container
  entrypoint (no data existed beyond Django core tables). No SQLite anywhere.
Tests actually executed (2026-09-10T20:2xZ, Windows host, Compose PostgreSQL 17.11):
  uv run --directory backend ruff format . -> unchanged; ruff check . -> All checks passed!
  uv run --directory backend mypy config agni tests -> Success: no issues found in 66 source files
  uv run --directory backend python manage.py check -> no issues; makemigrations --check -> No changes
  uv run --directory backend pytest tests -q -> 64 passed in 38.21s
  docker compose ... --profile app up -d --build --wait api -> healthy; migrations applied; ready 200
Tests not executed and concrete reason: API endpoints for the two commands are not exposed yet
  (sessions/CSRF arrive in B03); worker/dispatcher publish path is B10 (outbox rows written only).
Screens inspected: NONE (no UI change in B02).
Processes restarted and smoke-check result: api container rebuilt/restarted; /api/v1/health/ready 200.
Security/privacy or external-effect considerations: no role column; authority rechecked under fence;
  cross-scope reads answer 404 not 403; receipts never leak other principals' results; audit
  summaries carry safe fields only; no network calls inside transactions.
Remaining defects and reproduction: NONE known. Risk: per-entity audit chain does not chain across
  entities (documented); `Throttled.wait` read via getattr (DRF stub gap).
Required human input: review/merge PRs (gh not authenticated).
Next safe task: B03 - Identity, sessions and scoped permissions.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3e. Handoff record - B03 session claude-20260910T172516Z-b00b (2026-09-10)

```text
Task: B03 - Identity, sessions and scoped permissions (FR-01, FR-02; task card B03; docs 07 s.1-6,
  06 s.2 + API-001..007, 13 s.3, 03 UI-02/03, 11 AT-01/AT-02)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b03-identity from feat/b02-command-kernel @ 312bcb8
Files inspected: FR-01/02/10, security 07 s.1-6, API 06 s.2/s.7 + rows API-001..009, demo 13 s.3,
  UI 03 s.3 + UI-01/02/03, test plan AT-01-*/AT-02-*, build guide s.5 (issuer reachability).
Changes made and architecture decisions: agni/identity/{models (0002), domain/roles, contacts, otp,
  authz, sessions, backends, authentication, oidc, api/{views,urls}, application/commands,
  management/commands/provision_demo_staff}; agni/notifications/{models (0001), ports, adapters,
  api/demo_views}; agni/platform/api/views.ApiView (CSRF on all unsafe requests); agni/platform/
  errors explicit classes (+OTP codes); kernel aggregate bound VersionedModel | Principal;
  agni/cases/selectors; config settings (sessions, CSRF cookie readable, CACHES from CACHE_URL,
  OTP/OIDC settings incl. OIDC_METADATA_URL, TRUST_X_FORWARDED_FOR; production requires the three
  independent secrets + CACHE_URL); config/urls (identity routes, gated demo inbox);
  web src/api/auth.ts, features/identity/{useSession,SignInPage,AccountPage,RequireSession},
  router, AppShell, locales; infra: Keycloak realm import + backchannel-dynamic env, api
  OIDC_METADATA_URL, web depends_on restart, nginx resolver + $http_host; scripts/dev/
  smoke_identity.py; pyproject (+requests, authlib mypy override); DEPENDENCY_LOCK DEV-04.
  Decisions: contact plaintext stored Fernet-encrypted with HMAC lookup; OTP attempt counter is
  persisted before the failure is raised; sessions keep only policy facts; epoch mismatch flushes
  the session; NULL scope on a binding is never global; demo provisioning is a guarded command.
Migrations/data impact: identity 0002 (5 tables + principal.version), notifications 0001; applied
  on the LOCAL dev DB; synthetic smoke applicants and one demo staff mapping (chitra) exist there.
Tests actually executed (Windows host, 2026-09-10T20:5x-22:0xZ):
  uv run --directory backend ruff format/check, mypy config agni tests -> PASS (100 files)
  uv run --directory backend pytest tests -q -> 105 passed
  corepack pnpm --dir web lint/typecheck/test --run/build -> 0 problems, 15 passed, built
  docker compose ... up -d --build api web keycloak -> all healthy (keycloak 60 s boot)
  uv run --directory backend python ../scripts/dev/smoke_identity.py http://127.0.0.1:5173 --oidc
    -> ALL OTP SMOKE STEPS PASSED (11) and ALL OIDC SMOKE STEPS PASSED (9)
Tests not executed and concrete reason: browser/keyboard/viewport checks for UI-02/UI-03 (AT-01-06,
  AT-02-06) - Playwright suite arrives B16/B19; UI-21 (staff admin screen) is B14; SMS channel only
  through the demo sink (no provider); ClamAV not started (RAM).
Screens inspected: /sign-in and /account rendered in jsdom tests only; served bundle not opened in a
  browser this session.
Processes restarted and smoke-check result: api rebuilt 4x (requests dep, env, 503 mapping), web
  rebuilt 2x (resolver, Host header), keycloak recreated 2x (hostname URL) - all healthy after.
Security/privacy or external-effect considerations: codes never logged/returned; keyed MAC with
  dedicated pepper; limits fail closed; CSRF on anonymous login endpoints; sessions HttpOnly; issuer
  validation never disabled; demo inbox and demo provisioning absent when demo controls are off;
  Keycloak start-dev + synthetic users only.
Remaining defects and reproduction: NONE known. Note: Python cookie jars cannot log in to Keycloak
  over http (Secure cookies) - smoke script mimics browser localhost handling; browsers unaffected.
Required human input: review/merge PRs.
Next safe task: B04 - Service policy and master data.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3f. Handoff record - B04 session claude-20260910T172516Z-b00b (2026-09-10)

```text
Task: B04 - Service policy and master data (FR-03, FR-10, FR-27; task card B04; docs 02 s.6-7 +
  s.12, 05 policy tables, 24 form schemas, 19 gates, 06 API-010..013/018/019/095..102/123,
  13 s.1-4, 11 AT-03/AT-10/AT-27)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b04-policy from feat/b03-identity @ d2c2cab
Files inspected: FR-03/FR-10/FR-27, workflow s.6-7/s.12, data model policy tables, form schema
  catalogue, live gates (doc 19), API rows + DTOs, demo personas/premises (13 s.3-4), AT-03/10/27.
Changes made and architecture decisions: agni/policies/{models (0003), domain/schema.py,
  domain/simulation.py, selection.py, application/commands.py, api/{views,urls}.py,
  management/commands/seed_demo.py}; agni/routing/{models RoutingEntry (0002), resolution.py};
  agni/identity/{models Delegation (0003), domain/roles POLICY_ACTIVATE, application/
  delegations.py, api/delegation_views.py, api/urls}; agni/cases/{application/commands
  UpdatePremises + validate_premises_fields, api/{views,urls}, selectors (delegations)};
  agni/platform/api/views.ApiView.run_command (kernel bridge, ETag); config/urls; web
  src/api/{premises,services,policies}.ts, features/applicant/PremisesPage, features/policy/
  {PolicyListPage,PolicyDetailPage}, app/ProblemNotice, router, AppShell nav links, locales;
  infra/identity/realm-agni-dev.json (fixed user ids + 7 personas); scripts/dev/smoke_policy.py;
  pyproject (+jsonschema, +types-jsonschema dev); DEPENDENCY_LOCK DEV-05/06; requirements.txt.
  Decisions: (1) policy payload is validated data (JSON Schema 2020-12, additionalProperties
  false) - relational governance facts (preparer, approver, hashes) never live inside the JSON;
  (2) approval requires a passed simulation of the exact candidate hash and refuses every
  contributor (CREATE/EDIT) as approver; (3) intervals are half-open and never overlap; a
  successor may be approved with `close_predecessor: true`, which closes the single open-ended
  predecessor at the new effective_from (audited `policy.interval_closed`) - any other overlap
  is POLICY_INTERVAL_OVERLAP; (4) activation and submission share the service fence row so a
  submission pins the version effective at its instant (AT-27-05 threaded test); (5) selection
  with two effective versions raises POLICY_AMBIGUOUS instead of choosing; (6) the applicability
  preview is explicitly nonbinding (`binding: false`) and returns uncertainty for unknown
  categories; (7) delegations: proposer != confirmer, beneficiary resolved only through a
  verified contact, revocation immediate, history retained; (8) `_lock_policy` uses
  `select_for_update(of=("self",))` because PostgreSQL refuses FOR UPDATE on the nullable side
  of an outer join; (9) seed_demo drives v1 through the real commands (audit, receipts, outbox)
  rather than inserting an ACTIVE row.
Migrations/data impact: policies 0003 (public_summary, PolicyArtifact, PolicyVersion,
  PolicyContributor, PolicySimulation), routing 0002 (RoutingEntry), identity 0003 (Delegation +
  capability choices). Applied on the LOCAL dev DB by the api container; seed_demo baseline
  data (synthetic) present there.
Tests actually executed (Windows host, 2026-09-10T22:3x-23:2xZ):
  uv run --directory backend ruff format . && ruff check . && mypy config agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (124 files; no drift)
  uv run --directory backend pytest tests -q -> 122 passed (75.8 s; evidence/B04-backend-pytest.log)
  corepack pnpm lint / typecheck / test --run / build (web) -> 0 problems, tsc clean,
    18 passed (6 files; evidence/B04-web-vitest.log), built (394 kB JS)
  docker compose ... --profile app --profile full up -d --build api -> healthy; migrations
    policies 0003, identity 0003, routing 0002 applied by the entrypoint
  docker exec agni-dev-api-1 python manage.py seed_demo --scenario baseline --require-demo
    -> "policy v1 ACTIVE via kernel commands"; second run -> "already ACTIVE; chain skipped"
  docker compose ... run --rm --no-deps keycloak import --file //opt/keycloak/data/import/
    realm-agni-dev.json --override true -> realm re-imported with fixed user ids; restarted healthy
  uv run --directory backend python ../scripts/dev/smoke_policy.py http://127.0.0.1:5173 --oidc
    -> ALL APPLICANT SMOKE STEPS PASSED (15); staff phase timed out once at Keycloak cold start
    (15 s); rerun with --staff-only -> ALL STAFF SMOKE STEPS PASSED (7)
    (evidence/B04-smoke-policy.log, evidence/B04-smoke-policy-staff.log)
Tests not executed and concrete reason: PATCH /policies/{id} payload editor in the web UI (the
  API and command are tested; the screen shows the payload read-only until UI-24 editing lands
  with B14 admin tooling); browser/keyboard checks (Playwright arrives B16/B19); live-mode gate
  evidence path exercised only by unit assertion (no live policy exists by design).
Screens inspected: /applicant/premises and /policy/:id rendered in jsdom tests; served bundle
  not opened in a browser this session.
Processes restarted and smoke-check result: api container rebuilt with the B04 image
  (migrations 0003/0002/0003 applied on start); keycloak realm re-imported with fixed user ids;
  see EV-B04-04..06.
Security/privacy or external-effect considerations: no client-supplied role/state/approval flag
  is trusted; approval/activation need current grants at command time; SoD enforced in code and
  by DB constraint; seed and demo routes refuse outside demo mode; realm passwords are
  synthetic demo values in a dev-only realm file; contact plaintext stays encrypted.
Remaining defects and reproduction: NONE known.
Required human input: review/merge PRs (gh CLI not authenticated - BL-006).
Next safe task: B05 - Drafts, files and application wizard.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 4. Initial owner decisions and blockers

| ID | Required decision/input | Build impact | Safe current behavior |
| --- | --- | --- | --- |
| OPEN-01 | Agency-approved service applicability, building categories, form/checklist and valid source version | Blocks live intake | Use labelled demo profile and synthetic records only. |
| OPEN-02 | Actual ward/circle/service map and assignment authority | Blocks real routing | Fictional reviewed demo mapping; visible unresolved exception. |
| OPEN-03 | Qualified approving officers and delegations | Blocks live decisions | Synthetic separate actor/grant fixtures only. |
| OPEN-04 | Deadline, pause, holiday, deficiency and appeal rules | Blocks statutory timing/appeal activation | Explicit example clocks; disabled/referral conditional paths. |
| OPEN-05 | Certificate template, validity, lifecycle powers and digital-signing authority | Blocks live issuance/status instruments | Watermarked sample certificates; no unsigned-live fallback. |
| OPEN-06 | Identity provider, SMS/email and service credentials | Blocks real identity/delivery adapters | Local sinks and dev IdP; never request raw secrets in chat. |
| OPEN-07 | Hosting approval, retention/deletion and managed-device policy | Blocks sensitive live storage/offline mode | Isolated demo data; managed live requirements remain gated. |
| OPEN-08 | Existing agency-system ownership and partner contract/schema | Blocks real external import/registration | Documented adapter simulators and disabled source-specific connection. |
| OPEN-09 | Target hardware, users, throughput and accepted SLO/RPO/RTO | Blocks capacity/recovery claims | Measure proposed workload; revise by recorded evidence. |
| OPEN-10 | Exact patched dependency versions, image digests and license review | Blocks reproducible build completion | B00 resolves and records lock files; no `latest` deployment tags. |

An absent live credential does not block safe local implementation of domain logic and simulator contracts. It does block claiming that the real integration works. An absent authoritative rule must not be guessed by a coding agent.

## 5. Defect and specification issue ledger

Initially no implementation defects have been tested because the new application is not built. Do not label that "zero bugs." Create records with ISSUE-ID, affected rule/API/screen, observed versus expected, reproduction, impact, owner, status, test and evidence. A spec ambiguity becomes a documented decision/change before inconsistent code is merged.

## 6. Readiness labels

NOT_STARTED means no verified implementation evidence. IN_PROGRESS means changed work lacks full acceptance. BLOCKED means a concrete dependency prevents a required proof. READY_FOR_REVIEW means local evidence exists but independent review is pending. DONE means verified required evidence and review are recorded. DEFERRED requires approved scoped exclusion and a safe disabled user path. A live gate can never be marked DONE solely from demo-mode success.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
