# Dependency lock record (B00)

**Agni Setu implementation baseline 2.0.0 | started 2026-09-10**  
**Status:** READY_FOR_REVIEW (2026-09-10T19:1xZ) - all B00 proofs EV-B00-02..08 executed and passing on the current uncommitted tree; lockfiles `backend/uv.lock`, `web/pnpm-lock.yaml`, `infra/images.lock.json` present. Remaining `NOT_RESOLVED` rows (workbox, vitest/playwright/axe, eslint) are deliberately deferred to the phase that first needs them. Nothing in this file is a claim that an install or build has passed unless an evidence ID in section 7 says so.

This record satisfies `docs/10_BUILD_GUIDE.md` s.4 and task card B00 in `docs/17_AGENT_TASK_CARDS.md`. Family selections come from `docs/04_TECHNICAL_ARCHITECTURE.md` s.2 and are fixed by the baseline; exact patches below are resolved during B00 against official registries and compatibility-tested before being recorded as locked. Only the initial controlled resolution may use bounded ranges; subsequent installs use frozen lockfiles (`backend/uv.lock`, `web/pnpm-lock.yaml`, `infra/images.lock.json`).

## 1. Repository inspection (verified 2026-09-10)

| Item | Observed |
| --- | --- |
| Repository root | `f:\Gowtham\Agni` (Git Bash `/f/Gowtham/Agni`) |
| Branch / HEAD | `main` @ `338248f prototype of agni setu` (single commit) |
| Existing application code | NONE. Only the documentation pack, `references/` prototype HTML and `handover.md`. No `backend/`, `web/`, `infra/`, `pyproject.toml`, `package.json`, lockfiles or migrations existed before B00. |
| Existing stack to compare | NONE - greenfield. No conflicting architecture was found, so the stack ADRs can be accepted without a replacement decision (section 3). |
| Pre-existing uncommitted user work | Unstaged deletion of root `Agni_Setu_Interactive_Prototype.html` (byte-identical copy kept at `references/`); untracked docs pack. Preserved; not staged or reverted by B00. |
| Documentation pack integrity | `sha256sum -c MANIFEST.sha256` -> 30/30 OK (EV-001). `references/Agni_Setu_Interactive_Prototype.html` = `5928bc6487a9e2af46fd636ac2258cd207bccee0d5ea36d69e8c0a4f6a226180`, matching source register S02. |

## 2. Local environment inventory

Preferred environment per build guide s.2 is Linux/macOS/WSL2. The actual host is Windows 11 with Git Bash; see OPEN item L-03 in section 8.

