# Agni Setu

Fire-safety certificate case management for a fire service: accountable application intake,
inspection evidence, information/deficiency loops, time-bound follow-up, reasoned decisions,
certificate publication and public verification. Seven role workspaces, eleven application
states, server-side authority for every decision.

**Stack:** Django 5.2 LTS + Django REST Framework + PostgreSQL 17 · React 19 + TypeScript + Vite 8 ·
Celery / RabbitMQ · Valkey · private S3-compatible object storage · Docker Compose.
**Status:** implementation in progress, phase by phase (see [implementation status](docs/21_IMPLEMENTATION_STATUS.md)).
This is a demonstration build; it is not an official government service and issues no real certificates.

## Quick start (Windows and macOS)

You need **Docker Desktop** (running), **Git**, and a POSIX shell: on macOS use Terminal; on Windows
use **Git Bash** (installed with Git for Windows). Everything else runs inside containers.

```bash
git clone https://github.com/Git-hub00/Agni-Setu.git
cd Agni-Setu
scripts/dev/doctor.sh        # checks Docker, ports and tooling; explains anything missing
scripts/dev/up.sh app        # generates .env.local with random secrets, starts infrastructure + api + web
```

Then open <http://localhost:5173>. The API answers at <http://127.0.0.1:8000/api/v1/health/ready>.
PostgreSQL is published on **127.0.0.1:55432** (5432 is often taken by a local install).
The `app` profile also starts the background job worker (document scans, notification delivery,
clock thresholds) and the scheduler (due-obligation scan, outbox dispatch). Add `full` for the
local staff identity provider (Keycloak) and the malware scanner (ClamAV, needs ~1.5 GB RAM):
`scripts/dev/up.sh app full`. Stop with `scripts/dev/down.sh`; data volumes are kept.
Details, profiles and memory notes: [infra/compose/README.md](infra/compose/README.md).

Load the synthetic demonstration data (jurisdiction, service, policy v1, personas, one applicant
with premises) once the api container is healthy:

```bash
docker exec agni-dev-api-1 python manage.py seed_demo --scenario baseline --require-demo
```

Demo sign-in: applicants use the one-time code shown in the local demo inbox
(`GET /api/v1/demo/inbox?channel=EMAIL&contact=<address>`); staff sign in through the local
Keycloak realm (`arjun`, `meera`, `anita`, ... with the demo passwords in
`infra/identity/realm-agni-dev.json`). Everything is synthetic; nothing is sent to a real inbox.
End-to-end smoke checks against the running stack live in `scripts/dev/smoke_*.py`.

### Developing on the host (optional)

