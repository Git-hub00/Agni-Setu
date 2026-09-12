# B20 - Agency pilot activation checklist (gate register, not an activation)

**Agni Setu implementation baseline 2.0.0 | prepared 2026-09-12 by the engineering session**  
**Status:** CHECKLIST ONLY. Nothing in the repository authorises live use. Per the owner's instruction, B20 is delivered as the list of decisions, evidence and configuration gates that must be closed before the first official case or certificate. Each row states what exists in this repository today and what only the accountable owner can supply. No approval, credential, legal threshold or provider acceptance has been assumed.

Legend: **READY** = the engineering side exists and is tested; **OWNER** = needs a decision, document or credential from the named owner; **BLOCKED** = cannot be closed on the current host / without an external party even after the owner decides.

## 1. Owner decisions (docs/19 s.2)

| Gate | Decision / evidence required | Owner | What the repository provides today | Status |
| --- | --- | --- | --- | --- |
| LIVE-01 | Service mandate; system of record | Business/process owner | `SERVICE_MODE=DEMO` default; `AGNI-DEMO-*` numbering; LIVE refuses demo sinks (`config/settings/production.py`, `test_production_settings.py`) | OWNER |
| LIVE-02 | Eligibility, exclusions, forms, effective-date rules | Policy/legal owner | Versioned policy packages with independent approval, simulation gate, non-overlapping intervals, pinned cases (B04, `test_policy_governance.py`); synthetic `demo-fire-noc` only | OWNER (content) / READY (mechanism) |
| LIVE-03 | Authority posts, jurisdiction, delegation, separation | Process owner | Capability grants with independent approval, epoch-revoked sessions, SoD on decisions and approvals (`test_grants_and_provisioning.py`, `tests/faults/test_authority_race.py`) | OWNER (matrix sign-off) / READY |
| LIVE-04 | Document checklist, inspection criteria, NA, reinspection | Inspection/policy owner | Deterministic score-free evaluator, mandatory-fail block, NA only where permitted (`test_checklist.py`, B08); 8-item demo checklist | OWNER (content) / READY |
| LIVE-05 | Statutory clocks, calendars, holidays, pauses, escalation ladder | Process/policy owner | Working/calendar clocks, unioned pauses, unique threshold actions, escalation with acknowledgement (`test_clock.py`, `test_clocks.py`); demo targets never labelled statutory | OWNER (values) / READY |
| LIVE-06 | Notice wording, service, response periods | Policy/legal owner | Itemised immutable notices with supersession, response revisions, review return (`test_notices.py`); demo wording | OWNER (wording) / READY |
| LIVE-07 | Certificate template, validity, signing, issuer, revocation powers | Issuing authority | Sample watermarked PDF, demo watermark signer behind a port, status instruments (`test_decisions.py`, `test_lifecycle.py`); no real signing | OWNER + BLOCKED (approved signer) |
| LIVE-08 | Public verification fields and semantics | Data/privacy owner | Token lookup, minimal fields, distinct unknown/unavailable, rate-limited (`test_decisions.py` AT-22, `tests/security`); certificate-number lookup off in LIVE (`PUBLIC_LOOKUP_PROFILE=TOKEN`) | OWNER (field approval) / READY |
| LIVE-09 | Identity provider, recovery, staff MFA | Identity/security owner | OTP through a provider port (demo sink), OIDC through Authlib against any compliant issuer (local Keycloak), sessions with idle/absolute limits (`test_otp_sign_in.py`, `test_oidc_and_scope.py`, `test_sessions.py`) | OWNER + BLOCKED (real IdP / OTP gateway credentials) |
| LIVE-10 | Hosting, residency, storage, backup, key ownership | IT/security/procurement | Production-shaped Compose, environment contract, release/rollback runbook (`infra/containers/production/`), restore rehearsal (`scripts/ops/restore-check.sh`, 30.9 s local) | OWNER + BLOCKED (managed PostgreSQL with PITR, object service, KMS) |
| LIVE-11 | Retention, legal hold, destruction, subject requests | Records/privacy/legal owner | No automatic purge; immutable audit chains; exports expire after 24 h; contacts encrypted at rest | OWNER |
| LIVE-12 | Managed devices, offline permission, lost devices | Security/field operations | Offline packages per attempt, explicit sync, conflict review, revoked authority blocks sync (`test_sync.py`) | OWNER |
| LIVE-13 | Gateway contracts, credentials, reconciliation | Integration owner | HMAC partner intake, ordering, conflicts, verified-source reconciliation against a simulator (`test_integrations.py`); LIVE refuses demo partner secrets | OWNER + BLOCKED (partner sandbox) |
| LIVE-14 | Fees, payment, receipts | Finance/process owner | Fees disabled; dependent routes answer SERVICE_DISABLED with referral (`test_lifecycle.py` AT-30) | OWNER |
| LIVE-15 | Appeal / remedy process | Legal/process owner | Referral only; `/appeals` answers SERVICE_DISABLED with the referral text | OWNER |
| LIVE-16 | External issuer qualification / registration | Policy/registration owner | Conditional capability disabled | OWNER |
| LIVE-17 | Accessibility, languages, assisted service | Product/service owner | WCAG 2.2 AA axe + keyboard + viewport suite (`web/e2e`), English baseline; Hindi not enabled | OWNER (Hindi review, assisted-service process) / READY (English) |
| LIVE-18 | Security acceptance, vulnerability treatment, incident process | Security owner | Boundary + header suites (`tests/security`), secret scan, Trivy image reports with unfixed-OS findings recorded (`release/2026.09.12-b18/manifest.json`), pip/pnpm audits clean | OWNER (acceptance + treatment sign-off) |
| LIVE-19 | Recovery objectives, on-call, restore evidence | Operations owner | Broker / worker / storage / database fault suites and drills (B17), backup + isolated restore rehearsal with integrity report | OWNER + BLOCKED (PITR / off-host custody, roster) |
| LIVE-20 | UAT, pilot population, training, release approval | Sponsor/product/QA | B19 acceptance report (`docs/21` s.3u, `docs/ACCEPTANCE_MATRIX.md`, `docs/RELEASE_NOTES_DEMO.md`); GitHub `production` environment approval gate in the release workflow | OWNER |