| Tool | Required family | Observed | Evidence / command | State |
| --- | --- | --- | --- | --- |
| OS | Linux, macOS or WSL2 preferred | Windows 11 Home 10.0.26200, x86_64; shell MINGW64 (Git Bash, MSYS 3.4.10) | `uname -a` | OBSERVED (deviation, L-03) |
| Git | any recent | Git for Windows 2.45.2.windows.1 (package `mingw-w64-x86_64-git 2.45.2.1.91d03cb2e4-1`) | file inspection 2026-09-10T17:28Z: `C:\Program Files\Git\etc\package-versions.txt`; `git --version` NOT_RUN (gate) | OBSERVED (installed metadata; CLI confirmation pending, L-01) |
| Docker + Compose v2 | Docker Engine with Compose v2 | Docker Desktop 4.50.0 (build 209931); Docker CLI 28.5.1; Engine 28.5.1; Compose v2.40.3-desktop.1; buildx plugin present; Linux VM kernel v6.11.11 | file inspection 2026-09-10T17:28Z: `C:\Program Files\Docker\Docker\resources\componentsVersion.json`; `docker version`/`docker compose version` and daemon reachability NOT_RUN (gate) | OBSERVED (installed metadata; daemon reachability pending, L-01) |
| Python | 3.12.x | Python 3.12.7 (Windows CPython) | `python --version` | OBSERVED |
| uv | pinned release | uv 0.11.28 (installed by the official astral-sh cargo-dist installer, flat layout) | file inspection 2026-09-10T17:28Z: `C:\Users\realg\AppData\Local\uv\uv-receipt.json`; `uv --version` NOT_RUN (gate) | OBSERVED (installed metadata; CLI confirmation pending, L-01) |
| Node.js | 24 LTS | v24.14.1 | `node --version` | OBSERVED |
| pnpm | pinned release | only corepack 0.34.6 shim at `C:\Program Files\nodejs\node_modules\corepack\shims\pnpm.cmd`; no standalone install found | file inspection 2026-09-10T17:28Z: `C:\Program Files\nodejs\node_modules\corepack\package.json`; `pnpm --version` NOT_RUN (gate) | corepack OBSERVED; pnpm exact version to be pinned via `packageManager` field from registry resolution (L-02) |
| RAM | 16 GB planning guidance (8 GB reduced profile) | **5.9 GB total host RAM**; Docker Desktop Linux VM: 4 CPUs, 3.0 GB memory (`docker info`: 3019096064 bytes) | PowerShell `Get-CimInstance Win32_OperatingSystem`; `docker info` 2026-09-10T18:28Z (EV-B00-02) | OBSERVED - BELOW the guide's 8 GB reduced-profile guidance. See L-05: only the minimal infrastructure profile is expected to fit locally; Keycloak + ClamAV (full profile) must be validated separately or run on a larger host/CI |
| Free disk | >= 20 GB planning allowance | 157 GB free on F: (235 GB total) | `df -h .` | OBSERVED, satisfies allowance |
| Occupied ports | 5173, 8000, 5432, 5672, 15672, 6379, 8333, 8080, 3310 must be free or overridden | **5432 is occupied** (LISTENING on 0.0.0.0 and [::], PID 6388 - a pre-existing host process, not touched); all other listed ports free | `netstat -ano` 2026-09-10T18:28Z (EV-B00-02) | OBSERVED - L-06: Compose must publish PostgreSQL on a documented override host port (default `55432`), never kill the unknown process (build guide s.12) |
| WSL2 | optional alternative environment | `wsl --status`: default distribution **Ubuntu**, default version 2 (CORRECTION of the 17:28Z file-inspection note, which found no Store package and wrongly concluded no distro) | `wsl --status` 2026-09-10T18:28Z (EV-B00-02) | OBSERVED - a WSL2 Ubuntu exists; D-002/D-004 still apply (host-native authoring, containerized runtime) |
| pnpm (resolved) | pinned release | pnpm **12.3.4** downloaded by corepack 0.34.6 (`Downloading the pnpm 12.3.4 binary for win32-x64`) | `corepack pnpm --version` 2026-09-10T18:28Z (EV-B00-02) | OBSERVED - to be pinned as `"packageManager": "pnpm@12.3.4"` in `web/package.json` |
| Docker daemon | reachable, linux/amd64 | Server 28.5.1, `linux/x86_64` | `docker info` 2026-09-10T18:28Z | OBSERVED |

## 3. Architecture decision acceptance

`docs/14_ARCHITECTURE_DECISIONS.md` requires B00 to record acceptance or a reasoned alternative. Basis: the user-authorized baseline 2.0.0 selects this stack; repository inspection found no existing code or competing architecture; therefore no replacement decision is needed.

