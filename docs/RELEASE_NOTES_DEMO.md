# Agni Setu - demonstration release notes

**Build:** `main` after B18 (`6aa6967`) + B19 acceptance (this commit) | implementation baseline 2.0.0 | 2026-09-12  
**Nature of this release:** a demonstration build on synthetic data. It issues **sample** certificates watermarked "DEMONSTRATION - NOT A VALID GOVERNMENT CERTIFICATE", sends no real messages, signs nothing legally and integrates with no government system. Live use is gated by `docs/19_POLICY_AND_LIVE_ACTIVATION_GATES.md` (B20) and is not authorised by this release.

## 1. What the demonstration shows

| Journey | Roles | Where |
| --- | --- | --- |
| Applicant sign-in by one-time code, premises, applicability, versioned draft wizard, private uploads with malware scanning, atomic submission with receipt, timeline | applicant (OTP) | `/sign-in`, `/applicant/premises`, `/applications/new`, `/applications/:id/edit`, `/applications/:id` |
| Routing to an accountable queue or an owned exception, scrutiny, appointment scheduling with overlap protection, check-in, failed visits, follow-up attempts | supervisor `anita`, officers `suresh` / `priya` (Keycloak) | `/applications`, `/inspections`, `/schedule` |
| Deterministic checklist evaluation, immutable inspection reports with evidence provenance, offline field capture and explicit synchronisation with conflict review | officers | `/inspections/:id`, `/sync` |
| Information requests and deficiency notices, per-item responses, review returns, verified closure, physical reinspection | applicant + supervisor | `/applications/:id/notices/:noticeId`, `/applications/:id/review` |
| Stage and case clocks, reminders, accountable escalation, notifications with delivery visibility, operations recovery of durable jobs | supervisor, leadership `dev`, administrator `arjun` | `/monitoring`, `/notifications`, `/operations` |
| Guarded decisions with immutable rationale, sample certificate issuance through the durable job, public privacy-safe verification, certificate status instruments and renewal | supervisor, public | `/applications/:id/review`, `/certificates`, `/verify/:token` |
| Reconciled metrics, controlled exports with purpose and ticketed download, audited audit search, staff authority governance, independent policy approval, partner-event intake with ordering and conflicts, support tickets, withdrawal, referral for disabled routes | leadership, administrator, policy approver `meera`, applicant | `/reports`, `/audit`, `/team`, `/policy`, `/integrations`, `/support` |

## 2. How to run it

See `README.md` (Windows and macOS): `scripts/dev/up.sh all`, then `docker exec agni-dev-api-1 python manage.py seed_demo --scenario baseline --require-demo`, open `http://localhost:5173`. Applicant codes appear in the demo inbox (`GET /api/v1/demo/inbox?channel=EMAIL&contact=<address>`); staff sign in with the realm personas (passwords in `infra/identity/realm-agni-dev.json`). The acceptance walk is reproducible with `uv run --directory backend python ../scripts/dev/acceptance_run.py` (API + database level) and `corepack pnpm --dir web test:e2e` (browser level).

## 3. Evidence of this release

- `docs/ACCEPTANCE_MATRIX.md` - which of the 180 core acceptance cases, 16 properties, 20 journeys and 24 demonstration scenarios are automated, exercised by the acceptance scripts, blocked or not run.
- `docs/23_PROTOTYPE_COVERAGE.md` s.7 - every one of the 94 prototype controls and 20 forms with its implementation and status.
- `docs/21_IMPLEMENTATION_STATUS.md` s.3u - the B19 run record (commands, results, defects fixed, gaps).
- `release/2026.09.12-b18/` - release manifest, SBOMs, image scan summary (B18).

## 4. Known limitations of the demonstration (honest list)

1. **Demo console (UI-28) is not built.** No in-app persona switcher, clock advance, provider toggle or reset; use the real sign-ins, `seed_demo`, the demo inbox and the `scripts/ops` drills instead. Live mode never had these routes.
2. **Fixture baseline is smaller than the docs/13 inventory.** `seed_demo --scenario baseline` builds a deterministic baseline of personas, policy, premises and a handful of cases plus the smoke-generated cases; the 28-case / 5-certificate inventory with its 28/27/20/5/1/1 count oracle is not reproduced. Metrics reconcile against whatever the canonical dataset holds (proven by tests), not against that oracle.
3. **No print action, no clipboard copy, no document detach button, no policy create/edit form in the browser** (the server contracts exist and are exercised through the API and scripts).
4. **Malware scanning depends on ClamAV**, which needs about 1.5 GB RAM; on small laptops the daemon dies and uploads stay QUARANTINED (retried, never marked clean). The B19 acceptance run had to restart ClamAV before scans completed - this is the documented BL-007 host limit, not a scanning bypass.
5. **Performance protocol** (10,000 cases / 100 users) was not executed on this host; the reduced Locust run and the capacity finding are in B17.
6. **Sample signing and demo sinks only.** Live OTP / notification / signing / registry adapters, the operating-environment services (managed PostgreSQL with PITR, broker, cache, object service, identity provider, TLS) and the GitHub `production` environment approvals are B20 owner decisions.
7. **Visual parity snapshots** (1440x900 / 390x844 per role) were not captured; accessibility, headings, overflow and CSP are asserted by the browser suite instead.

## 5. Defects found and fixed during acceptance

Recorded in `docs/21_IMPLEMENTATION_STATUS.md` s.3u as they were found; each has a test or acceptance step that fails without the fix.