For code changes with hot reload, run the infrastructure in Docker and the app on your machine.
Toolchain: Python 3.12, [uv](https://docs.astral.sh/uv/) 0.11.x, Node 24 LTS (pnpm comes via corepack).

```bash
scripts/dev/up.sh                                   # infrastructure only
cd backend && uv sync --frozen && uv run python manage.py migrate && uv run python manage.py runserver 127.0.0.1:8000
cd web && corepack pnpm install --frozen-lockfile && corepack pnpm dev      # http://localhost:5173, proxies /api
```

`backend/requirements.txt` is exported from `uv.lock` for readers without uv; the lockfiles are authoritative.
Run every quality gate with `scripts/ci/verify.sh` (lint, types, tests, build, Compose validation).

### Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | Django project (`config/`), business modules (`agni/`), tests, `uv.lock` |
| `web/` | React/TypeScript SPA, `pnpm-lock.yaml`, nginx config for the container |
| `infra/` | Compose stack, Dockerfiles, `images.lock.json` (digest-pinned images) |
| `scripts/` | `dev/` (doctor, up, down), `ci/verify.sh` |
| `docs/` | Implementation specification 2.0.0 (this pack) and the dependency lock record |
| `references/` | Read-only HTML prototype used as the visual reference |
| `handover.md` | Live agent handover record (Part A fixed, Part B updated every session) |

---

# Implementation documentation pack

**Version 2.0.0 | 09 September 2026 | Target: Codex, Claude Code and human engineers**

## Start here

Build the real application behind the existing Agni Setu product design: accountable application intake, inspection evidence, information/deficiency loops, time-bound follow-up, reasoned decisions, certificate publication/verification and operational governance. Keep the seven workspaces and eleven-state lifecycle. This is an implementation specification, not a codebase or claim of government deployment.

The selected greenfield stack is **Django 5.2 LTS + Django REST Framework + PostgreSQL 17**, with a **React 19/TypeScript/Vite 8** frontend, **Celery/RabbitMQ** background execution, **Valkey** disposable caching, and **private S3-compatible object storage**. This explicitly supersedes the earlier Flask/MongoDB proposal for a new build; do not silently migrate an existing repository without assessment. Rationale, alternatives, module structure, dependency policy and operating tradeoffs are in documents04 and14.

## Use with an empty or existing project

Extract this folder. Place its `AGENTS.md`, `CLAUDE.md`, `docs/` and `references/` in the project root. In an existing repository, inspect and merge instructions rather than overwriting existing files. Keep the HTML under references as a read-only visual/interaction example; do not use its localStorage as the real application database.

Read this README, [AGENTS.md](AGENTS.md), [product scope](docs/00_PRODUCT_AND_SCOPE.md), [architecture](docs/04_TECHNICAL_ARCHITECTURE.md), [build guide](docs/10_BUILD_GUIDE.md) and [current status](docs/21_IMPLEMENTATION_STATUS.md). Then read only the assigned task card and relevant detailed contracts before coding. The complete pack is intentionally too detailed to paste blindly into every prompt.

### First instruction to Codex or Claude Code

```text
Read AGENTS.md, README.md and docs/21_IMPLEMENTATION_STATUS.md.
Inspect this repository before making changes; preserve unrelated work.
Use implementation baseline 2.0.0 and the HTML in references/ as the visual reference.
Read docs/00_PRODUCT_AND_SCOPE.md, docs/04_TECHNICAL_ARCHITECTURE.md,
docs/10_BUILD_GUIDE.md and the B00 task card in docs/17_AGENT_TASK_CARDS.md.
Execute B00 only: verify environment, inspect existing code, select supported exact
patch versions and image digests, resolve compatibility/licenses, and document locks.
Do not invent statutory rules, credentials, test results or live government connections.
Use safe local adapters and synthetic fixtures; do not send real SMS or issue real certificates.
Report what you inspected, changed and actually tested, then update the status ledger
with evidence and the next safe task. Stop for review before B01.
```

### Continue instruction after each phase

```text
Read the latest AGENTS.md and implementation status. Verify prior phase evidence.
Complete the next approved Bxx task and its dependencies only. Read the task's functional,
workflow, UI, API, data, security and test sections before implementation.
Implement the vertical slice with real persistence, authorization, happy/error/recovery
paths and tests. Do not bypass required guards to make a demonstration pass.
Run relevant tests, restart affected processes, inspect relevant screens and record
honest evidence. Update the handoff/status. Do not claim unexecuted tests passed.
```

## Reading map

| Document | Link |
| --- | --- |
| Product And Scope | [Open 00](docs/00_PRODUCT_AND_SCOPE.md) |
| Functional Specification | [Open 01](docs/01_FUNCTIONAL_SPECIFICATION.md) |
| Workflow And Policy Specification | [Open 02](docs/02_WORKFLOW_AND_POLICY_SPECIFICATION.md) |
| Ui Ux Specification | [Open 03](docs/03_UI_UX_SPECIFICATION.md) |
| Technical Architecture | [Open 04](docs/04_TECHNICAL_ARCHITECTURE.md) |
| Data Model And Migrations | [Open 05](docs/05_DATA_MODEL_AND_MIGRATIONS.md) |
| Api And Event Contracts | [Open 06](docs/06_API_AND_EVENT_CONTRACTS.md) |
| Security Privacy And Access | [Open 07](docs/07_SECURITY_PRIVACY_AND_ACCESS.md) |
| Async Jobs And Error Recovery | [Open 08](docs/08_ASYNC_JOBS_AND_ERROR_RECOVERY.md) |
| Offline Inspection And Sync | [Open 09](docs/09_OFFLINE_INSPECTION_AND_SYNC.md) |
| Build Guide | [Open 10](docs/10_BUILD_GUIDE.md) |
| Test Plan And Acceptance | [Open 11](docs/11_TEST_PLAN_AND_ACCEPTANCE.md) |
| Deployment And Operations | [Open 12](docs/12_DEPLOYMENT_AND_OPERATIONS.md) |
| Demo Data And Scenarios | [Open 13](docs/13_DEMO_DATA_AND_SCENARIOS.md) |
| Architecture Decisions | [Open 14](docs/14_ARCHITECTURE_DECISIONS.md) |
| Requirements Traceability | [Open 15](docs/15_REQUIREMENTS_TRACEABILITY.md) |
| Integrations And Certificates | [Open 16](docs/16_INTEGRATIONS_AND_CERTIFICATES.md) |
| Agent Task Cards | [Open 17](docs/17_AGENT_TASK_CARDS.md) |
| Engineering Standards | [Open 18](docs/18_ENGINEERING_STANDARDS.md) |
| Policy And Live Activation Gates | [Open 19](docs/19_POLICY_AND_LIVE_ACTIVATION_GATES.md) |
| Source Register And Glossary | [Open 20](docs/20_SOURCE_REGISTER_AND_GLOSSARY.md) |
| Implementation Status | [Open 21](docs/21_IMPLEMENTATION_STATUS.md) |
| Documentation Qa | [Open 22](docs/22_DOCUMENTATION_QA.md) |
| Prototype Coverage | [Open 23](docs/23_PROTOTYPE_COVERAGE.md) |
| Form Schemas And Validation | [Open 24](docs/24_FORM_SCHEMAS_AND_VALIDATION.md) |

The primary requested documents are [Functional specification](docs/01_FUNCTIONAL_SPECIFICATION.md), [Technical architecture](docs/04_TECHNICAL_ARCHITECTURE.md) and [Build guide](docs/10_BUILD_GUIDE.md). The other documents make those specifications implementable instead of leaving database, UI, failure and test behavior implicit.

## What is fixed and what is pending

Product state/role semantics and engineering safety invariants are fixed by this baseline. Technology families are selected, but exact patched versions, lockfiles and image digests must be installed/tested during B00. Example timing/fees/applicability/validity and capacity figures are not government-approved rules or achieved results. Live activation requires document19 approval evidence. Safe development does not require real customer data.

The initial build covers the complete selected demo product, including offline failed visits, exceptions, job recovery, policy governance and public verification. Payments, legal appeals, external registration and continuing declarations have explicit conditional contracts and safe disabled/referral behavior until a real profile/authority is approved. AI approval, emergency dispatch, IoT, native mobile apps and multi-state infrastructure are not silently added.

## Document authority and change control

For product behavior: scope00, functional01 and workflow02 govern; interface/data contracts05/06/24 govern implementation details; UI03 must express those rules. ADR14 records deliberate technical choices. Sources20 provide provenance but do not override newly approved baseline decisions. If any two normative sections disagree, record a specification issue and resolve it explicitly; do not infer precedence to weaken safety. New approved changes update affected specs, API schemas, tests, prototype mapping and status together.

A state transition must have current scoped authorization, policy/authority checks, immutable accepted evidence, a version precondition and transactional event/audit/outbox when relevant. All external effects need retry-safe stable identities and explicit unknown-outcome recovery. Browser validation and hidden buttons are not security boundaries.

## Contents and verification

The archive contains Markdown documentation plus the existing self-contained HTML visual reference. Planned commands, models and endpoints are build contracts, not delivered implementation code. [Documentation QA](docs/22_DOCUMENTATION_QA.md) reports checks actually performed on this documentation. [Implementation status](docs/21_IMPLEMENTATION_STATUS.md) starts NOT_STARTED/NOT_RUN for the new backend.

Do not upload secrets, production databases, confidential premises documents or identity keys to agents. Supply secrets through approved local environment/secret storage. Do not copy old test credentials into deployment defaults.