| ADR | Decision | B00 disposition | Note |
| --- | --- | --- | --- |
| ADR-01 | Django/DRF modular monolith | ACCEPTED for implementation | Greenfield; no Flask code to inventory. |
| ADR-02 | PostgreSQL rather than MongoDB | ACCEPTED | No MongoDB data exists; no migration claimed. |
| ADR-03 | SPA + PWA in one React codebase | ACCEPTED | Offline behavior to be browser-tested at B11. |
| ADR-04 | Server sessions with OIDC/OTP adapters | ACCEPTED | CSRF/Origin controls required from B03. |
| ADR-05 | Policy and authority are versioned data | ACCEPTED | No statutory power inferred from role. |
| ADR-06 | SQL outbox and persistent obligations | ACCEPTED | At-least-once delivery; reconciliation required. |
| ADR-07 | RabbitMQ transport; Valkey disposable | ACCEPTED | Images to be digest-pinned (section 6). |
| ADR-08 | Private supported S3; local SeaweedFS mini | ACCEPTED | SeaweedFS is dev/test only. |
| ADR-09 | Guarded commands instead of status PATCH | ACCEPTED | - |
| ADR-10 | Conflict-aware offline operations | ACCEPTED | - |
| ADR-11 | Favorable decision distinct from publication | ACCEPTED | - |
| ADR-12 | Scoped SQL reports first | ACCEPTED | - |
| ADR-13 | No autonomous AI in the safety decision loop | ACCEPTED | - |
| ADR-14 | Near-real-time polling baseline | ACCEPTED | - |
| ADR-15 | Demo/live separation enforced in code and deployment | ACCEPTED | - |

Acceptance here is an implementation-team disposition recorded by the B00 agent under the user's authorization of baseline 2.0.0; it is not government or product-owner approval of any policy content.

## 4. Python (backend) dependency candidates

Resolution source: PyPI JSON API and each project's release notes. Columns are filled only from actual registry responses and actual `uv lock` output. Bounded ranges are the initial resolution constraint; the exact version comes from `backend/uv.lock`.