## 2. Configuration gates enforced in code (docs/19 s.3)

| Check | Where | Evidence |
| --- | --- | --- |
| LIVE refuses demo OTP / notification / signing sinks, demo scanner, demo controls, demo partner secrets, non-TOKEN public lookup | `backend/config/settings/production.py` | `tests/unit/test_production_settings.py` (7), `scripts/ops/prod_boot_check.py` A1-A3 (7 problems listed together) |
| No demo routes outside `APP_ENV=local` with demo controls | `backend/config/urls.py` | boot check B14 (demo inbox 404 under production settings) |
| Placeholder / short secrets, wildcard hosts, http origins refused | production settings | same |
| Read-only, non-root, no published private ports, digest-only images | `infra/containers/production/compose.prod.yml` | `tests/unit/test_release_packaging.py` (11), boot check 23/23 |
| Release requires a tag on HEAD, green gates, migration compatibility, fixable-CVE gate and a `production` environment approval | `.github/workflows/release.yml` | packaging test; workflow not yet executed on GitHub (needs the environment configured by the repository owner) |

## 3. Release evidence available now (docs/19 s.6)

| Evidence | Location | State |
| --- | --- | --- |
| Commit / release ids | `main` history (B00-B19 fast-forwards), `release/2026.09.12-b18/manifest.json` | available (local manifest; registry digests appear at publish time) |
| Dependency locks and container digests | `backend/uv.lock`, `web/pnpm-lock.yaml`, `infra/images.lock.json`, `docs/DEPENDENCY_LOCK.md` | available |
| Migration plan | `scripts/ci/migration_compat.py` runs (B18: `c9ccf1d` and `a485335` -> current PASS) | available |
| Database / object restore result | B17 restore drill (30.9 s, 50 chains, 21/21 objects) | available (local; PITR not claimed) |
| Automated and manual test reports | `docs/21` s.3a-3u, `docs/ACCEPTANCE_MATRIX.md`, `evidence/` | available |
| Role / authority matrix sign-off | LIVE-03 | OWNER |
| Approved policy hash | LIVE-02 (mechanism: policy version hash + approval record) | OWNER |
| Public schema approval | LIVE-08 | OWNER |
| Provider sandbox / live acceptance | LIVE-07/09/13 | BLOCKED |
| Security findings and treatment | Trivy reports (api: 63 unfixed Debian OS advisories, 0 Python; web: 0), `tests/security` | available; treatment sign-off OWNER |
| Accessibility review | `web/e2e` suite results (B16, B19) | available (automated); manual screen-reader walk OWNER |
| Operator runbooks and contact roster | `infra/containers/production/README.md`, `docs/12` | runbooks available; roster OWNER |
| Rollback decision | runbook s.4-5 | procedure available; per-release decision OWNER |
| Pilot monitoring dashboard | operations summary API + `/operations` page; external dashboards | OWNER (monitoring stack) |
| Explicit go / no-go | - | OWNER |

## 4. Engineering gaps carried into the decision (from B19)

D-011 demo console not built (demo convenience); D-012 fixture inventory smaller than docs/13; performance protocol not executed on the developer host (B17); visual parity snapshots not captured; the 19 acceptance cases labelled NOT_RUN and the BLOCKED rows in `docs/ACCEPTANCE_MATRIX.md`.

---
[Documentation index](../README.md) | [Live gates](19_POLICY_AND_LIVE_ACTIVATION_GATES.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