| Package | Family constraint (spec) | Resolved exact version | Registry source | License | Vulnerability disposition | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Python interpreter | 3.12.x | 3.12.7 (host); `backend/.python-version` = `3.12`; `requires-python = ">=3.12,<3.13"` | python.org | PSF-2.0 | n/a | `uv lock` output "Using CPython 3.12.7" |
| Django | `>=5.2,<5.3` (LTS) | **5.2.17** | PyPI via `uv lock` | BSD-3-Clause | pip-audit: no advisory | EV-B00-03 |
| djangorestframework | spec `>=3.16,<3.17`; **locked constraint `>=3.17.2,<3.18`** | **3.17.2** | PyPI via `uv lock` | BSD-3-Clause | 3.16.1 flagged PYSEC-2026-3827 + PYSEC-2026-3828 (fix 3.17.2) -> upgraded; see s.9 DEV-01 | EV-B00-03, EV-B00-08 |
| psycopg[binary] | `>=3,<4` | **3.3.5** (+ psycopg-binary 3.3.5) | PyPI via `uv lock` | LGPL-3.0 | no advisory | EV-B00-03 |
| drf-spectacular | compatible with Django 5.2 / DRF 3.17 | **0.30.0** | PyPI via `uv lock` | BSD-3-Clause | no advisory | resolved together with DRF 3.17.2 without conflict |
| django-environ | current | **0.14.0** | PyPI via `uv lock` | MIT | no advisory | no py.typed -> mypy override in pyproject |
| Authlib | current (Django OIDC client) | **1.8.0** | PyPI via `uv lock` | BSD-3-Clause | no advisory | EV-B00-03 |
| requests (added B03) | `>=2.32,<3` | **2.34.2** (already transitive via pip-audit; now a direct runtime dependency) | PyPI via `uv lock` | Apache-2.0 | no advisory | s.9 DEV-04: Authlib's Django client imports `requests` at runtime; the production image (no dev group) failed to boot without it (EV-B03-05) |
| jsonschema (added B04) | `>=4.23,<5` | **4.26.0** (already transitive; now a direct runtime dependency) | PyPI via `uv lock` | MIT | no advisory | s.9 DEV-05: policy packages are validated against a Draft 2020-12 JSON Schema (workflow s.6) |
| types-jsonschema (added B04, dev) | `>=4.23,<5` | **4.26.0.20260518** | PyPI via `uv lock` | Apache-2.0 | n/a | dev; s.9 DEV-06: mypy strict needs the stubs |
| celery | `5.6` compatible stable patch | **5.6.3** (kombu 5.6.2, amqp 5.3.1, billiard 4.2.4) | PyPI via `uv lock` | BSD-3-Clause | no advisory | L-04 CLOSED: 5.6.x exists on PyPI |
| boto3 | current | **1.43.91** (botocore 1.43.91, s3transfer 0.19.2) | PyPI via `uv lock` | Apache-2.0 | no advisory | EV-B00-03 |
| redis (Valkey client, Redis protocol) | current | **6.4.0** | PyPI via `uv lock` | MIT | no advisory | EV-B00-03 |
| weasyprint | current; **locked constraint `>=70,<71`** | **70.0** | PyPI via `uv lock` | BSD-3-Clause | 69.0 flagged PYSEC-2026-3940 (fix 70.0) -> upgraded; s.9 DEV-02 | EV-B00-08. Windows host needs GTK/Pango only to *render*; import/check works. Rendering runs in Linux containers (D-004) |
| qrcode[pil] | current | **8.2** (pillow 12.3.0) | PyPI via `uv lock` | BSD | no advisory | EV-B00-03 |
| gunicorn | current (production API serving) | **23.0.0** | PyPI via `uv lock` | MIT | no advisory | POSIX-only; runs in containers, not on the Windows host |
| pytest | current; **locked constraint `>=9.0.3,<10`** | **9.1.1** | PyPI via `uv lock` | MIT | 8.4.2 flagged PYSEC-2026-1845 (fix 9.0.3) -> upgraded; s.9 DEV-03 | dev; EV-B00-08 |
| pytest-django | current | **4.14.0** | PyPI via `uv lock` | BSD-3-Clause | no advisory | dev |
| hypothesis | current | **6.168.0** | PyPI via `uv lock` | MPL-2.0 | no advisory | dev |
| ruff | current | **0.16.7** | PyPI via `uv lock` | MIT | no advisory | dev; `ruff check` + `ruff format --check` PASS (EV-B00-04) |
| mypy | current | **1.19.1** | PyPI via `uv lock` | MIT | no advisory | dev; strict mode + django plugin |
| django-stubs[compatible-mypy] | compatible with Django 5.2 + mypy | **5.2.9** (django-stubs-ext 6.1.0) | PyPI via `uv lock` | MIT | no advisory | dev |
| djangorestframework-stubs | compatible with DRF 3.17 | **3.16.9** | PyPI via `uv lock` | MIT | no advisory | dev; resolved fine against DRF 3.17.2 |
| pip-audit | current | **2.10.1** | PyPI via `uv lock` | Apache-2.0 | n/a | dev; the audit tool itself |
| uv (tool) | pinned release | **0.11.28** (ebf0f43d7 2026-07-07 x86_64-pc-windows-msvc) | astral-sh GitHub release (cargo-dist installer) | Apache-2.0 OR MIT | n/a | EV-B00-02 |

Transitive dependencies (100 packages total) are captured only by `backend/uv.lock`; this table lists direct dependencies. `backend/requirements.txt` is a convenience export (`uv export --frozen --no-dev --no-hashes`) for readers who do not use uv; `uv.lock` remains authoritative and CI uses `uv sync --frozen`. License values are the well-known upstream licenses of each project as published on PyPI; no license-compliance review beyond identification has been performed (all are permissive or LGPL-as-library).

## 5. Node (web) dependency candidates

Resolution source: npm registry. Exact versions come from `web/package.json` (exact pins, no `^`) and `web/pnpm-lock.yaml`.

| Package | Family constraint (spec) | Resolved exact version | License | Vulnerability disposition | Evidence |
| --- | --- | --- | --- | --- | --- |
| Node.js runtime | 24 LTS | v24.14.1 (host); `web/.nvmrc` = `24`; `engines.node = ">=24.0.0 <25"` | MIT-style (Node license) | n/a | `node --version` |
| pnpm | pinned release via `packageManager` | **12.3.4** (`"packageManager": "pnpm@12.3.4"`, fetched by corepack 0.34.6) | MIT | n/a | EV-B00-02 |
| react / react-dom | 19.x stable | **19.3.0** / **19.3.0** | MIT | pnpm audit: none | EV-B00-05 |
| @types/react / @types/react-dom | match React 19 | **19.3.0** / **19.3.0** | MIT | none | dev |
| typescript | current stable, strict mode | **5.9.3** | Apache-2.0 | none | dev; `tsc --noEmit` PASS |
| vite | 8.x stable | **8.2.2** (rolldown 1.2.8 binding) | MIT | none | EV-B00-06 build PASS |
| @vitejs/plugin-react | compatible with Vite 8 | **5.2.0** | MIT | none | dev |
| tailwindcss + @tailwindcss/vite | 4.x | **4.3.3** / **4.3.3** | MIT | none | dev; `@theme` tokens compile |
| radix-ui (unified primitives package) | current, React 19 compatible | **1.6.7** | MIT | none | EV-B00-05 |
| react-router | 7.x (SPA/browser router mode) | **7.18.3** | MIT | none | EV-B00-05 |
| @tanstack/react-query | 5.x | **5.102.8** | MIT | none | EV-B00-05 |
| react-hook-form | 7.x | **7.87.0** | MIT | none | EV-B00-05 |
| zod | 4.x compatible | **4.5.4** | MIT | none | EV-B00-05 |
| dexie | 4.x | **4.4.5** | Apache-2.0 | none | EV-B00-05 |
| workbox (via vite-plugin-pwa or explicit build) | Vite-compatible SW build | NOT_RESOLVED - deferred to B11 (first phase that needs a service worker); will be added through the same lock discipline | MIT | NOT_RUN | B11 |
| vitest / jsdom | current | **5.0.0** / **30.0.1** (B01) | MIT | none | dev; unit tests |
| @testing-library/react / jest-dom / user-event | current | **16.3.3** / **7.0.1** / **14.6.7** (B01) | MIT | none | dev |
| eslint / @eslint/js / typescript-eslint / globals | current | **10.10.0** / **10.0.1** / **8.70.0** / **17.12.0** (B01) | MIT | none | dev; flat config, type-checked rules |
| eslint-plugin-react-hooks / eslint-plugin-jsx-a11y | current | **7.1.1** / **6.10.2** (B01) | MIT | none | dev |
| axe-core, @playwright/test | current | NOT_RESOLVED - added at B16/B19 with browser and accessibility suites | MPL-2.0 / Apache-2.0 | NOT_RUN | dev; later phases |

164 packages were locked at B00; B01 added the test/lint tooling above (lockfile regenerated from exact specifiers, frozen install verified) in `web/pnpm-lock.yaml` (lockfile regenerated from exact specifiers; `pnpm install --frozen-lockfile` reproduces - EV-B00-05). `pnpm audit --audit-level low`: "No known vulnerabilities found" (EV-B00-08). License values are the well-known upstream licenses; identification only, no formal compliance review.

## 6. Container images (`infra/images.lock.json`)

Digests must come from the registry (`docker manifest inspect` or registry API), never typed from memory. Record architecture (linux/amd64 for this host; verify multi-arch for Apple Silicon developers).

| Service | Image family (spec) | Selected tag | Digest | Architectures | Evidence |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL | `postgres` 17.x latest supported minor | **17.11** (Docker Hub newest 17.x on 2026-09-10; debian trixie-slim base) | index `sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675` | amd64, arm64/v8 (+arm/v5, arm/v7, 386, ppc64le, riscv64, s390x) | EV-B00-07 |
| RabbitMQ | `rabbitmq` 4.x-management with bundled matching Erlang | **4.3.5-management** (newest 4.x line; official image bundles matching Erlang) | index `sha256:57bddb6fbc3498b5d8b5a14dc6f4506073ebcf94c66ba2a7678c335faa8dd631` | amd64, arm64/v8 (+arm/v7, ppc64le, riscv64, s390x) | EV-B00-07 |
| Valkey | `valkey/valkey` 8.1.x | **8.1.10** | index `sha256:3fbd2e3e4b6e85e046c1e7c215e8f79087bc0357789184305806664e320996f3` | amd64, arm64 (+arm/v7, ppc64le) | EV-B00-07 |
| SeaweedFS (local S3 emulator only) | `chrislusf/seaweedfs` pinned release | **4.46** (newest plain release tag 2026-09-08; the 3.x line ended at 3.99 in 2025-10) | index `sha256:08d516132314207d10c8e37cbffc1f32b147d870169688734cc61c6231625b62` | amd64, arm64 (+386, arm/v7) | EV-B00-07; dev/test only (ADR-08) |
| Keycloak (local OIDC, full profile) | `quay.io/keycloak/keycloak` 26.x | **26.7.3** | index `sha256:ff4257d0d64efbe99ed1ddfaf07765cc3c36dc7518bf8324d41961327f441c54` | amd64, arm64 (+ppc64le) | EV-B00-07; start-dev never used live |
| ClamAV (full profile) | `clamav/clamav` stable | **1.5.4** (newest 1.5.x; 1.4.6 is the LTS alternative) | index `sha256:1fdfd24c6f0a0fb60788481487459a6d4eda8a9b448641594e04db8410d34422` | **amd64 only** | EV-B00-07; arm64 hosts (Apple Silicon) need emulation or the scanner simulator - BL-005 |

Machine-readable copy: `infra/images.lock.json`. Compose files reference `<image>@<index_digest>` so the same lock resolves on Windows/amd64 and macOS/arm64 hosts (D-004), except ClamAV as noted.

## 7. Compatibility proof (required by task card B00)

| Evidence ID | Check | Exact command + cwd | Result | Notes |
| --- | --- | --- | --- | --- |
| EV-001 | Documentation pack checksums | `sha256sum -c MANIFEST.sha256` in repo root | PASS 30/30 | 2026-09-10 |
| EV-002 | Runtime versions | `python --version`; `node --version`; `uname -a`; `df -h .` | PASS (observed values in s.2) | 2026-09-10 |
| EV-B00-01 | Toolchain versions from installed metadata (CLI probes gated) | Read `C:\Program Files\Git\etc\package-versions.txt`, `C:\Program Files\Docker\Docker\resources\componentsVersion.json`, `%LOCALAPPDATA%\uv\uv-receipt.json`, `C:\Program Files\nodejs\node_modules\corepack\package.json`; Glob for WSL distro packages | OBSERVED: Git 2.45.2.windows.1; Docker Desktop 4.50.0 / Engine+CLI 28.5.1 / Compose v2.40.3-desktop.1; uv 0.11.28; corepack 0.34.6; no WSL distro | 2026-09-10T17:28Z. File inspection, not command output; `--version` CLI confirmation still NOT_RUN (BL-002) |
| EV-B00-02 | Toolchain versions by CLI (confirms EV-B00-01) | `uv --version && git --version && corepack --version && docker version && docker compose version`; `corepack pnpm --version`; `wsl --status`; PowerShell RAM; `netstat -ano`; `docker info` (repo root) | PASS: uv 0.11.28; git 2.45.2.windows.1; corepack 0.34.6; Docker 28.5.1/28.5.1; Compose v2.40.3-desktop.1; pnpm 12.3.4; WSL Ubuntu v2; RAM 5.9 GB; port 5432 occupied; daemon linux/x86_64 | 2026-09-10T18:27-18:28Z |
| EV-B00-03 | Python lock resolves and reproduces | `uv lock --directory backend` (100 packages, 15.3 s first run); `uv sync --frozen --directory backend` | PASS - 98 packages installed into `backend/.venv`; re-lock after security bumps resolved; frozen sync reproduces | 2026-09-10T18:30-19:00Z |
| EV-B00-04 | Django hello-world + quality gates | `uv run --directory backend python manage.py check`; `ruff check .`; `ruff format --check .`; `mypy config agni` | check PASS "System check identified no issues (0 silenced)"; ruff check PASS "All checks passed!"; ruff format PASS "14 files already formatted"; mypy PASS "Success: no issues found in 12 source files" (strict + django plugin; `environ` handled by a `[[tool.mypy.overrides]]` entry) | 2026-09-10T19:00-19:1xZ |
| EV-B00-05 | Node lock reproduces | `corepack pnpm install --dir web` then `corepack pnpm install --dir web --frozen-lockfile` | PASS - 164 packages; lockfile regenerated from exact specifiers (pnpm 12 does not rewrite specifiers on `--lockfile-only`); frozen install: "Lockfile is up to date, resolution step is skipped" | 2026-09-10T18:5xZ |
| EV-B00-06 | React hello-world build | `corepack pnpm --dir web typecheck && corepack pnpm --dir web build` | PASS - tsc clean; vite 8.2.2 built 16 modules in 4.18 s (dist/index.html 0.44 kB, CSS 5.01 kB, JS 220.00 kB) | 2026-09-10T18:5xZ |
| EV-B00-07 | Image digests resolvable | `docker buildx imagetools inspect <image>:<tag>` for the six images | PASS - index + per-platform digests recorded in s.6 and `infra/images.lock.json`; ClamAV index is amd64-only | 2026-09-10T18:3x-18:5xZ |
| EV-B00-08 | Dependency vulnerability scan | `uv run --directory backend pip-audit --progress-spinner off`; `corepack pnpm --dir web audit --audit-level low` | pip-audit first run: FAIL - 5 advisories in 3 packages (DRF 3.16.1 x2, pytest 8.4.2 x2, weasyprint 69.0) -> ranges raised, re-locked (s.9 DEV-01..03); rerun on the re-locked environment: PASS "No known vulnerabilities found". pnpm audit: PASS "No known vulnerabilities found" | 2026-09-10T18:4x-19:1xZ |

## 8. Open items and blockers for B00

| ID | Item | Impact | Unblock condition |
| --- | --- | --- | --- |
| L-01 | Toolchain version probes (`git`, `docker`, `docker compose`, `uv`, `pnpm`, RAM, ports) not executed because the agent harness's Bash permission classifier was unavailable on 2026-09-10 (handover BL-002). Tools are installed (file inspection). | Environment record incomplete; installs cannot start | Harness classifier recovers or user changes permission mode |
| L-02 | Registry resolution (PyPI/npm/Docker Hub/Quay) not executed for the same reason (WebFetch also gated) | Sections 4-6 unresolved | Same as L-01 |
| L-03 | Host is Windows 11 + Git Bash; build guide prefers Linux/macOS/WSL2. Windows-native path is viable for uv/pnpm/Docker Desktop, but `scripts/*.sh`, gunicorn, ClamAV loopback and WeasyPrint's GTK runtime assume POSIX. | B00 install proof is done Windows-native and labelled as such; B01 must decide how POSIX-only components run (WSL2 or containers) | DECIDED 2026-09-10 by user (handover D-002): B00 uses the Windows-native toolchain consistently. B01 carries the POSIX-only component decision. |
| L-04 | Celery "5.6 compatible" in the architecture spec must be confirmed to exist on PyPI at lock time; if not, lock latest supported 5.x and record the deviation here | Possible spec/registry mismatch | CLOSED 2026-09-10: celery 5.6.3 locked |
| L-05 | Host has 5.9 GB RAM and Docker Desktop's Linux VM is limited to 3.0 GB / 4 CPUs - below the build guide's 8 GB reduced-profile guidance | Full local profile (PostgreSQL + RabbitMQ + Valkey + SeaweedFS + Keycloak + ClamAV + API/worker/scheduler/web) is unlikely to fit; ClamAV alone typically needs >1 GB | B01 defines `minimal` (postgres, rabbitmq, valkey, objectstore) and `full` Compose profiles; local proof runs `minimal`; `full` is validated on CI or a larger host and recorded honestly. User may raise the Docker Desktop memory limit |
| L-06 | Host port 5432 is already in use by an unrelated process (PID 6388) | Default PostgreSQL port mapping would collide | B01 Compose publishes PostgreSQL on `${POSTGRES_HOST_PORT:-55432}`; `.env.example`/README document the override; never kill the unknown process |
| L-07 | ClamAV 1.5.4 image index is linux/amd64 only | macOS arm64 hosts cannot run the scanner natively | B01/B05: `full` profile marks clamav `platform: linux/amd64` (emulated on Apple Silicon) and the scanner adapter has a local simulator; live scanning capacity is a deployment concern (BL-005) |
| L-01/L-02/L-03 | (historical) tool probes and registry resolution blocked by the harness gate; Windows host deviation | - | CLOSED 2026-09-10T18:27Z (gate lifted via user allowlist); L-03 superseded by D-002/D-004 |

## 9. Change discipline and recorded deviations

Upgrades after B00 require an ADR-style note in this file (reason, compatibility tests, security impact) and refreshed lockfiles. Never use `latest` tags or unbounded ranges in committed manifests. A newer major release is not adopted automatically.

| ID | Date | Change | Reason | Compatibility evidence | Security impact |
| --- | --- | --- | --- | --- | --- |
| DEV-01 | 2026-09-10 | djangorestframework family 3.16 -> **3.17.2** (`>=3.17.2,<3.18`) | pip-audit PYSEC-2026-3827 and PYSEC-2026-3828 affect 3.16.1; fix version 3.17.2 | `uv lock` resolved with Django 5.2.17, drf-spectacular 0.30.0, djangorestframework-stubs 3.16.9; `manage.py check` PASS; API surface unused yet (B00), so no behavioral regression possible; B01+ tests run against 3.17 | Removes two known vulnerabilities |
| DEV-02 | 2026-09-10 | weasyprint 69.0 -> **70.0** (`>=70,<71`) | PYSEC-2026-3940 affects 69.0; fixed in 70.0 | import-level only at B00 (rendering worker arrives B12); container build will exercise it | Removes one known vulnerability |
| DEV-03 | 2026-09-10 | pytest 8.4.2 -> **9.1.1** (`>=9.0.3,<10`) | PYSEC-2026-1845 affects 8.x; fixed in 9.0.3 | dev-only; pytest-django 4.14.0 resolved compatibly; no tests exist yet at B00 | Removes one known vulnerability (dev tooling) |
| DEV-04 | 2026-09-10 (B03) | add direct runtime dependency **requests 2.34.2** (`>=2.32,<3`) | `authlib.integrations.django_client` imports `requests`; the api container (built with `--no-dev`) crashed at import until it was declared (found by the container health check, not by host tests, which had it through the dev group) | `uv lock` re-resolved with no other change; container rebuilt and healthy; requirements.txt re-exported | Apache-2.0; pip-audit clean |
| DEV-05 | 2026-09-10 (B04) | add direct runtime dependency **jsonschema 4.26.0** (`>=4.23,<5`) | Policy packages are data validated against a versioned Draft 2020-12 JSON Schema with `additionalProperties: false` (workflow s.6, FR-27); the library was already in the lock as a transitive dependency | `uv lock` resolved without other changes; `manage.py check` PASS; 122 backend tests PASS incl. schema-rejection tests; requirements.txt re-exported | MIT; pip-audit clean (already present transitively) |
| DEV-06 | 2026-09-10 (B04) | add dev dependency **types-jsonschema 4.26.0.20260518** (`>=4.23,<5`) | mypy strict reported "Library stubs not installed for jsonschema" | dev group only; `mypy config agni tests` PASS (121 files) | none (typing stubs) |

---
[Documentation index](../README.md) | [Build guide](10_BUILD_GUIDE.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
