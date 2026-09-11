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
| B05 | Drafts, files and application wizard | READY_FOR_REVIEW (2026-09-11T00:50Z; PR pending; ClamAV proof BLOCKED by host RAM - see s.3g) | Server drafts: append-only `DraftRevision` per autosave with `Application.current_draft_revision`; revision 1 pre-fills the premises snapshot and pins the FORM artifact of the policy in force; `PatchDraft` (API-023) requires the edited `draft_revision` plus the application `If-Match` and answers a stale second tab with 412 carrying `current_draft_revision` and `current_fields`; declarations D01-D03 (demo constants, individually accepted, exact code/version stored); requirement evaluation from the policy for the declared category (MISSING / PENDING_SCAN / REJECTED / SATISFIED - only a CLEAN linked version satisfies a slot); `blockers` and `allowed_actions` keep Submit disabled with a safe reason (TR-01 arrives with B06). Documents module (`agni.documents`): `UploadReservation` (random private staging key, bounded size/TTL, allowlisted target type, requirement code from the policy, package quota 20 files / 50 MiB), byte transfer streamed through the API (no bucket credentials to the browser; SHA-256 computed server-side; body bounded), `CompleteUpload` (server digest vs client claim vs storage metadata, magic-byte sniff, promotion to content-addressed `objects/<sha256>` never overwritten, QUARANTINED `DocumentVersion`, durable `document.scan` job in the same transaction, staging cleanup after commit), `GrantDocumentAccess` (CLEAN only; append-only `DocumentAccess`; signed principal-bound 5-minute proxy ticket; REJECTED never served), detach (new draft revision, nothing destroyed). Durable jobs (`platform.LogicalJob`/`JobAttempt`): `FOR UPDATE SKIP LOCKED` claim, lease-token fence, backoff 30 s/2 m/10 m/30 m/2 h, max 6 attempts, UNKNOWN -> RECONCILIATION_REQUIRED, `process_jobs` worker (Compose `worker` service). Scanner adapters: clamd INSTREAM (5 s/30 s timeouts; outage/ERROR -> UNKNOWN, never CLEAN) and `demo_eicar`; object stores: S3/SeaweedFS and in-memory (tests); production settings refuse a non-S3 store and a demo scanner in LIVE. Web: UI-05 `/applications` (URL-synced search/status, cursor paging, Continue for drafts, retry on failure), UI-06 `/applications/new` + `/applications/:id/edit` (4 steps, serialised 800 ms autosave with If-Match + per-attempt idempotency key reused on retry, explicit 412 conflict panel with field differences and "use saved / reapply mine", declarations, per-requirement upload reserve -> PUT -> complete with 2 s scan polling, review with blockers, no dead Submit), UI-07 `/applications/:id` slice. Tests: backend **137 passed** (AT-04-01..05, AT-05-01..05, job fence, clamd protocol against a real fake clamd socket, S3 adapter against the live Compose object store), web **22 passed**; ruff/mypy strict/tsc/eslint clean; migrations platform 0002, documents 0001, cases 0003. **Container proof:** api rebuilt (migrations applied on start), `worker` container healthy; SeaweedFS volume budget raised after every PUT failed with "No writable volumes" (found only by the container run); `scripts/dev/smoke_drafts.py` through nginx **17/17 PASS** (fresh OTP applicant, premises, draft, autosave, stale 412, reserve/PUT/complete -> QUARANTINED, link -> PENDING_SCAN, no scanner -> stays QUARANTINED and cannot be opened (409), detach, list); one-off `process_jobs --once` with the local demo scanner in the container -> job COMPLETE, version CLEAN, audit row. **ClamAV: BLOCKED** - the container never became healthy on the 3 GB Docker VM (1.42 GiB of its 1.5 GiB limit while loading signatures, 17 min, then unhealthy; it starved the api); stopped again. The clamd protocol client is proven against a real socket in unit tests; a real ClamAV verdict needs a host with more RAM (CI/larger machine). Evidence `handover.md` B7 EV-B05-01..08; record s.3g | Push `feat/b05-drafts`, PR; then B06 |
| B06 | Submission, routing and case visibility | READY_FOR_REVIEW (2026-09-11T01:35Z; PR pending) | TR-01 `SubmitApplication` (API-024) follows the atomic transition algorithm: principal fence -> service activation fence -> application row; draft-revision precondition; policy re-selected under the fence and compared with `reviewed_policy_version_id` (POLICY_UNAVAILABLE / POLICY_AMBIGUOUS propagate); full field completeness; every declaration accepted at its current version; every referenced document must belong to the case and be CLEAN and every required requirement covered (EVIDENCE_INCOMPLETE otherwise - no receipt, no partial transition); routing resolved from the pinned policy's ROUTING artifact rows (category-specific beats wildcard) or a visible owned `RoutingException` on the accountable central queue; immutable `SubmissionRevision` (fields, premises snapshot, declaration snapshot, selection explanation, sha256) + `SubmissionDocument` rows; public reference `AS-<year>-<n>`; stage instance SUBMITTED; `application.submitted.v1` (PUBLIC_CASE) and `routing.exception_opened.v1` (INTERNAL) events; CASE_TARGET (calendar) and SCRUTINY_TASK (working) obligations with due instants from the clock model; audit; outbox envelopes; receipt. TR-02 `StartScrutiny` (API-027) for a supervisor scoped to the accountable queue, refused while a routing exception is OPEN. `ResolveRoutingException` (API-028) with an active queue in the target jurisdiction and a ROUTING artifact; re-owns active obligations; old routing events retained. Clock model (`agni.obligations.domain.clock`): CALENDAR/WORKING bases, IANA calendar, holidays, union of pauses, open pause -> no estimate, boundary equality due - all six worked rows of workflow s.8 pass. Reads: API-020 list (+next_due_at), API-022 detail (submission, obligations - applicants see the case target only -, open exception for staff, allowed_actions with safe reason codes), API-025 timeline (applicant PUBLIC_CASE only, staff + INTERNAL, RESTRICTED never), API-026 revisions, `/overview` (UI-09 counts from the same scoped population and cutoff, due soon/overdue/routing exceptions, priority work, latest events). Web: submit in the wizard with explicit confirmation, one stable command key and an "outcome not confirmed" state (Check status / Retry safely), receipt banner, detail timeline with internal labels, supervisor actions, `/overview`. Tests: backend **154 passed** (AT-06-01..05 incl. 3-way concurrent submit, AT-07-01..05, AT-09-01..05, clock worked table), web **23 passed**; gates clean; migrations cases 0004, obligations 0001, routing 0003. **Container proof PASS:** api + worker recreated on the B06 image (migrations applied on start), seed republished the spec calendar as artifact number 2, `scripts/dev/smoke_submission.py --scan-via-demo --oidc` through nginx: applicant 37/37 (fresh OTP applicant, draft, declarations, 3 uploads scanned CLEAN by demo one-off worker passes, link, submit -> receipt `AS-2026-1001` on `central-scrutiny` with CASE_TARGET + SCRUTINY_TASK due at Fri 17:00 IST, same-key replay, second submit 409, detail/timeline/revisions, unmapped ward W-99 -> SUBMITTED with NO_MATCH exception invisible to the applicant, overview) and staff 8/8 (anita via real Keycloak: sees exception, scrutiny blocked, overview counts it, resolve-routing 200, start-scrutiny -> SCRUTINY, internal events in her timeline). Evidence `handover.md` B7 EV-B06-01..06; record s.3h | Push `feat/b06-submission`, PR; then B07 |
| B07 | Assignment and appointment management | READY_FOR_REVIEW (2026-09-11T03:40Z; PR pending) | NEW app `agni.inspections`: `Inspection` attempts (REQUESTED -> SCHEDULED -> IN_PROGRESS -> COMPLETED; SCHEDULED/IN_PROGRESS -> FAILED; REQUESTED/SCHEDULED -> CANCELLED; retained forever; pinned checklist artifact; appointment + IANA timezone; check-in facts), `Assignment` versions (one ACTIVE per attempt by partial unique index; **GiST exclusion constraint on (officer, half-open booking range) for ACTIVE bookings with the `btree_gist` extension**), `Availability` intervals. Commands: TR-05 `RequireInspection` (API-029: SCRUTINY -> INSPECTION_PENDING only when the pinned policy requires a visit and routing is resolved; SCRUTINY_TASK satisfied, INSPECTION_TASK obligation opened, checklist pinned from the policy), `ScheduleInspection` (API-041: eligibility = active OFFICER binding in the case jurisdiction, officer scheduling fence, unavailability check, overlap pre-check + DB constraint -> APPOINTMENT_CONFLICT with the conflicting interval, public `inspection.scheduled.v1` + internal `inspection.assignment_changed.v1`, `application_version` child precondition), `ReassignInspection` (API-042: supersedes the ACTIVE assignment; stale officer authority revoked by version; case clock untouched), `CancelInspection` (API-043: attempt kept, assignment REVOKED, follow-up REQUESTED attempt created), `CheckIn` (API-044: assigned officer only, `assignment_version` -> ASSIGNMENT_CHANGED, GPS or an explicit unavailability reason - never fabricated coordinates), `FailVisit` (API-046: FAILED attempt with approved reason code, FULFILLED assignment, follow-up attempt, case stays INSPECTION_PENDING with unchanged case-target due), `RecordAvailability` (API-094: self or supervising supervisor; affected bookings surfaced, never cancelled). Reads: API-038 list (officer: own assigned attempts; supervisor/leadership: jurisdiction; filters), API-039 detail with allowed_actions, API-040 `/schedule` (<= 31 days, bookings + unavailability, permitted officers), `/officers` roster; case detail gains `require-inspection` and an inspections summary (officer identity internal). Web: UI-10 `/inspections` queue (URL filters, large cards), UI-11 `/schedule` week agenda list with officer filter, UI-12 slice `/inspections/:id` (assignment history, supervisor schedule/reassign/cancel dialog, officer check-in and failed visit, checklist preview), case detail "Require site inspection". Tests: backend **159 passed** (AT-08-01..05 incl. two concurrent bookings -> one assignment, DB exclusion on bypass; AT-11-01..05), web **24 passed**; gates clean; migration inspections 0001. **Container proof PASS:** api rebuilt (inspections 0001 incl. btree_gist applied), web image rebuilt with the B05-B07 screens, `scripts/dev/smoke_inspections.py` **21/21** through nginx + Keycloak (anita requires + schedules Suresh, overlap 409, reassigns to Priya; Suresh's check-in 404; Priya checks in and records SITE_INACCESSIBLE -> FAILED + follow-up attempt, case clock unchanged). Evidence `handover.md` B7 EV-B07-01..06; record s.3i | Push `feat/b07-assignments`, PR; then B08 |
| B08 | Inspection reports and checklist evaluation | READY_FOR_REVIEW (2026-09-11T03:15Z; PR pending) | Domain `agni.inspections.domain.checklist`: pure validator (exact item codes, no duplicates/extras, PASS/FAIL/NOT_VERIFIED/NOT_APPLICABLE, 10-2000 char explanation for every non-PASS result, unique UUID evidence lists, optional capture time/location) and **deterministic evaluator** (mandatory FAIL -> MANDATORY_FAIL, mandatory NOT_VERIFIED -> MANDATORY_NOT_VERIFIED, NA where the checklist forbids it -> NA_NOT_PERMITTED, PASS without evidence on an evidence-required item -> EVIDENCE_MISSING; permitted NA always listed for reviewer confirmation; advisory FAIL/NOT_VERIFIED recorded as findings; **no numeric score exists**). Persistence (inspections 0002): `InspectionDraft` (one per inspection/officer; versioned child), append-only `InspectionReport` (revision per attempt; assignment, checklist artifact, submitter, capture vs acceptance time, observations, evaluation, canonical sha256, source_operation_id) and `ReportEvidence` (item/document unique; evidence sha256 + object key pinned), `Inspection.current_report`. Commands: `SaveReportDraft` (API-045 PUT; assigned officer of an open attempt; inspection ETag + application/assignment/checklist version fences; partial observations; evidence must already be CLEAN files of the same case; inspection version unchanged, draft ETag returned) and `SubmitReport` (API-047; assigned officer only - others 404; must be checked in; complete observations; summary 10-4000; captured_at or explicit capture_unavailable_reason; declaration; **evidence must be CLEAN and belong to this case (wrong-case / quarantined -> 422)**; immutable revision + evidence rows; attempt COMPLETED, assignment FULFILLED, draft removed; **TR-06 INSPECTION_PENDING -> REVIEW_PENDING**, INSPECTION_TASK satisfied, REVIEW_TASK obligation (working minutes from the pinned policy), public `inspection.report_accepted.v1` + internal `inspection.report_evaluated.v1`, audit, outbox, ReportReceipt; same key -> replay, new key on the closed attempt -> 409). Staff evidence uploads: `INSPECTION_EVIDENCE` target for the currently assigned officer (`inspection-c0N` codes of the pinned checklist; file owned by the case; package quota shared). Reads: inspection detail carries the officer's own draft, the accepted report and `save-draft` / `submit-report` actions (CHECK_IN_REQUIRED); case detail carries per-attempt report facts (staff: eligibility + blockers; applicant: revision/acceptance only). Seed checklist aligned to docs/24 s.4 (C01-C08 flags; published as artifact number 2, old attempts keep #1). Web UI-12 `ReportWorkspace` (results per item with NA only where permitted, explanation prompts, per-item evidence upload + scan check, Save draft, declaration, Submit report with a stable operation id, receipt + `ReportView` with blockers). Tests: backend **172 passed** (6 evaluator unit tests; AT-13-01..06 / AT-14-01..04 integration on real PostgreSQL), web **25 passed** (one contention timeout re-run alone). **Container proof PASS:** api (`f2a37b6959e4`) and web (`ffcdf409e140`) rebuilt and verified by image id, inspections 0002 applied on start, seed republished the spec checklist as artifact number 2, `scripts/dev/smoke_reports.py` **32/32** through nginx + Keycloak (anita schedules Priya on the B07 follow-up attempt; Priya: draft allowed / submit CHECK_IN_REQUIRED before check-in, check-in, two evidence uploads through INSPECTION_EVIDENCE -> QUARANTINED -> CLEAN via a one-off demo-scanner pass, draft saved without moving the inspection version and restored on re-read, NA-not-permitted 422, incomplete set 422, foreign evidence 422, submit 201 -> COMPLETED + REVIEW_PENDING with MANDATORY_FAIL:C06 blocker and no score, same-key replay, closed-attempt resubmit 409; anita: REVIEW_TASK ACTIVE due Fri 17:00 IST, INSPECTION_TASK SATISFIED, blockers visible, accepted report with 6 evidence hashes, both report events in the timeline). Evidence `handover.md` B7 EV-B08-01..06; record s.3j | Push `feat/b08-reports`, PR; then B09 |
| B09 | Notices, responses and correction cycles | READY_FOR_REVIEW (2026-09-11T11:05Z; merged to `main` per D-009 - see s.3k) | NEW app `agni.notices` (migration 0001): `Finding` (materialised from every accepted report's FAIL / mandatory NOT_VERIFIED observation; unresolved findings are retained across reinspections, never duplicated), immutable `Notice` rounds (unique application/type/round; PUBLISHED -> SATISFIED / SUPERSEDED; internal note staff-only), `NoticeItem` (OPEN -> RESPONSE_RECEIVED -> ACCEPTED / RETURNED; deficiency items linked to findings), append-only `ResponseRevision` (+ documents), `NoticeItemReview`, `FindingReview`. Commands: `PublishNotice` (API-054: supervisor in jurisdiction **plus `notice.publish` grant**; INFORMATION -> TR-03 SCRUTINY->INFO_REQUIRED, DEFICIENCY -> TR-07 REVIEW_PENDING->COMPLIANCE_PENDING with every item bound to an open finding; superseding round while waiting keeps the original notice and cancels its clock; APPLICANT_RESPONSE obligation from the policy budget; stage task satisfied), `SubmitResponse` (API-056: applicant/delegate with `notice.respond`; CLEAN same-case evidence only; new revision per item; item and finding -> RESPONSE_RECEIVED; **never a transition**; closed notice -> 409 NOTICE_NOT_OPEN), `ReviewItem` (API-058: accept/return against the current revision; deficiency item accepted only after its finding is VERIFIED_CLOSED -> else 409 RESPONSE_NOT_VERIFIED; return keeps replies and reopens the finding with a public reason), `VerifyFinding` (API-060: supervisor + grant, not the inspecting officer; VERIFIED_CLOSED needs reviewer-cited CLEAN evidence or a PASS observation of an accepted report - **an applicant upload or checkbox alone never closes a MANDATORY finding** (422 verification_basis_required); RETURNED / REINSPECTION_REQUIRED recorded), `AcceptInformation` (API-057 TR-04: all required items ACCEPTED else 409 with pending codes; notice SATISFIED; new SCRUTINY_TASK), `CompleteCorrections` (API-061 TR-08: 409 MANDATORY_FINDINGS_OPEN while any mandatory finding or reinspection is outstanding; deficiency notices SATISFIED; new REVIEW_TASK), `RequireReinspection` (API-062 TR-09: linked findings, new REINSPECTION attempt pinned to the previous checklist, case clock untouched). Reads: API-053/055/059 audience-filtered; case detail gains `notices`, `findings_summary` and guarded actions request-information / issue-deficiencies / accept-information / complete-corrections / require-reinspection. Uploads: `NOTICE_RESPONSE` target (`response-<item code>`) for the applicant side. Seed: anita gets `notice.publish`. Web: UI-08 `/applications/:id/notices/:noticeId` (applicant task list with evidence upload + replies; reviewer accept/return, finding verification with cited evidence, accept information; "Response received" never styled as verified), case detail notices section + supervisor notice actions (item builder, deficiencies from open findings, complete corrections, reinspection). Tests: backend **178 passed** (incl. `tests/integration/test_notices.py` AT-15-01..05, AT-16-01..04, AT-17-01..03), web **26 passed**; gates clean; migration notices 0001. **Container proof PASS:** api `7bb3434e8d2c` / web `996a0b59568e` rebuilt and verified, notices 0001 applied, seed re-run (anita `notice.publish`), `scripts/dev/smoke_notices.py --scan-via-demo` **40/40** through nginx + Keycloak (fresh case -> TR-02 -> TR-03 notice -> guard rails -> applicant NOTICE_RESPONSE upload scanned CLEAN -> reply (no transition) -> early TR-04 409 -> review ACCEPTED -> TR-04 back to SCRUTINY with fresh SCRUTINY_TASK). Evidence `handover.md` B7 EV-B09-01..06; record s.3k | B10 (clocks, outbox dispatch, notifications) |
| B10 | Clocks, outbox dispatch and notifications | READY_FOR_REVIEW (2026-09-11T12:45Z; merged to `main` per D-009 - see s.3l) | **Clocks (FR-18):** `ObligationPause` (authorised, policy-permitted reason codes only; open interval = PAUSED with "due date will be recalculated"), `recompute_obligation` derives `due_at` from immutable facts + the union of pauses (worked example: Mon 09:00 + 240 working min -> 13:00; pause 10-11 -> 14:00; overlapping 10:30-11:30 -> 14:30, not 15:00) and supersedes stale future threshold actions. **Thresholds and escalation (FR-19):** `domain/thresholds.py` plans `REMINDER_75` (75 % of the *active* budget), `DUE` and `ESCALATION_<minutes>` from the pinned policy; `scan_due_obligations` (scheduler, 30 s) inserts the unique `ThresholdAction` per (obligation, stage instance, key) and one durable job with a deterministic logical id - two racing schedulers produce exactly one action/job; the `obligation.threshold` job re-checks state and generation at execution (satisfied -> `CANCELLED_AS_OBSOLETE`, never a fabricated send), creates the unique `Escalation` per threshold action, notifies the duty roster and writes an INTERNAL `obligation.threshold_reached.v1` event. API-074 (one `as_of` cutoff drives counts and urgency), API-075 (clock breakdown, pauses, thresholds, escalations), API-076 manual escalation (idempotent per command, duty roster recipients), API-077 acknowledge (ownership only; obligation untouched). **Outbox dispatch (docs/08 s.2):** `platform/dispatch.py` claims PENDING / stale DISPATCHED rows `FOR UPDATE SKIP LOCKED`, always creates the durable fan-out job (deterministic id) and sends a best-effort broker wake-up through a port (`null` | `amqp` via kombu | `failing` test double); a broker outage leaves rows PENDING with a visible attempt count and the next scan republishes; the fan-out job marks the row COMPLETE. **Notifications (FR-23):** `Notification` (unique per recipient + logical key, versioned template key, safe context, audience-specific body, no attachment URLs), `DeliveryAttempt` (READY -> SENDING -> ACCEPTED_BY_PROVIDER / FAILED; provider acceptance is not delivery), `NotificationPreference` (API-008; mandatory service messages ignore optional channels); templates for 16 event types with audience rules (applicant / supervisors of the owner queue / assigned officer); `notification.fanout` and `notification.deliver` jobs on the demo sink with `force_failure` for outage drills - a gateway outage leaves the in-app notice in place and retries with the job backoff; API-078..080 recipient-only with idempotent read markers and a read-through boundary. **Operations skeleton (UI-20):** API-103/104 (`/jobs`) for administrators: outbox lag, oldest due job, worker activity, dead letters, unknown outcomes, sanitised attempts. `run_schedulers` command + Compose `scheduler` service; `jobs.current_clock()` injects the worker pass clock into handlers. Web: UI-15 `/monitoring` (tabs, KPIs from one cutoff, clock drawer, manual escalation, acknowledge), UI-19 `/notifications` (unread filter, mark read, read-through, delivery status, preferences), UI-20 `/operations`, nav tools + header link. Tests: backend **183 passed** (incl. `tests/integration/test_clocks.py` AT-18-01/02, AT-19-01..05, AT-23-01..05), web **28 passed**; gates clean; migrations obligations 0002 + notifications 0002. **Container proof PASS:** api `b89708eaf2d7` / web `2875d0c683fa` rebuilt and verified, new `scheduler` container healthy, real RabbitMQ wake-ups (`published=34 failed=0`), 9 threshold + 34 fan-out + 12 delivery jobs completed by the worker, `scripts/dev/smoke_clocks.py` **19/19** (obligations from one cutoff, manual escalation + replay, acknowledge != satisfy, notifications read/read-through, preferences, operations summary, supervisor 403 on `/jobs`). Evidence `handover.md` B7 EV-B10-01..06; record s.3l | B11 (offline field application) |
| B11 | Offline field application | READY_FOR_REVIEW (2026-09-11T15:05Z; merged to `main` per D-009 - see s.3m) | NEW app `agni.offline` (migration 0001): `SyncOperation` (one identity per client operation: unique (principal, operation_id), canonical sha256, ACCEPTED / CONFLICT with the stored result) and `ReportConflict` (reviewed proposal OPEN -> RESOLVED with outcome, reason, cited evidence, resolver). API-048 offline package (current ACTIVE assignee with current OFFICER authority; 24 h expiry; versions; checklist; `Cache-Control: no-store`), API-049 `/sync/operations` (runs the ONLINE SubmitReport / FailVisit handlers through the kernel with `idempotency_key=sync:<id>` and `expected_version=base_inspection_version`; identical replay -> stored result; same id + other content -> 409 SYNC_PAYLOAD_CONFLICT; every refusal recorded as CONFLICT with a safe server snapshot and re-raised with `operation_id/server/sync_state`), API-050 owner-scoped receipt, API-051 proposal (former assignees included), API-052 supervisor resolution (PROPOSE_NEW_REPORT / REINSPECTION_REQUIRED / DECLINE; CLEAN same-case evidence only), `/conflicts` list. **Hardening:** `_assigned_officer_only` now requires the OFFICER role for the case jurisdiction at command time -> 403 AUTHORITY_REVOKED (online and via sync). Web: Dexie v1 stores per docs/09 s.3, frozen manifests (canonical JSON + SHA-256), explicit foreground sync with injected deps (upload -> wait CLEAN -> freeze once -> POST with the id as Idempotency-Key -> receipt; lost response -> lookup/replay; 401 -> sign-in needed; 403/409/412/422 -> stored CONFLICT, retries stop), connectivity from `/me` (never `navigator.onLine` alone), identity-switch purge, unsent-work warning on sign-out, UI-13 `/sync` (grouped operations, versions, receipts, conflict panel local vs server with propose / discard), UI-12 offline package card + offline fallback workspace + Save on device / Queue for sync; PWA via vite-plugin-pwa 1.3.0 (static shell precache only, `/api` never cached, user-confirmed reload; nginx serves `sw.js` / manifest with no-cache). Tests: backend **187 passed** alone (incl. `tests/integration/test_sync.py` 4 tests: AT-12-01/02/04/05 + API-051/052 + revoked authority), web **33 passed** (incl. 5 sync-algorithm specs on fake-indexeddb) + build with `sw.js`; gates clean; `pnpm audit` clean. **Container proof PASS:** api `eecf7c16b76e` / web `760efc9d3e6b` rebuilt and verified by image id, offline 0001 applied on start, `scripts/dev/smoke_offline.py` **18/18** through nginx + Keycloak. Incident BL-008 (PostgreSQL crash recovery under an overlapped run) recorded with the clean rerun. Evidence `handover.md` B7 EV-B11-01..08; record s.3m | B12 (decisions, issuance and verification) |
| B12 | Decisions, issuance and verification | READY_FOR_REVIEW (2026-09-11T19:1xZ; merged to `main` per D-009 - see s.3n) | NEW app `agni.decisions` (migration 0001): server-calculated readiness guard list (API-064), `RecordDecision` TR-10 / TR-12 (API-065) binding the accepted submission revision, accepted report, findings, pinned policy and the `case.decide` grant in force, immutable rationale (INTERNAL) + public reason, one final decision per case, approval opens ISSUANCE_TASK and the issuance request in the same transaction, rejection cancels open obligations; API-066 list. NEW app `agni.certificates` (migrations 0001/0002): IssuanceRequest with a stable identity (number `AGNI-DEMO-<year>-<n>`, uuid5 logical action, frozen render snapshot, hashed + encrypted 256-bit verification token), `certificate.issue` durable job through renderer / signer / verifier ports (WeasyPrint in the containers, simulated PDF in tests; `demo_watermark` receipt that states it is NOT a digital signature; hash-match verifier), lookup-before-resubmit, RECONCILIATION_REQUIRED on unknown outcomes with `reconcile_issuance`, guarded TR-11 publication (SYSTEM event, obligations satisfied, audit, outbox), registry API-067/068, audited reader-bound artifact tickets API-069, anonymous rate-limited no-store public verification API-073 (approved subset only; unknown 404 != revoked; 503 on store failure; exact-number lookup DEMO-only). Web: UI-14 review queue + review page (readiness panel, no preselected outcome, acknowledgment, confirmation with evidence versions, "certificate processing"), UI-16 register, UI-17 detail (download, verification link), UI-18 public verify page, UI-01 public actions. Tests: backend **198 passed** alone (incl. `test_decisions.py` 3 + domain unit 6), web **37 passed** + build, e2e **35/35** with a real WeasyPrint PDF; pip-audit + pnpm audit clean. Two contract regressions caught by the suite and fixed before commit (catalogue size, LIVE default). Evidence `handover.md` B7 EV-B12-01..06; record s.3n | B13 (lifecycle, support and conditional routes) |
| B13 | Lifecycle, support and conditional routes | READY_FOR_REVIEW (2026-09-11T20:2xZ; merged to `main` per D-009 - see s.3o) | `CaseHold` (cases 0005) with guarded withdrawal TR-13 (API-030: applicant only, profile stages, disposition of obligations / attempts / notices), holds (API-031/032: listed clocks paused through the B10 pause table, TRANSITIONS / DECISIONS block scope enforced in every transition and the issuance job), TR-14 return-for-clarification (API-063: new CLARIFICATION attempt, no-visit addendum refused as SERVICE_DISABLED); `CertificateStatusInstrument` (certificates 0003) with pure admissibility (expired never reinstated; revocation and supersession final), API-071 status actions needing the `certificate.status` grant + evidence, API-070 linked renewal drafts that never extend validity, registry history / renewals / allowed actions; NEW app `agni.support` (support 0001): tickets with audience-filtered messages, SUPPORT_ATTACHMENT uploads readable only through ticket scope, support status machine with requester reopen, routes + appeals answering 409 SERVICE_DISABLED with the referral; profile-gated API-072/119 stubs. Web: UI-07 lifecycle block (withdraw with confirmation, hold form + release, return form), UI-17 status dialog + renewal, UI-26 support pages. Tests: backend **210 passed** alone (incl. 4 lifecycle integration + 3 admissibility unit), web **39 passed** + build, e2e **29/29** steps (one holder step NOT_RUN, covered by tests). Evidence `handover.md` B7 EV-B13-01..05; record s.3o | B14 (reporting, audit and operational UI) |
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

## 3g. Handoff record - B05 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B05 - Drafts, files and application wizard (FR-04, FR-05; task card B05; docs 05 draft/
  document tables + s.9 object identity, 24 s.2-3 + DTOs, 16 s.2-3, 08 s.3-4, 03 UI-05/06/07 +
  s.6-7, 06 API-020..023/033..037, 11 AT-04/AT-05)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b05-drafts from feat/b04-policy @ 2c35c0a
Files inspected: FR-04/05, data model draft_revision/submission_*/upload_reservation/
  document_version/document_access/logical_job/job_attempt + s.9, form schemas s.2-3/6/7-8,
  integrations s.2-3, async jobs s.3-4, UI-05/06/07 + wizard state s.6 + error screens s.7,
  API rows + DTOs DraftCreate/DraftPatch/UploadReservation/UploadComplete/DocumentAccess,
  AT-04-01..06, AT-05-01..06.
Changes made and architecture decisions: NEW app agni/documents (models 0001, ports, adapters
  s3/memory/scanners, application/commands, api/{views,urls}, selectors, scanning); platform
  LogicalJob/JobAttempt (0002) + jobs.py + management/commands/process_jobs; cases DraftRevision +
  Application.current_draft_revision (0003), domain/drafts, application/{access,drafts},
  CreateDraftApplication (service_id/application_type, revision 1 with pinned form schema),
  api/views (API-020/022/023) + urls; policies/selection (case-insensitive category match);
  platform/errors (explicit FILE_*/UPLOAD_*/EVIDENCE_INCOMPLETE classes); settings (object
  store/scanner/upload/job settings; production refuses non-S3 storage and demo scanner in LIVE;
  test settings memory store + demo scanner); config/urls; compose `worker` service; web
  api/applications.ts, features/applications/{useDraftAutosave,ApplicationsListPage,
  NewApplicationPage,ApplicationWizardPage,ApplicationDetailPage}, router, AppShell nav, locales;
  scripts/dev/smoke_drafts.py; tests (4 new modules).
  Decisions: (1) uploads stream through the API to a private staging key - the browser never
  receives bucket credentials or presigned URLs; completion promotes verified bytes to a
  content-addressed `objects/<sha256>` key that is never overwritten, and scan/access bind to
  (key, sha256); (2) the scan verdict is written only by the worker under the job lease fence,
  exactly once, after re-hashing the object; UNKNOWN (outage, timeout, clamd ERROR) never becomes
  CLEAN - the job retries with backoff and the version stays QUARANTINED; (3) a draft autosave
  is an append-only revision + audit row, deliberately NOT a timeline CaseEvent (autosave every
  800 ms would drown the case timeline); (4) the stale-tab 412 carries current_draft_revision
  and current_fields so the UI can show differences and reapply chosen edits with a new command
  key; (5) declarations D01-D03 are backend demo constants served to the UI (single source; to
  move into the FORM artifact with the admin tooling phase); (6) only the applicant owner, the
  acting operator or a delegate with `draft.edit` may edit; case.read delegates see but cannot
  save; (7) Submit is shown as unavailable with a safe reason until B06 delivers TR-01 - the
  wizard never turns a save into a submission; (8) the durable job table is the source of truth
  for asynchronous work; Celery/RabbitMQ wake-ups are wired at B10 (recorded limitation).
Migrations/data impact: platform 0002, documents 0001, cases 0003 (nullable FK + new table);
  applied on the LOCAL dev DB by the api container; smoke run leaves synthetic drafts/uploads.
Tests actually executed (Windows host, 2026-09-10T23:5x-2026-09-11T00:5xZ):
  uv run --directory backend ruff format . && ruff check . && mypy config agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (154 files; no drift)
  uv run --directory backend pytest tests -q -> 137 passed (88 s) incl. the S3 adapter test
    against the live Compose SeaweedFS (skips with reason when the endpoint is down)
  corepack pnpm typecheck / lint / test --run / build -> tsc clean, 0 problems, 22 passed,
    built (evidence/B05-web-vitest.log)
  docker compose ... up -d --wait api worker -> api healthy (cases 0003, documents 0001,
    platform 0002 applied), worker healthy ("handlers: document.scan")
  docker compose ... up -d clamav -> never healthy (17 min, 1.42 GiB / 1.5 GiB, api starved);
    stopped -> ClamAV verdict BLOCKED on this host
  docker compose ... up -d --wait objectstore after raising -volume.max 8 -> 64 (every PUT had
    failed: "No writable volumes and no free volumes left" for the bucket collection)
  worker paused; uv run --directory backend python ../scripts/dev/smoke_drafts.py
    http://127.0.0.1:5173 --expect-scan QUARANTINED -> ALL DRAFT/UPLOAD SMOKE STEPS PASSED (17)
    (evidence/B05-smoke-drafts.log)
  docker exec -e SCANNER_PROVIDER=demo_eicar agni-dev-api-1 python manage.py process_jobs --once
    -> claimed=1 complete=1; DocumentVersion plan CLEAN demo_eicar; LogicalJob COMPLETE, attempt
    SUCCESS, 1 scan audit row; worker started again
Tests not executed and concrete reason: AT-04-06/AT-05-06 browser/keyboard/viewport checks
  (Playwright suite arrives B16/B19); resumable multipart upload (not implemented by design -
  single bounded PUT, docs/16 s.3 step 3); preview derivatives (original served with nosniff +
  sandbox CSP; sanitized derivatives are a later slice); Celery broker wake-up (B10).
Screens inspected: /applications, /applications/:id/edit and /applications/:id rendered in
  jsdom tests only; served bundle not opened in a browser this session.
Processes restarted and smoke-check result: api rebuilt (healthy), worker started (healthy),
  objectstore recreated with the larger volume budget (data volume kept), ClamAV started and
  stopped (never healthy); smoke 17/17 + demo-scanner worker pass CLEAN; see EV-B05-04..08.
Blocked: EV-B05-05 real ClamAV verdict (host RAM). Unblock: Docker Desktop memory >= 5 GB or
  run the `full` profile on CI; the worker then scans automatically and `smoke_drafts.py`
  without `--expect-scan` must report CLEAN + a successful ticketed download.
Security/privacy or external-effect considerations: no client-supplied checksum/size/state is
  trusted; media type verified by magic bytes; REJECTED files never served; tickets signed,
  principal-bound, 5 min, audited; object keys random/server-generated; scanner never receives
  browser paths; production refuses in-memory storage and demo scanners.
Remaining defects and reproduction: NONE known.
Required human input: review/merge PRs (gh CLI not authenticated - BL-006).
Next safe task: B06 - Submission, routing and case visibility.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3h. Handoff record - B06 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B06 - Submission, routing and case visibility (FR-06, FR-07, FR-09; task card B06; docs 02
  s.2-5, s.7-10, 05 submission/routing_exception/obligation tables, 06 API-020..028 + s.8-9,
  24 Submission/RoutingResolution/Reason DTOs, 03 UI-05/07/09, 11 AT-06/AT-07/AT-09)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b06-submission from feat/b05-drafts @ a9367b6
Files inspected: workflow lifecycle + transition catalogue + non-transition commands + supporting
  state machines + pinning + clock model (worked tests) + atomic transition algorithm; event
  envelope and submit example; UI-09; data model tables; security audience rules; AT lists.
Changes made and architecture decisions: NEW app agni/obligations (models 0001, domain/clock);
  routing.RoutingException (0003); cases SubmissionRevision/SubmissionDocument (0004);
  cases/application/submission.py (SubmitApplication, StartScrutiny, ResolveRoutingException,
  shared enter_stage/record_event/event_envelope helpers); cases/api/case_views.py (application
  endpoints + overview) with views.py reduced to premises; urls; tests conftest fixtures
  (supervisor, leadership, foreign_supervisor; routing rows materialised); web api/cases.ts,
  SubmitPanel, wizard submit, detail timeline/actions, OverviewPage, routes/nav/locales;
  seed_demo calendar per workflow s.8 + immutable artifact republishing; smoke_submission.py.
  Decisions: (1) fence order principal -> service activation -> application (workflow s.9) so a
  concurrent activation can never interleave with a submission; (2) the case-target obligation is
  associated with the SUBMITTED stage instance where it started (data model requires exactly one
  instance); (3) the scrutiny task obligation is created at submission and owned by the routed
  queue; TR-02 does not create another obligation at B06 (stage clocks per later phases); (4)
  a routing failure never blocks the receipt: the case is SUBMITTED, owned by the service's
  accountable central queue, with an OPEN exception, and the case clock runs; (5) scrutiny cannot
  start while an exception is OPEN (409 ROUTING_UNRESOLVED); (6) RESTRICTED events are not
  exposed by any B06 projection; applicants get PUBLIC_CASE only; (7) public references are a
  per-year sequence with savepoint retry, random suffix only after six collisions; (8) the
  supervisor's internal note at TR-02 is an INTERNAL event (`scrutiny.note.v1`), never copied to
  the applicant; (9) the web submit reuses one idempotency key across retries and turns a network
  timeout into "Outcome not confirmed" with Check status / Retry safely (UI s.7).
Migrations/data impact: cases 0004, obligations 0001, routing 0003; applied on the LOCAL dev DB
  by the api container; seed_demo publishes CALENDAR artifact number 2 (spec calendar) because
  number 1 carried the earlier Mon-Sat 09:30-17:30 content (artifacts are immutable).
Tests actually executed (Windows host, 2026-09-11T01:0x-02:xxZ):
  uv run --directory backend ruff format . && ruff check . && mypy config agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (167 files; no drift)
  uv run --directory backend pytest tests -q -> 154 passed in 157 s (evidence/B06-backend-pytest.log)
  corepack pnpm typecheck / lint / test --run / build -> clean, 23 passed (9 files;
    evidence/B06-web-vitest.log), built
  docker compose ... up -d --wait api worker -> healthy; cases 0004, obligations 0001,
    routing 0003 applied on start; seed_demo -> CALENDAR artifact number 2 published
  worker paused; uv run --directory backend python ../scripts/dev/smoke_submission.py
    http://127.0.0.1:5173 --scan-via-demo --oidc -> ALL APPLICANT SUBMISSION SMOKE STEPS PASSED
    (37) and ALL STAFF SUBMISSION SMOKE STEPS PASSED (8); worker started again
    (evidence/B06-smoke-submission.log)
Tests not executed and concrete reason: AT-06-06/07-06/09-06 browser checks (Playwright at
  B16/B19); notifications to permitted participants on exception resolution (B10 dispatcher;
  the outbox intents are written); pause intervals/holds (B13) - the clock model supports them
  and is unit-tested, no command creates them yet; UI-15 obligations screen (B10/B14).
Screens inspected: jsdom tests for /overview and the wizard/detail; served bundle not opened in
  a browser this session.
Processes restarted and smoke-check result: api + worker recreated on the B06 image (healthy);
  smoke 37/37 + 8/8 (EV-B06-04..06).
Security/privacy or external-effect considerations: no client-supplied status/queue/policy is
  trusted; supervisor scope is the accountable queue's jurisdiction (out of scope == 404);
  leadership is read-only; internal notes never reach applicant projections; receipts carry
  safe ids only.
Remaining defects and reproduction: NONE known.
Required human input: review/merge PRs (BL-006); larger host for ClamAV (BL-007).
Next safe task: B07 - Assignment and appointment management.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3i. Handoff record - B07 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B07 - Assignment and appointment management (FR-08, FR-11; task card B07; docs 02 s.4-5,
  05 inspection/assignment/availability tables + s.5 constraint SQL, 06 API-029/038..046/094,
  24 InspectionRequest/ScheduleCommand/ReassignCommand/CheckIn/FailedVisit/Availability/
  ScheduleQuery/InspectionListQuery, 03 UI-10/11/12, 07 permission matrix, 11 AT-08/AT-11)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b07-assignments from feat/b06-submission @ 147f5cf
Files inspected: as listed; workflow s.4 (non-transition commands) and s.10 (missed
  appointments generate rescheduling work, not auto-closure).
Changes made and architecture decisions: NEW agni/inspections (models 0001 with
  BtreeGistExtension, eligibility.py, application/commands.py, selectors.py, api/{views,urls});
  platform/errors (ASSIGNMENT_CHANGED, OFFICER_UNAVAILABLE, APPOINTMENT_CONFLICT classes);
  cases/selectors (officers see assigned cases), cases/api/case_views (require-inspection action,
  inspections summary); config settings/urls; tests conftest (officers fixture) +
  test_inspections.py; web api/inspections.ts, features/inspections/{InspectionsQueuePage,
  SchedulePage,InspectionDetailPage}, ApplicationDetailPage (require inspection + list), router,
  nav (officer -> /inspections), locales, queue test; scripts/dev/smoke_inspections.py.
  Decisions: (1) booking safety is layered: officer scheduling fence (the principal fence row)
  + availability check + overlap pre-check for a readable 409 + the GiST exclusion constraint as
  the final guard; intervals are half-open so 06:30 end / 06:30 start do not collide; (2) an
  attempt that is cancelled or fails automatically opens the follow-up REQUESTED attempt while
  the case is INSPECTION_PENDING (the case still needs a visit; BR-01 accountability); the
  INSPECTION_TASK obligation and the case target keep running; (3) reassignment supersedes the
  previous assignment and the stale officer loses command authority immediately (404 on
  check-in), which is how "revoke stale offline authority" is realised before B11; (4) officer
  identity is internal - applicant projections carry the appointment only; (5) check-in without
  GPS requires an explicit reason; coordinates are never fabricated; (6) eligibility is the
  OFFICER binding in the case's jurisdiction (NULL binding never global); (7) the `/officers`
  roster is a scoped scheduling helper, distinct from the B14 staff admin API-087.
Migrations/data impact: inspections 0001 (btree_gist extension + 3 tables); applied on the LOCAL
  dev DB by the api container; smoke left one FAILED + one REQUESTED attempt on a demo case.
Tests actually executed (Windows host, 2026-09-11T02:4x-03:4xZ):
  uv run --directory backend ruff format . && ruff check . && mypy config agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (179 files; no drift)
  uv run --directory backend pytest tests -q -> 159 passed in 160 s (evidence/B07-backend-pytest.log)
  corepack pnpm typecheck / lint / test --run / build -> clean, 24 passed (10 files;
    evidence/B07-web-vitest.log; a first run under CPU contention lost 3 workers and was
    re-run alone), built
  docker compose ... build api (first background attempt produced no new image - recorded, then
    rebuilt in the foreground: new image id) ; build web ; up -d --wait api worker web ->
    inspections 0001 applied on start; web serves the B05-B07 bundle
  smoke_submission.py --scan-via-demo --oidc -> PASS (fresh SCRUTINY case; evidence/B07-smoke-submission.log)
  uv run --directory backend python ../scripts/dev/smoke_inspections.py http://127.0.0.1:5173
    -> ALL INSPECTION SMOKE STEPS PASSED (21; evidence/B07-smoke-inspections.log)
Tests not executed and concrete reason: AT-08-06/AT-11-06 browser checks (Playwright at
  B16/B19); applicant notification of the appointment (B10 dispatcher; the public event and
  outbox intent exist); offline package revocation (B11); travel buffers (policy option not in
  the demo profile).
Screens inspected: jsdom test for UI-10; UI-11/12 rendered by typecheck/build only; served
  bundle not opened in a browser this session.
Processes restarted and smoke-check result: api, worker and web recreated (healthy); smoke 21/21.
Security/privacy or external-effect considerations: supervisor scope = accountable queue's
  jurisdiction (out of scope == 404); officers act only on their ACTIVE assignment; applicants
  never see officer identity or internal assignment events; no client-supplied officer state.
Remaining defects and reproduction: NONE known. Note: a `docker compose build` run in the
  background once exited 0 without producing a new image; verify the image id after builds.
Required human input: review/merge PRs (BL-006); larger host for ClamAV (BL-007).
Next safe task: B08 - Inspection reports and checklist evaluation.
End commit and worktree status: recorded in handover.md B12 after commit/push.
```

## 3j. Handoff record - B08 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B08 - Inspection reports and checklist evaluation (FR-13, FR-14; task card B08; docs 02
  TR-06, 05 inspection_draft/inspection_report/report_evidence(/finding), 06 API-045/047 +
  ReportReceipt, 24 s.4 Observation + demo checklist table + ReportDraft/ReportSubmit, 03 UI-12,
  07 permission matrix, 09 manifest example, 11 AT-13/AT-14)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b08-reports from feat/b07-assignments @ f713c08
Files inspected: as listed plus the B07 inspections commands/views (helpers reused), the
  documents commands (upload target allowlist), submission helpers (record_event/enter_stage),
  the clock model and the seed command.
Changes made and architecture decisions: NEW agni/inspections/domain/checklist.py (pure
  validator + evaluator), NEW agni/inspections/application/reports.py (SaveReportDraft,
  SubmitReport, draft_body, report_body), models InspectionDraft/InspectionReport/
  ReportEvidence + Inspection.current_report (migration inspections 0002), api views/urls
  (PUT /inspections/{id}/draft, POST /inspections/{id}/reports, detail projection + actions),
  documents/application/commands.py (INSPECTION_EVIDENCE target for the assigned officer;
  CompleteUpload resolves the owning case per target type; quota counts inspection
  reservations), cases/api/case_views.py (per-attempt report facts, audience-filtered),
  seed_demo CHECKLIST_ITEMS aligned to docs/24 s.4; tests unit/test_checklist.py +
  integration/test_reports.py; web api/inspections.ts (types + saveReportDraft/submitReport),
  api/applications.ts (uploadFile for any permitted target), features/inspections/
  ReportWorkspace.tsx (+ ReportView), InspectionDetailPage (workspace/report wiring),
  InspectionDetailPage.test.tsx, locales; scripts/dev/smoke_reports.py; infra/compose/README.
  Decisions: (1) the evaluator is deterministic and score-free: blockers are a list of codes
  per item; eligibility is simply "no blockers"; nothing compensates a mandatory blocker;
  (2) a report with mandatory blockers is still ACCEPTED as the immutable record and TR-06 still
  moves the case to REVIEW_PENDING - the blockers travel with the report to the decision (B12)
  and to notices (B09); nothing auto-rejects; (3) permitted NOT_APPLICABLE needs a rationale
  and is always listed for reviewer confirmation (docs/24 "NA with rationale and review");
  (4) evidence must be a CLEAN DocumentVersion of the same application - wrong-case, unknown
  or still-quarantined files are refused at draft and submit time (422 per pointer); the
  accepted report pins each evidence sha256/object key; (5) the draft is a versioned child so
  saving does not move the inspection version (the inspection ETag still guards the save;
  the reply ETag is the draft's); (6) the report author is always the current ACTIVE
  assignee who has checked in - supervisors/other officers get 404, applicants 403; the
  submitter of the accepted report gets 409 INVALID_TRANSITION on a fresh retry so a client
  can tell "already accepted" from "not yours"; (7) officers upload evidence through the same
  reserve/PUT/complete/scan pipeline as applicants (INSPECTION_EVIDENCE target, item-coded
  requirement `inspection-c0N`), so provenance and scanning rules are identical; (8) Finding
  rows (data model `finding`) are deferred to B09 where notices consume them - the report's
  evaluation JSON already carries itemised findings with severity.
Migrations/data impact: inspections 0002 (3 tables + Inspection.current_report). Seed
  republishes the CHECKLIST artifact as number 2 (content-addressed; old attempts keep #1).
Tests actually executed (Windows host, 2026-09-11):
  uv run --directory backend ruff format . && ruff check agni tests && mypy agni -> PASS
    ("All checks passed!"; "Success: no issues found in 146 source files")
  uv run --directory backend pytest tests/unit/test_checklist.py tests/integration/test_reports.py
    -q -> 13 passed (first run: 1 failure - fresh submit on a closed attempt answered 404;
    decision (6) added and re-run green)
  uv run --directory backend pytest -q -> 172 passed in 376 s (evidence/B08-backend-tests.log)
  corepack pnpm --dir web typecheck / lint / build -> clean, built (473.85 kB js)
  corepack pnpm --dir web test --run -> 24 passed, 1 failed (PolicyDetailPage timed out at
    5 s under CPU contention); re-run of that file alone -> 1 passed => 25/25
    (evidence/B08-web-tests.log)
  uv run --directory backend python manage.py makemigrations --check --dry-run -> No changes detected
  docker compose ... build api web -> image ids verified afterwards (api f2a37b6959e4 created
    02:59Z, web ffcdf409e140 created 03:06Z); up -d --wait api worker web -> healthy;
    showmigrations inspections -> [X] 0001_initial [X] 0002_reports; seed_demo -> idempotent,
    CHECKLIST demo-checklist-v1 now numbers 1 and 2 (number 2 = docs/24 s.4 flags)
  worker stopped; uv run --directory backend python ../scripts/dev/smoke_reports.py
    http://127.0.0.1:5173 -> ALL REPORT SMOKE STEPS PASSED (32 steps;
    evidence/B08-smoke-reports.log); worker started again
  Clock note: real `date -u` at this record = 2026-09-11T03:1xZ; the B07 checkpoint stamps
    CP-034..039 in handover.md ran ~1 h 20 min ahead of the real clock (estimated without
    `date -u`); from CP-040 on, stamps are taken from `date -u`.
Tests not executed and concrete reason: AT-13-06/AT-14-05/06 browser + offline variants
  (B11/B16/B19); real ClamAV verdict (BL-007); Playwright.
Screens inspected: jsdom test of the report workspace (draft restore, NA gating, note
  prompts, submit payload/If-Match, accepted report with blockers); served bundle not opened
  in a browser this session.
Processes restarted and smoke-check result: api, worker, web recreated on the B08 images
  (healthy); smoke_reports.py 32/32.
Security/privacy or external-effect considerations: report authorship bound to the current
  ACTIVE assignment; evidence scoped to the case and CLEAN; applicant projections never carry
  blockers, notes or officer identity; no client-supplied evaluation is trusted (the server
  recomputes); no real messages sent.
Remaining defects and reproduction: NONE known.
Required human input: review/merge PRs (BL-006); larger host for ClamAV (BL-007).
Next safe task: B09 - Notices, responses and correction cycles.
End commit and worktree status: commit f0513c3 on feat/b09-reports, pushed; tree clean.
```

## 3k. Handoff record - B09 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B09 - Notices, responses and correction cycles (FR-15, FR-16, FR-17; task card B09; docs 02
  TR-03/04/07/08/09 + s.4 (submit-response never transitions) + s.5 Notice/Finding state
  machines, 05 finding/notice/notice_item/response_revision/finding_review, 06 API-053..062,
  24 NoticeItemInput/NoticeCreate/NoticeResponse/ItemReview/FindingVerification/
  ReinspectionRequest, 03 UI-08/UI-14, 07 s.5 "Publish notice / verify finding = J plus
  capability", 23 control map (info-response, finding-response, verify-finding, return-review,
  reinspect), 11 AT-15/16/17)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b09-notices from feat/b08-reports @ f0513c3
Files inspected: as listed plus identity roles (Capability.NOTICE_PUBLISH already defined),
  authz (require_capability / grant_for), cases access (delegation helpers), inspections
  commands (helpers reused: _case_event/_intent/_reason/_application_version/_new_attempt).
Changes made and architecture decisions: NEW agni/notices/{apps,models,selectors}.py,
  domain/rules.py (EVIDENCE_TYPES allowlist, item code regex, validate_items,
  pending_required_items, open_mandatory_findings, reinspection_outstanding),
  application/{findings,projections,commands}.py, api/{views,urls}.py, migrations/0001_initial;
  platform/errors.py (MandatoryFindingsOpen, NoticeNotOpen, ResponseNotVerified - codes already
  in the catalogue); cases/application/access.py (can_respond_to_notices);
  cases/api/case_views.py (_notice_facts, five guarded actions, notices + findings_summary);
  documents/application/commands.py (NOTICE_RESPONSE target, quota over notice reservations);
  inspections/application/reports.py (materialise_findings inside report acceptance);
  config settings/urls; seed_demo (anita notice.publish grant); tests conftest (supervisor
  grant + plain_supervisor fixture), tests/integration/test_notices.py, test_reports.py (two
  mypy fixes found by running `mypy tests`); web api/notices.ts, api/applications.ts
  (CaseDetail notices/findings_summary, NOTICE_RESPONSE upload target),
  features/notices/{NoticePage,CaseNotices}.tsx + NoticePage.test.tsx, ApplicationDetailPage
  wiring, router, locales; scripts/dev/smoke_notices.py; infra/compose/README.
  Decisions: (1) publication is direct (no DRAFT notice rows) - the DRAFT state stays in the
  enum for the documented state machine; (2) a superseding round is published while the case
  already waits (INFO_REQUIRED / COMPLIANCE_PENDING): no transition, original notice ->
  SUPERSEDED with its obligation CANCELLED, new APPLICANT_RESPONSE obligation started; (3)
  stage tasks: TR-03/TR-07 mark the stage task SATISFIED; TR-04/TR-08 open a fresh
  SCRUTINY_TASK / REVIEW_TASK on the new stage instance; the case target is never touched;
  (4) findings are created when the report is accepted (B08 command) so deficiency items can
  reference them; an unresolved finding for the same item is retained across reinspections;
  (5) closing a MANDATORY finding needs reviewer-attributed evidence (cited CLEAN documents or a
  PASS observation in an accepted report) - the applicant's response alone is refused; (6) the
  inspecting officer who submitted the originating report cannot verify its findings
  (separation of duties); (7) API-058 ACCEPTED on a deficiency item requires the finding to be
  VERIFIED_CLOSED first (409 RESPONSE_NOT_VERIFIED); a finding verification also accepts its
  open items; (8) response documents travel through the same reserve/PUT/complete/scan
  pipeline (NOTICE_RESPONSE target, `response-<item code>`), never a bypass; (9) NOTICE_NOT_OPEN
  is reported before field-level validation so a closed round is unambiguous.
Migrations/data impact: notices 0001 (7 tables). Seed adds one AuthorityGrant (anita,
  notice.publish). No data rewrite.
Tests actually executed (Windows host, 2026-09-11):
  uv run --directory backend ruff format . && ruff check agni tests && mypy agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (193 files; no drift)
  uv run --directory backend pytest tests/integration/test_notices.py -q -> 6 passed
    (two test fixes on the way: closed-notice 409 ordering; ETag from the response header)
  uv run --directory backend pytest -q -> **178 passed in 280 s** when run alone
    (evidence/B09-backend-tests.log). Two earlier full runs that overlapped with vitest, a
    docker build and other pytest processes on this 5.9 GB host reported 58-67 setup ERRORs
    (environmental contention); the isolated run is the recorded result.
  corepack pnpm --dir web typecheck / lint / build -> clean, built (2.5 s)
  corepack pnpm --dir web test --run -> **26 passed (12 files)** (evidence/B09-web-tests.log).
    Known flake F-01: InspectionDetailPage.test.tsx failed fast in two of four full parallel
    runs and passes alone and in the final full run; vitest testTimeout raised to 20 s; root
    cause (worker-parallel interference) not yet isolated - tracked below.
  docker compose ... build api web -> api 7bb3434e8d2c (10:26Z), web 996a0b59568e (10:35Z),
    ids verified; up -d --wait api worker web -> healthy; showmigrations notices -> [X]
    0001_initial; seed_demo -> idempotent, grants now anita:notice.publish +
    anita:policy.activate + meera:policy.approve
  worker stopped; uv run --directory backend python ../scripts/dev/smoke_notices.py
    http://127.0.0.1:5173 --scan-via-demo -> ALL NOTICE SMOKE STEPS PASSED (40 steps: fresh
    OTP applicant AS-2026-1005 submitted; anita start-scrutiny; TR-03 notice 201 ->
    INFO_REQUIRED with APPLICANT_RESPONSE due +7 days and SCRUTINY_TASK SATISFIED; second
    notice 409, empty items 422; applicant view without internal note; NOTICE_RESPONSE
    upload -> QUARANTINED -> CLEAN via one-off demo pass; reply 201 RESPONSE_RECEIVED and case
    still INFO_REQUIRED; accept-information early 409 RESPONSE_NOT_VERIFIED pending
    ['INFO-01']; review ACCEPTED 200; TR-04 200 -> SCRUTINY, notice SATISFIED, fresh
    SCRUTINY_TASK, response obligation SATISFIED; all four notice events in the applicant
    timeline) (evidence/B09-smoke-notices.log); worker started again
Tests not executed and concrete reason: AT-15-06/AT-16-06/AT-17-06 browser/accessibility
  variants (Playwright arrives with B16); UI-14 review queue page (`/reviews`) is B12 scope
  (decision readiness) - the review controls live on UI-08 for now; real ClamAV (BL-007).
Screens inspected: jsdom test of UI-08 (applicant view: returned item with feedback,
  "response received" wording, reply submission payload/If-Match); reviewer view and case
  detail actions covered by typecheck/lint/build only.
Security/privacy or external-effect considerations: notice publication and finding
  verification need supervisor role in the case jurisdiction plus the separately granted
  notice.publish capability; applicants never see internal notes, reviewer identities or
  closure evidence; evidence scoped to the case and CLEAN; no automatic finding closure; no
  real messages sent.
Remaining defects and reproduction: F-01 (test flake, not a product defect): run
  `corepack pnpm --dir web test --run` repeatedly; InspectionDetailPage.test.tsx occasionally
  fails within ~1.5 s while other files run in parallel workers, passes alone. Next step:
  run with `--no-file-parallelism` to confirm interference, then isolate (suspects: shared
  `crypto.randomUUID`/fetch stubs, timers).
Self-review (D-009, no human reviewer named): diff of feat/b09-notices reviewed for the
  forbidden shortcuts of task card B09 - no appeal terminology in the response path, published
  notice content immutable (only state/closed_at change), responses never delete or close,
  server rechecks every guard; separation of duties enforced on finding verification.
Required human input: larger host for ClamAV (BL-007); agency inputs for B20.
Next safe task: B10 - Clocks, outbox dispatch and notifications.
End commit and worktree status: commit 1c7c86f on feat/b09-notices, pushed; fast-forwarded into
  main (D-009) and pushed: origin/main = 1c7c86f. Tree clean.
```

## 3l. Handoff record - B10 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B10 - Clocks, outbox dispatch and notifications (FR-18, FR-19, FR-23; task card B10;
  docs 02 s.8 clock model + s.4/s.5, 05 obligation_pause/threshold_action/escalation/outbox/
  logical_job/notification/delivery_attempt, 06 API-008/074..080/103/104 + event families
  obligation.threshold_reached.v1 / notification.delivery_updated.v1, 08 s.2-6/8-10,
  24 EscalationCreate/Preferences/ObligationQuery/NotificationQuery, 03 UI-15/19/20,
  11 AT-18/19/23, 12 scheduler heartbeat)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b10-clocks from main/feat/b09-notices @ 1c7c86f
Files inspected: as listed plus platform jobs/outbox/models (B05 kernel), notifications demo
  sink (B03), identity contacts (encrypted verified contact, masking), eligibility roster query.
Changes made and architecture decisions:
  obligations: models (+ObligationPause, ThresholdAction, Escalation; migration 0002),
    domain/thresholds.py, application/{clock_service,scheduler,commands}.py, api/{views,urls}.py
  notifications: models (+Notification, DeliveryAttempt, NotificationPreference; migration
    0002), ports (+OutboundMessage/MessageSender/ProviderUnavailable/ProviderRejected), adapters
    (+DemoSinkMessageSender with force_failure, get_message_sender), templates.py,
    application/fanout.py (fan-out + delivery jobs, recipient rules, threshold/manual escalation
    notifications), api/{views,urls}.py (API-078/079/080/008)
  platform: dispatch.py (dispatcher + broker port), api/operations.py (API-103/104),
    management/commands/run_schedulers.py, process_jobs (registers the new kinds),
    jobs.py (current_clock() for handlers)
  config: settings (BROKER_PROVIDER, CELERY_BROKER_URL), urls (obligations, notifications, jobs)
  infra: compose.dev.yml `scheduler` service (app profile, BROKER_PROVIDER=amqp), README rows
  tests: tests/integration/test_clocks.py
  web: api/{monitoring,notifications,operations}.ts, features/monitoring/MonitoringPage(+test),
    features/notifications/NotificationsPage(+test), features/operations/OperationsPage,
    AppShell (tools nav + Notifications link), router, locales; scripts/dev/smoke_clocks.py
  Decisions: (1) timers are database facts: the scheduler scans `obligation.due_at` and the
  threshold plan every 30 s; no long Celery ETA, no browser timers; (2) reminder fractions
  apply to the active (working) budget via `due_instant(budget*fraction)`, escalation steps are
  calendar minutes after due - both from the pinned policy (`reminder_fractions`,
  `escalation_minutes_after_due`); (3) uniqueness = (obligation, stage instance, threshold
  key) on ThresholdAction + uuid5 logical job id + OneToOne Escalation.threshold_action, so
  duplicate schedulers/restarts/deliveries collapse to one effect; (4) execution re-checks
  state/generation/stage and records CANCELLED_AS_OBSOLETE instead of sending an obsolete
  reminder; (5) the dispatcher always writes the durable fan-out job and treats the broker as a
  wake-up only (row persists after broker ack; outage = visible lag); (6) in-app notification is
  the transactional intent; channel attempts are separate rows and jobs; a failed/unknown
  delivery never changes case state and never removes the in-app copy; (7) recipients derive
  from the case (applicant + acting operator) and the duty roster (supervisors of the owner
  queue's jurisdiction, assigned officer), never from request bodies; staff receive in-app only
  in the demo profile; (8) preferences cannot suppress mandatory service messages (notices,
  appointments, case receipt); (9) `NotificationPreference` replaces the spec's
  `template_artifact_id` with `template_key`+`template_version` constants because no template
  artifact table exists yet (recorded deviation; template artifacts can be introduced with the
  Hindi copy in B16); (10) the operations endpoints expose ids and safe error codes only;
  recovery commands (API-105/106) are B14; (11) ADMIN role = operations administrator for
  API-103/104 until a dedicated `operations.read` grant is modelled (B14).
Migrations/data impact: obligations 0002 (3 tables), notifications 0002 (3 tables). No data
  rewrite. New Compose service `scheduler` (app profile).
Tests actually executed (Windows host, 2026-09-11):
  uv run --directory backend ruff format . && ruff check agni tests && mypy agni tests
    && manage.py check && makemigrations --check --dry-run -> PASS (212 files; no drift)
  uv run --directory backend pytest tests/integration/test_clocks.py -q -> 5 passed
    (fixes on the way: FOR UPDATE on a nullable join in the threshold job -> of=self;
    handlers used the system clock instead of the worker pass clock -> jobs.current_clock();
    URL-encoded as_of; fan-out then delivery needs two worker passes -> drain helper)
  corepack pnpm --dir web typecheck / lint / test --run / build -> clean, **28 passed (14
    files)**, built (evidence/B10-web-tests.log)
  uv run --directory backend pytest -q (alone) -> **183 passed in 464 s** (evidence/B10-backend-tests.log)
  docker compose ... build api web -> api b89708eaf2d7 (12:33Z), web 2875d0c683fa (12:31Z), ids
    verified; up -d --wait api worker scheduler web -> all healthy incl. the NEW scheduler;
    showmigrations -> obligations 0002 + notifications 0002 applied
  scheduler container log (real RabbitMQ wake-ups, BROKER_PROVIDER=amqp): "[scheduler]
    thresholds created=9 scanned=10" then "[dispatch] scanned=34 published=34 failed=0";
    worker log: 9 obligation.threshold + 34 notification.fanout + 12 notification.deliver jobs
    all COMPLETE (retry=0 dead=0 lost=0)
  uv run --directory backend python ../scripts/dev/smoke_clocks.py http://127.0.0.1:5173 ->
    ALL CLOCK SMOKE STEPS PASSED (19 steps: anita via Keycloak; API-074 counts from one cutoff
    (overdue 3, open escalations 3 - the backlog of demo cases), API-075 clock breakdown,
    API-076 manual escalation 201 + same-key replay, API-077 acknowledge 200 then 409, one-off
    scheduler/dispatcher + worker passes in the api container, API-078 20 in-app notifications
    incl. ESCALATION, API-079 idempotent read, API-080 read-through marked 19, API-008
    preferences, arjun API-103 summary outbox pending 0 / dead 0, anita on /jobs -> 403)
    (evidence/B10-smoke-clocks.log)
Tests not executed and concrete reason: AT-18-06/AT-19-06/AT-23-06 browser variants
  (Playwright, B16); real RabbitMQ wake-up path exercised only through the container proof
  (`BROKER_PROVIDER=amqp` in the scheduler service), unit tests use the null/failing brokers;
  worker-kill fault drill (docs/08 s.10) is B17.
Screens inspected: jsdom tests of UI-15 (counts, overdue row, acknowledge with ETag) and UI-19
  (failed e-mail keeps the in-app notice, read-through boundary); UI-20 by typecheck/build.
Security/privacy or external-effect considerations: notifications are recipient-only; bodies
  carry ids and public reasons, never attachment URLs or internal notes; delivery destinations
  are masked; operations views are administrator-only and sanitised; no real messages sent
  (demo sink).
Remaining defects and reproduction: NONE known.
Required human input: larger host for ClamAV (BL-007); agency inputs for B20.
Next safe task: B11 - Offline field application.
End commit and worktree status: commit b89bacb on feat/b10-clocks, pushed (~13:2xZ); fast-forwarded
  into main (D-009) and pushed: origin/main = b89bacb.
```

## 3m. Handoff record - B11 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B11 - Offline field application (FR-12; task card B11; docs 09 (offline model: packages,
  local stores, connectivity, sync algorithm, conflicts, device hygiene), 06 API-048..052 +
  24 SyncOperation / ConflictProposal DTOs, 05 sync_operation, 03 UI-13 + UI-12 offline states,
  11 AT-12-01..06, 07 device data minimisation)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b11-offline from main/feat/b10-clocks @ b89bacb (coding began on
  feat/b10-clocks while the harness blocked git; the branch was created after the B10 fast-forward)
Files inspected: inspections commands/reports (SubmitReport, FailVisit, ReassignInspection rules),
  documents upload targets (INSPECTION_EVIDENCE), platform kernel (receipt replay,
  expected_version), identity authz snapshot, web api client / ReportWorkspace /
  InspectionDetailPage (B08), router/AppShell/locales, vitest setup, nginx config.
Changes made and architecture decisions:
  backend NEW app agni.offline (migration 0001): models.py - SyncOperation (append-only; unique
    (principal, operation_id); request_sha256; base/assignment versions; schema_version;
    state ACCEPTED | CONFLICT; stored canonical result), ReportConflict (versioned; unique
    (proposer, operation_id); local manifest + sha256; safe summary; server snapshot;
    OPEN -> RESOLVED with outcome / reason / selected evidence / resolver)
  application/sync.py - normalise_manifest (envelope + per-type keys, unknown-field and
    forbidden-field violations, schema gate, canonical sha256); process_operation runs the
    ONLINE handlers SubmitReport / FailVisit through the kernel with idempotency_key
    "sync:<operation_id>" and expected_version = base_inspection_version; identical replay
    -> the stored result (200 ACCEPTED or 409 CONFLICT, replayed=true); same id + other hash
    -> 409 SYNC_PAYLOAD_CONFLICT; refusals (412 / 409 / 422 / not-assignee -> ASSIGNMENT_CHANGED
    / AUTHORITY_REVOKED) are recorded as CONFLICT rows with the sanitised problem and a safe
    server snapshot, then re-raised with operation_id / server / sync_state extensions
  application/conflicts.py - ProposeConflict (API-051: current or former assignee only, no
    If-Match, one proposal per operation, INTERNAL event) and ResolveConflict (API-052:
    supervisor of the case jurisdiction; PROPOSE_NEW_REPORT | REINSPECTION_REQUIRED | DECLINE;
    reason 10-2000; cited evidence must be CLEAN files of the case; both versions preserved;
    second resolution -> 409)
  api/views.py + urls.py - API-048 GET /inspections/{id}/offline-package (current ACTIVE
    assignee of an open attempt with current OFFICER authority; 24 h expiry; versions;
    checklist items; limits; Cache-Control: no-store; inspection ETag), API-049 POST
    /sync/operations (ETag of the resulting inspection version), API-050 GET
    /sync/operations/{id} (owner-scoped, 404 for everyone else), POST
    /inspections/{id}/conflicts, GET /conflicts (supervisor jurisdictions + own proposals),
    POST /conflicts/{id}/resolve (If-Match "conflict:<id>:v<n>")
  platform/errors.py (+OFFLINE_PACKAGE_EXPIRED 410, SYNC_SCHEMA_UNSUPPORTED 422,
    SYNC_PAYLOAD_CONFLICT 409); config settings (INSTALLED_APPS) + urls
  web: api/offline.ts (DTOs, package fetch with ETag, sync post, receipt lookup, conflicts);
    offline/database.ts (Dexie v1 stores device_meta / packages / report_drafts /
    local_evidence / upload_state / operations / receipts / conflicts per docs/09 s.3;
    ensureDeviceMeta purges the previous principal on identity switch; unsentWork);
    offline/queue.ts (canonical JSON + SHA-256, package save/expiry, local drafts, local
    evidence blobs, queueReportOperation / queueFailedVisitOperation with manifests frozen
    once, state groups); offline/sync.ts (injected deps: upload local blobs through the normal
    INSPECTION_EVIDENCE pipeline -> wait for CLEAN -> freeze the manifest once -> POST with
    Idempotency-Key = operation_id and If-Match = package ETag -> store the receipt; network
    failure keeps the operation queued; 409/412/422 -> CONFLICT with the server problem;
    unknown outcome -> GET receipt lookup before any retry; never last-write-wins);
    offline/connectivity.ts (ONLINE / OFFLINE / SERVER_UNAVAILABLE / SIGN_IN_NEEDED from /me,
    never navigator.onLine alone); offline/deps.ts; offline/serviceWorker.ts + pwa.ts
    (production-only registration; update = user-confirmed reload); vite.config.ts VitePWA
    (static shell precache, navigateFallbackDenylist /api /static /media, no runtime caching,
    no skipWaiting / clientsClaim, dev disabled); index.html theme-color; AppShell update
    banner; features/sync/SyncPage.tsx (UI-13: connectivity badge, operations grouped by
    state with package/assignment versions, evidence size, attempts, receipts, "Sync now" /
    "this one", conflict panel local vs server with propose / discard); InspectionDetailPage
    (offline package card: download, expiry, versions; offline fallback workspace rendered
    from the stored package when the API is unreachable, incl. an offline failed visit);
    ReportWorkspace (Save on device, local evidence, Queue for sync; online submit unchanged);
    AccountPage sign-out warning for unsent local work; router /sync; officer nav link;
    locales sync.* / app.update* / account.*; nginx: sw.js / workbox runtime / manifest served
    with Cache-Control no-cache and the manifest media type
  Decisions: (1) SyncOperation / ReportConflict live in the new `agni.offline` app (FR-12
    module name) instead of `inspections`, where docs/05 lists sync_operation - recorded
    deviation, identical semantics; (2) offline operations reuse the online handlers through
    the kernel, so there is exactly one authorisation / version / evidence code path and no
    offline-specific acceptance rule; (3) one operation id = one manifest hash: identical
    replay returns the stored result, other content behind the same id is refused (no silent
    overwrite); (4) refusals are stored as CONFLICT rows with the sanitised problem and a safe
    server snapshot so the device learns the outcome after a lost response and automatic
    retries stop; (5) a former assignee receives ASSIGNMENT_CHANGED (not 404) because they
    held a package - staff who never held one get 404; (6) the package is a read model with an
    explicit expiry (24 h demo default) and versions; it proves nothing and the server never
    trusts it; (7) the service worker precaches only the static shell and never API responses;
    case data lives in IndexedDB under app control; updates require a user-confirmed reload;
    (8) API-048 expiry uses the settings clock (SystemClock in production and tests) - the test
    asserts the 24 h delta; (9) local evidence blobs upload at sync time through the normal
    upload pipeline, so scan / quota rules are unchanged and a manifest is frozen only with
    CLEAN server references; (10) workbox-window is a direct dev dependency because the
    plugin's virtual register module imports it and pnpm's strict layout does not hoist it;
    (11) HARDENING of B07/B08 commands: `_assigned_officer_only` (CheckIn, FailVisit,
    SaveReportDraft, SubmitReport - online and via sync) now also requires the actor's OFFICER
    role for the case jurisdiction to be in force at command time (`load_snapshot` +
    `has_role`), answering AUTHORITY_REVOKED (403) otherwise - an ACTIVE assignment alone is
    not authority (task card B11 proof "revoked authority blocked"; docs/09 s.7). A disabled
    account is stopped earlier at the session boundary (401, epoch recheck) and nothing is
    recorded; (12) the test clock is now injected into the offline views too
    (`agni.offline.api.views.get_clock` in the signed_client fixture) so API-048 expiry is
    asserted exactly.
Migrations/data impact: offline 0001 (2 tables). No data rewrite. No new Compose service.
Tests actually executed (Windows host, 2026-09-11):
  uv run --directory backend ruff format agni tests && ruff check agni tests && mypy agni tests
    -> PASS (224 files); manage.py check -> no issues; makemigrations --check --dry-run ->
    "No changes detected"
  uv run --directory backend pytest tests/integration/test_sync.py -q -> 3 passed in 39 s
    (AT-12-01/02/04/05 + API-051/052) after two fixes found by running: expires_at was
    compared with the FrozenClock although API-048 used the un-patched settings clock (now
    injected via the fixture); ReassignInspection only accepts unstarted attempts -> new
    scheduled_visit fixture for the superseded-assignment scenario; then **4 passed in 64 s**
    with the added revoked-authority test (role binding revoked -> sync 403 AUTHORITY_REVOKED
    recorded as CONFLICT, package 403, online submit 403, assignment untouched; disabled
    account -> 401 at the session boundary, nothing recorded)
  corepack pnpm --dir web install / typecheck / lint -> clean (fixes: ObservationResult typing
    in queue.ts, unused import); test --run -> 33 passed (15 files) incl. offline/sync.test.ts
    (5 specs on fake-indexeddb: upload -> freeze -> receipt; network failure keeps the queue;
    409 -> CONFLICT stored; unknown outcome -> lookup; failed-visit op)
    (evidence/B11-web-tests.log); build -> PASS with dist/sw.js + manifest.webmanifest
    (precache 5 entries, 666 KiB; chunk-size warning 658 kB - route code-splitting is a B17
    performance item); pnpm audit -> "No known vulnerabilities found"
  uv run --directory backend pytest -q (full suite): first run 13:55-14:08Z overlapped the web
    pipeline -> "1 failed, 159 passed, 34 errors": PostgreSQL killed a backend (signal 13,
    Broken pipe) twice and ran crash recovery; every error is a connection refused during
    recovery (BL-008, environmental - handover B7 EV-B11-04). Rerun ALONE 14:13-14:31Z ->
    **186 passed in 1088 s** (tree before the authority fence). Final run ALONE on the final
    tree 14:39-14:45Z -> **187 passed in 320.92 s**, 0 PostgreSQL recovery events
    (evidence/B11-backend-tests.log)
  docker compose -p agni-dev ... build api web -> api eecf7c16b76e (14:48:53Z), web 760efc9d3e6b
    (14:55:13Z); up -d --wait api worker scheduler web -> all healthy; running containers verified
    against those image ids (api/worker/scheduler = eecf7c16b76e, web = 760efc9d3e6b);
    showmigrations offline -> [X] 0001_initial applied on start
  uv run --directory backend python ../scripts/dev/smoke_offline.py http://127.0.0.1:5173 ->
    ALL OFFLINE SMOKE STEPS PASSED (18 steps through nginx + Keycloak, 15:01Z: anita
    require-inspection on AS-2026-1005 + schedule Priya; Priya API-048 package with 24 h expiry
    and versions, anita 404 on the officer package; schema 0.9 -> 422 SYNC_SCHEMA_UNSUPPORTED;
    RECORD_FAILED_VISIT sync -> VISIT_OUTCOME receipt; same manifest -> replayed receipt with the
    same command_id; same id + other content -> 409 SYNC_PAYLOAD_CONFLICT; API-050 lookup 200 for
    Priya / 404 for anita; case INSPECTION_PENDING with FAILED + REQUESTED attempts; report
    against the closed attempt -> 409 ASSIGNMENT_CHANGED recorded as CONFLICT; API-051 proposal
    201 OPEN; API-052 resolve DECLINE 200) (evidence/B11-smoke-offline.log)
  curl -sI http://127.0.0.1:5173/sw.js -> 200, Content-Type application/javascript,
    Cache-Control: no-cache; /manifest.webmanifest -> 200, application/manifest+json, no-cache
    (nginx serves the worker and manifest revalidated on every visit)
Tests not executed and concrete reason: AT-12-03 storage-error and eviction drills and
  AT-12-06 browser offline / airplane-mode / narrow-viewport checks need a real browser
  (Playwright, B16/B19); local schema migration ("migration preserves drafts") has no test yet
  because the Dexie schema is at its first version - the first `version(2).upgrade` must ship
  with that test; ClamAV real verdict BL-007.
Screens inspected: jsdom tests of the sync algorithm; UI-13 SyncPage and the UI-12 offline
  states by typecheck/build only (NOTE: no jsdom spec for /sync yet - add with AT-12-06).
Security/privacy or external-effect considerations: packages hold the minimum (case
  reference, premises display name / locality / category, checklist, versions) - no applicant
  contact data, no internal notes; Cache-Control: no-store on the package; local stores are
  purged when a different principal signs in on the device; sync and receipt endpoints are
  owner-scoped; conflict listings are jurisdiction-scoped; no real messages, no signing.
Remaining defects and reproduction: NONE known.
Self-review (D-009, no human reviewer named): diff reviewed against task card B11 forbidden
  shortcuts - no navigator.onLine-only status, no client-side acceptance, manifests never edited
  behind an id, no automatic retry after 409/412, conflicts never auto-resolved, the worker
  caches no API data.
Required human input: larger host for ClamAV (BL-007); agency inputs for B20.
Next safe task: B12 - Decisions, issuance and verification.
End commit and worktree status: commit a125d50 on feat/b11-offline, pushed (15:11Z); fast-forwarded
  into main (D-009) and pushed: origin/main = a125d50.
```

## 3n. Handoff record - B12 session claude-20260910T172516Z-b00b (2026-09-11)

```text
Task: B12 - Decisions, issuance and verification (FR-20, FR-21, FR-22; task card B12; docs 02
  s.3 TR-10/11/12 + s.6 profile (reject_from, separation_of_duties, sample_validity_days,
  public_fields), 05 decision / issuance_request / certificate (+ certificate_status_instrument
  deferred to B13), 06 API-064..069 + API-073 + s.7 "Certificate and verification" + s.9
  "Record a decision", 16 s.2 ports, s.5 issuance boundaries, s.6 unknown signing outcomes, s.7
  verification, 24 DecisionCommand / CertificateListQuery, 03 UI-01/14/16/17/18, 11 AT-20/21/22)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b12-decisions from main/feat/b11-offline @ a125d50
Files inspected: cases submission helpers (_lock_case_for_staff, record_event, enter_stage),
  states TRANSITIONS, notices commands (_satisfy/_open_obligation/_task_budget/_pinned_policy),
  inspections commands (_intent), identity authz (grant_for/require_capability, RoleBinding),
  documents ports/adapters/scanning (job pattern, object store), platform jobs/outbox/audit,
  policies seed (profile keys), notifications templates/fanout, web api/pages patterns.
Changes made and architecture decisions:
  NEW app agni.decisions (migration 0001): models.Decision (append-only; unique
    (application, decision_number) and one final decision per case; evidence_snapshot,
    policy_version, authority_grant, actor, reason, public_reason, accepted_at, sha256);
    domain/readiness.py (pure guard list: DECISION_EXISTS, STATUS_NOT_REVIEW_PENDING,
    ROUTING_UNRESOLVED, INSPECTION_OPEN, NO_ACCEPTED_REPORT, REPORT_NOT_ELIGIBLE,
    MANDATORY_FINDINGS_OPEN, REINSPECTION_OUTSTANDING, NOTICE_OPEN, AUTHORITY_MISSING /
    AUTHORITY_SCOPE_MISMATCH, SEPARATION_OF_DUTIES; reject: DECISION_EXISTS, STATUS_NOT_PERMITTED
    from the profile's reject_from, authority); application/commands.py (case_facts /
    actor_facts from the database, readiness_body for API-064, RecordDecision for API-065:
    DecisionCommand validation incl. mandatory review_acknowledged and no caller-specified
    actor/grant/status/number, current-revision and current-report checks -> 412
    VERSION_CONFLICT with `changed` = submission_revision | report (a stale read of the
    reviewed evidence), readiness re-evaluated under the case lock -> 403 FORBIDDEN /
    AUTHORITY_SCOPE_MISMATCH / SEPARATION_OF_DUTIES or 409 INVALID_TRANSITION carrying the
    `blockers` extension, TR-10 / TR-12 via transition_for, PUBLIC_CASE decision event + INTERNAL
    decision.rationale.v1, REVIEW_TASK satisfied, APPROVE opens ISSUANCE_TASK (calendar budget
    issuance_calendar_minutes) and creates the issuance request in the same transaction,
    REJECT cancels the open obligations; audit with the grant id; outbox intent);
    api (DecisionReadinessView supervisor-only + no-store; DecisionsView GET list with staff
    context / POST command).
  NEW app agni.certificates (migrations 0001/0002): models IssuanceRequest (versioned; unique
    decision, logical_action_id, certificate_number; READY -> PROCESSING ->
    RECONCILIATION_REQUIRED | PUBLISHED | FAILED; frozen render_snapshot; token hash +
    Fernet ciphertext; artifact FK; provider_request_id; signature_verification; attempts;
    last_error_code; reconciliation_note), CertificateArtifact (append-only content-addressed
    object key, sha256, size, media type, mode, renderer), Certificate (unique number and token
    hash; recorded_status ACTIVE/SUSPENDED/REVOKED/SUPERSEDED; predecessor; external source
    tuple; is_demo), CertificateSequence (per-year allocator locked FOR UPDATE);
    ports.py (CertificateRenderer, CertificateSigner submit/lookup, SignatureVerifier with
    typed unavailable / unknown / rejected outcomes); adapters.py (SimulatedRenderer -> minimal
    valid PDF for hermetic tests; WeasyPrintRenderer -> HTML with watermark, facts table, QR
    (qrcode) of the verification link; DemoWatermarkSigner: receipt = watermark statement bound
    to the artifact hash, NOT a digital signature, class hooks force unavailable / unknown /
    rejected and lookup states; DemoSignatureVerifier hash match); application/issuance.py
    (allocate_certificate_number AGNI-DEMO-<year>-<n>, create_issuance_request + durable job
    `certificate.issue` with the uuid5 logical id; job: freeze snapshot + mint 256-bit token
    once -> render + store once (staging -> promote, never overwritten) -> lookup by the stable
    id when a provider id exists -> submit -> verify -> publish inside the completion
    transaction: re-lock request + case, re-check APPROVED_PENDING_ISSUE, create Certificate,
    TR-11 -> COMPLETED with a SYSTEM certificate.published.v1 event, ISSUANCE_TASK +
    CASE_TARGET satisfied, audit rows, outbox intent; unknown/rejected/invalid ->
    RECONCILIATION_REQUIRED + job UNKNOWN/PERMANENT, no second number; reconcile_issuance
    resumes the same identity), application/registry.py (effective_status precedence:
    REVOKED/SUPERSEDED final; expired interval -> EXPIRED over ACTIVE and SUSPENDED; public
    projection = approved subset only), api (API-067 list with pending-issuance cards, API-068
    detail with verification_url for authorised readers, API-069 audited reader-bound
    ticket, artifact GET with integrity check and Cache-Control private/no-store, API-073
    anonymous verification: per-IP rate limit failing closed to 503 VERIFICATION_UNAVAILABLE,
    token hash lookup, exact-number lookup only in DEMO under PUBLIC_LOOKUP_PROFILE=
    TOKEN_OR_NUMBER, 404 unknown without hints, no-store), management command
    reconcile_issuance (operator path until API-105/106 in B14).
  platform/errors (+VerificationUnavailable class; the 51-code catalogue of docs/06 s.5 is
    unchanged - decision guards use INVALID_TRANSITION + `blockers`, stale evidence uses
    VERSION_CONFLICT + `changed`, as the contract test `test_problem_json` enforces);
    cases/api/case_views (decision / issuance / certificate / decision_readiness in CaseDetail;
    approve / reject actions from the readiness, publish-instrument = SYSTEM_JOB);
    notifications templates decision.approved.v1 / decision.rejected.v1 /
    certificate.published.v1 (+ fan-out context keys); process_jobs registers the kind; seed
    grants anita `case.decide`; settings CERTIFICATE_RENDERER_PROVIDER (weasyprint |
    simulated), PUBLIC_VERIFY_BASE_URL, PUBLIC_LOOKUP_PROFILE, PUBLIC_VERIFY_RATE_LIMIT;
    (PUBLIC_LOOKUP_PROFILE defaults to TOKEN in LIVE and TOKEN_OR_NUMBER in DEMO);
    production LIVE refuses a demo renderer and non-TOKEN lookup; compose passes
    PUBLIC_VERIFY_BASE_URL to api + worker; pyproject mypy overrides qrcode/weasyprint.
  web: api/decisions.ts, api/certificates.ts, CaseDetail typings; UI-14 ReviewQueuePage
    (/reviews) + ReviewPage (/applications/:id/review: submitted record, report + blockers,
    findings, correspondence, readiness panel with authority + blockers, no preselected
    outcome, rationale + public reason, explicit acknowledgment, confirmation summarising the
    evidence versions, one stable command key, conflict -> reload, result "Approved -
    certificate processing" never "issued"); DecisionSummary on the case page; UI-16
    CertificatesPage (Published / Pending issuance / Historical tabs, DEMONSTRATION badge,
    exact-number or premises search); UI-17 CertificateDetailPage (status first, watermark
    label, provenance, ticketed download, copy verification link, empty status history until
    B13); UI-18 VerifyPage (/verify[/:token]: token or number, ACTIVE green only with a fresh
    answer, unknown -> "Record not found", outage -> amber "Unable to verify now" + retry, 429
    message, never cached); UI-01 home actions (Apply / track, Verify certificate) + header
    Verify link; nav Reviews (supervisor) and Certificates (applicant / supervisor /
    leadership); locales review.* / certificates.* / verify.* / decision.*.
  Decisions: (1) exactly one final decision per case in the initial profile (unique
    constraint) - appeals/corrective instruments are a separate lifecycle (B13+); (2) the
    readiness read is advisory and the command recomputes it under the lock, so UI state can
    never authorise; (3) render snapshot and verification token are frozen at the FIRST job
    attempt and the rendered artifact is stored once - every retry reuses the same number,
    token and artifact identity (docs/16 s.5-6), so WeasyPrint's non-deterministic bytes never
    matter; (4) `CertificateArtifact` is its own table (data model says "artifact_id FK"
    without a target) instead of reusing DocumentVersion, because a server-rendered
    instrument is not an applicant upload and must not enter the scan/quota pipeline; (5) the
    demo signer produces a receipt that states in words it is not a digital signature; the
    verifier is a hash match; LIVE refuses both (production settings) - no real signing is
    claimed; (6) public verification exposes exactly the approved subset (certificate_number,
    effective_status, premises display name / locality, issued_at, valid_until, issuer label,
    source, checked_at, is_demo, demo notice) and answers 404 for unknown, 503 without any
    assertion on store/registry failure, 429 above 60/min/IP; (7) status precedence for
    display: REVOKED > SUPERSEDED > EXPIRED (interval) > SUSPENDED > ACTIVE; the recorded
    administrative state is kept beneath; (8) exact certificate-number lookup is a DEMO-only
    convenience (PUBLIC_LOOKUP_PROFILE=TOKEN_OR_NUMBER; LIVE requires TOKEN); (9) rejection is
    permitted only from the stages the pinned policy lists (`reject_from`, demo:
    REVIEW_PENDING) and cancels open obligations rather than marking them satisfied; (10)
    certificate lifecycle instruments (suspend / reinstate / revoke / supersede), renewals and
    external registration (TR-15) are B13 - the detail view already shows an empty status
    history and disabled actions with reason codes; (11) the baseline certificate inventory of
    docs/13 s.6 (five seeded sample certificates) is demo fixture data for B19, not seeded here.
Migrations/data impact: decisions 0001 (1 table), certificates 0001 + 0002 (4 tables; split by
  Django because of the cross-app FK). No data rewrite. No new Compose service; api + worker
  gain PUBLIC_VERIFY_BASE_URL.
Tests actually executed (Windows host, 2026-09-11):
  uv run --directory backend ruff format agni tests && ruff check agni tests && mypy agni tests
    -> PASS (255 files); manage.py check -> no issues; makemigrations --check --dry-run ->
    "No changes detected"
  uv run --directory backend pytest tests/unit/test_decisions_and_certificates_domain.py
    tests/integration/test_decisions.py -q -> 9 passed (6 unit + 3 integration; two earlier
    runs found test mistakes, not product defects: the publish-instrument action exists only
    from APPROVED_PENDING_ISSUE, the first job backoff step is 2 min, a 366-day clock jump
    expires the test sessions) - details in handover.md B7 EV-B12-02
  corepack pnpm --dir web typecheck / lint / test --run / build -> clean, **37 passed (17
    files)**, built (evidence/B12-web-tests.log); first full vitest run had 3 worker start-up
    timeouts under host load and a router error in HomePage.test (the new public actions need a
    router) -> fixed the test, reran the 5 files and then the whole suite
  uv run --directory backend pytest -q (full suite, ALONE): first run 16:40-16:48Z ->
    "3 failed, 158 passed, 36 errors in 473 s" - two REAL contract regressions found and fixed
    (error catalogue must stay at the 51 documented codes -> INVALID_TRANSITION + `blockers`
    and VERSION_CONFLICT + `changed` instead of two new codes; LIVE default for
    PUBLIC_LOOKUP_PROFILE must be TOKEN) plus the BL-008 PostgreSQL crash recovery at 16:44:57Z
    (`signal 13`) that failed 1 test + 36 setups in the recovery window; targeted rerun
    (test_problem_json, test_production_settings incl. two new LIVE refusals, domain unit,
    test_decisions) -> 34 passed in 71.5 s; final full run ALONE 17:01-17:10Z ->
    **198 passed in 585.12 s**; 0 PostgreSQL termination / recovery lines in that window
    (evidence/B12-backend-tests.log)
  Container proof (after the user restarted Docker Desktop at ~18:47Z - the Compose CLI had
    hung twice with no output and no container events; the stale CLI processes were killed):
    docker compose build api web -> api 9097a52ee330 (17:20:49Z), web 06156ee7b85d
    (17:19:13Z); up -d --wait api worker scheduler web -> all healthy; running containers
    verified against those ids; showmigrations -> decisions 0001, certificates 0001 + 0002
    applied on start; seed_demo baseline re-run (idempotent) so anita holds `case.decide`
  uv run --directory backend python ../scripts/dev/smoke_decisions.py http://127.0.0.1:5173 ->
    ALL DECISION SMOKE STEPS PASSED (**35 steps** through nginx + Keycloak, 19:00Z: Priya
    scheduled / checked in / evidence scanned / all-PASS report on AS-2026-1005 ->
    REVIEW_PENDING; anita readiness eligible with the seeded grant; 422 without
    acknowledgment; 412 VERSION_CONFLICT (changed=submission_revision) on stale evidence; 422
    on a caller-specified status; approve -> 201 APPROVED_PENDING_ISSUE with
    AGNI-DEMO-2026-101 READY; same key replays; second decision 409 INVALID_TRANSITION;
    register shows the number only under pending issuance; one worker pass renders the REAL
    WeasyPrint sample PDF (15,136 bytes, renderer=weasyprint, DEMO_WATERMARK) and publishes ->
    COMPLETED, certificate ACTIVE, ISSUANCE_TASK + CASE_TARGET satisfied, timeline carries
    decision.approved.v1 / decision.rationale.v1 / certificate.published.v1; API-068 detail
    with provenance; API-069 ticket + PDF download with X-Agni-Artifact-Mode; API-073 by token
    (approved fields only, no-store) and by exact number; unknown -> 404; register lists
    ACTIVE) (evidence/B12-smoke-decisions.log)
  Final quality gates on the committed tree (19:0xZ): ruff check "All checks passed!"; mypy
    "Success: no issues found in 255 source files"; tsc clean; eslint clean;
    uv run pip-audit -> "No known vulnerabilities found"; pnpm audit --audit-level low ->
    "No known vulnerabilities found"
Tests not executed and concrete reason: AT-20-06 / AT-21-06 / AT-22-06 browser + accessibility
  variants (Playwright, B16/B19); AT-20-05 threaded race of two decision commands (the kernel
  fence + one-final-decision unique constraint are exercised by the same-key replay and the
  second-decision 409; a two-thread drill like AT-06-05 is a B17 reliability item); a real
  signer / signature verifier does not exist by design (docs/19 gate); ClamAV BL-007.
Screens inspected: jsdom tests of UI-14 (acknowledgment, confirmation, If-Match /
  Idempotency-Key, blockers disable Approve) and UI-18 (ACTIVE demo record; unknown vs outage);
  UI-16 / UI-17 / review queue by typecheck + build only (NOTE for B16/B19).
Security/privacy or external-effect considerations: decision payloads never carry actor,
  grant, status or certificate number; rationale is INTERNAL and staff-only; public
  verification is anonymous but rate-limited, no-store and limited to the approved subset (no
  applicant identity, contacts, private ids, evidence); artifact download is reauthorised,
  reader-bound, audited and integrity-checked; the verification token is stored as hash +
  ciphertext and recovered only for authorised readers and the rendered link; no real
  signature, no government authority, no external registration is claimed anywhere.
Remaining defects and reproduction: NONE known in the product. Environmental: BL-008
  (PostgreSQL crash recovery under host load) recurred once during the web test run.
Self-review (D-009): diff reviewed against task card B12 forbidden shortcuts - no forged
  official signature (demo watermark receipt says so), certificate numbers are never
  reallocated on retry (same request, same number, same artifact), no admin completion
  override (TR-11 only through the job's guarded publish), approval never shows "issued".
Required human input: BL-007; agency approvals for any real signing arrangement (docs/19).
Next safe task: B13 - Lifecycle, support and conditional routes.
End commit and worktree status: commit 3666a25 on feat/b12-decisions, pushed (19:16Z); fast-forwarded
  into main (D-009) and pushed: origin/main = 3666a25.
```

## 3o. Handoff record - B13 session claude-20260910T172516Z-b00b (2026-09-11/12)

```text
Task: B13 - Lifecycle, support and conditional routes (FR-24 certificate lifecycle and renewal,
  FR-30 support / withdrawal / profile-dependent appeals, FR-18 holds, FR-13 TR-14; task card
  B13; docs 02 s.3 TR-13/TR-14, s.5 Certificate / Support ticket / Appeal machines, s.6 profile
  (withdraw_from, permitted_pause_reasons, appeals, external_registration, fees), s.7 holds;
  05 case_hold / certificate_status_instrument / support_ticket / support_message (appeal and
  continuing_declaration stay disabled); 06 API-030/031/032, API-063, API-070/071/072,
  API-112..119; 24 HoldCreate, CertificateStatusCommand, RenewalCreate, ReviewReturn,
  TicketCreate/TicketMessage/TicketStatus/TicketQuery; 16 s.8, s.9, s.11; 03 UI-07 actions,
  UI-17 lifecycle, UI-26; 11 AT-24 / AT-30)
Baseline: implementation spec 2.0.0
Branch and start commit: feat/b13-lifecycle from main @ 3666a25
Files inspected: cases submission/commands helpers, inspections `_new_attempt` / `_case_event`,
  notices RequireReinspection, obligations clock_service (add_pause/end_pause), documents
  ReserveUpload/CompleteUpload/GrantDocumentAccess/selectors, policies models (PolicyState),
  routing DutyQueue, identity Capability (CERTIFICATE_STATUS exists; no case.hold / ticket.*
  capabilities - decisions below), web api/pages patterns.
Changes made and architecture decisions:
  cases: models.CaseHold (+ migration 0005: kind ADMINISTRATIVE/COURT_ORDER, reason, basis
    document, authorized_by, starts/requested_end/ends, affected_obligations, command_block_scope,
    ACTIVE/RELEASED, etag "hold:<id>:v<n>"); application/holds.py (`ensure_not_on_hold(scope)`
    guard + `hold_body`, models-only so every command module can import it);
    application/lifecycle.py: WithdrawApplication (API-030/TR-13: applicant or acting operator,
    stage must be in the pinned profile's `withdraw_from` - transition table for a draft -,
    refused while on hold, terminal: obligations CANCELLED, REQUESTED/SCHEDULED attempts
    CANCELLED with ACTIVE assignments REVOKED, PUBLISHED notices CANCELLED, PUBLIC_CASE
    application.withdrawn.v1 + INTERNAL case.disposition.v1), CreateHold (API-031: supervisor of
    the jurisdiction; one ACTIVE hold per case; only ACTIVE obligations of the case may be
    listed and are paused through clock_service.add_pause with the profile's permitted reason
    AUTHORIZED_ADMINISTRATIVE_HOLD and hold_id; command_block_scope subset of TRANSITIONS /
    DECISIONS; COURT_ORDER cites a CLEAN case document; start at most 24 h back - earlier
    backdating needs a specific authority that is not enabled), ReleaseHold (API-032: ends the
    hold's open pauses, recomputes, INTERNAL case.hold_released.v1); guard wired into every
    application transition (notices `_transition`, StartScrutiny, RequireInspection,
    accept-report, RecordDecision with scope "decision", and the issuance job which waits with
    RETRYABLE CASE_ON_HOLD instead of publishing); CaseDetail adds on_hold, holds (staff),
    prior_certificate_id, closed_at and the actions withdraw / add-hold / release-hold /
    return-for-clarification, with ON_HOLD reason codes on blocked transitions.
  notices: ReturnForClarification (API-063 / TR-14, FR-13): supervisor, current accepted report,
    nonempty items (codes of the pinned checklist), requires_new_visit must be literal true
    (false -> 409 SERVICE_DISABLED: no no-visit addendum in baseline 2.0), creates a
    CLARIFICATION attempt, REVIEW_TASK satisfied, INSPECTION_TASK opened, PUBLIC_CASE
    inspection.clarification_requested.v1 + INTERNAL note.
  certificates: models.CertificateStatusInstrument (+ migration 0003; append-only; action,
    grant, actor, effective_at, reason, public_reason, evidence, successor, status before/after);
    domain/lifecycle.py pure admissibility (ACTIVE -> SUSPEND/REVOKE/SUPERSEDE; SUSPENDED ->
    REINSTATE/REVOKE/SUPERSEDE; EXPIRED interval -> REVOKE/SUPERSEDE only; REVOKED/SUPERSEDED ->
    nothing); application/lifecycle.py RecordStatusAction (API-071: supervisor of the
    jurisdiction + `certificate.status` grant; effective_at between issue and now; SUSPEND/REVOKE
    cite a CLEAN case document; SUPERSEDE names an in-force ACTIVE certificate of the same
    premises without predecessor and links it; 409 CERTIFICATE_STATUS_CONFLICT when not
    admissible; PUBLIC_CASE certificate.status_changed.v1; audit with the grant) and
    CreateRenewalDraft (API-070: holder/operator, not for REVOKED/SUPERSEDED, one open renewal
    per certificate, new DRAFT for the same premises with `prior_certificate_id`, RENEWAL type
    and the number in the draft fields; the source certificate is not touched); registry detail
    now carries status_history (reasons for staff only), renewals and the holder-side renewal
    action; API-068 adds allowed_status_actions per reader; API-072 external registration and
    API-119 declarations are profile-gated routes answering 409 SERVICE_DISABLED.
  support (NEW app, migration 0001): SupportTicket (requester, optional readable case, category,
    subject, description, OPEN/IN_PROGRESS/WAITING_FOR_REQUESTER/RESOLVED/CLOSED, owner queue =
    the case's queue or SUPPORT_DEFAULT_QUEUE_KEY, priority), SupportMessage (append-only;
    REQUESTER/INTERNAL audience; MESSAGE/STATUS kind; cited CLEAN files as a JSON id list -
    deviation from the "document_refs through table" of docs/05, recorded); commands CreateTicket
    (API-113), AddTicketMessage (API-115: requesters write REQUESTER only; staff notes INTERNAL;
    state nudges OPEN->IN_PROGRESS on a staff reply and WAITING->IN_PROGRESS on a requester
    reply; closed tickets need a reopen), ChangeTicketStatus (API-116: staff machine; requester
    may only reopen RESOLVED/CLOSED -> IN_PROGRESS; every change is a STATUS entry); scope =
    requester, ADMIN (global) or SUPERVISOR of the owner queue's jurisdiction; views API-112/114
    (audience-filtered), /support/routes (profile flags + referral), API-117/118 appeals -> 409
    SERVICE_DISABLED with the approved referral text - no appeal row is ever created.
  documents: SUPPORT_ATTACHMENT upload target for requesters and support agents of an open
    ticket (`support-<label>` codes, per-ticket quota, DocumentVersion.application follows the
    ticket's case or stays NULL); visible_documents includes attachments of tickets the reader
    may see (FR-30 "attachment scope inherits ticket readership").
  notifications: templates application.withdrawn.v1, certificate.status_changed.v1,
    inspection.clarification_requested.v1 (+ context keys action / attempt_number); seed grants
    anita `certificate.status`; settings SUPPORT_DEFAULT_QUEUE_KEY (test: demo-central-review).
  web: api/support.ts, api/lifecycle.ts, certificates.ts (status actions, renewal, history and
    renewal types), CaseDetail typings (on_hold, holds, prior_certificate_id, closed_at);
    features/lifecycle/CaseLifecycleActions (UI-07: applicant withdrawal with a reasoned
    confirmation, supervisor hold form listing the ACTIVE clocks and the blocked scope, active
    hold cards with release, return-for-clarification form) mounted on the case page; UI-26
    SupportPage (routes card with the appeal referral, new-ticket form with optional case link,
    ticket list) and SupportTicketPage (audience-filtered conversation, reply with a scanned
    attachment, staff-only internal-note toggle, permitted status buttons, requester reopen);
    UI-17 CertificateDetailPage rewritten with status history, renewals, holder renewal button
    (navigates to the new draft) and the authority's status dialog offering only the enabled
    actions with evidence selection; nav "Support" for signed-in users.
  Decisions: (1) no dedicated `case.hold` / `ticket.*` capabilities exist in the identity model
    - holds require the SUPERVISOR role of the case jurisdiction (an administrative act), support
    scope is ADMIN (global) or SUPERVISOR of the owner queue's jurisdiction; recorded as a gap
    for docs/07 review; (2) hold pauses reuse the B10 pause table with the only pause reason the
    demo profile permits; a COURT_ORDER hold is distinguished on the hold record, not by a new
    pause reason (the profile would refuse it); (3) command_block_scope semantics: TRANSITIONS
    blocks every application transition incl. publication, DECISIONS blocks TR-10/TR-12 only,
    an empty list pauses clocks without blocking; (4) an IN_PROGRESS attempt is not cancelled by
    a withdrawal (the attempt machine has no IN_PROGRESS -> CANCELLED edge); REQUESTED/SCHEDULED
    attempts are; (5) staff cannot withdraw on the applicant's behalf (not specified; refused
    with 403); (6) expired records: REINSTATE and SUSPEND are inadmissible, REVOKE/SUPERSEDE
    stay possible; reinstatement only for a still-in-force suspension (workflow s.5 invariant);
    (7) renewal eligibility = recorded ACTIVE or SUSPENDED (incl. an expired interval), never
    REVOKED/SUPERSEDED, one open renewal per certificate; (8) appeals, declarations, external
    registration and fees are disabled by the demo profile and answer with the referral - no
    model rows, no "filed" wording anywhere; (9) support attachments cited in messages are a
    JSON id list rather than a through table (simplicity; readership still follows the ticket).
Migrations/data impact: cases 0005 (case_hold), certificates 0003 (status instrument), support
  0001 (2 tables). No data rewrite. No new Compose service.
Tests actually executed (Windows host, 2026-09-12):
  uv run --directory backend ruff format / ruff check agni tests / mypy agni tests -> clean
    (275 files); manage.py check -> no issues; makemigrations --check --dry-run -> "No changes
    detected"
  uv run --directory backend pytest tests/unit/test_certificate_lifecycle_rules.py
    tests/integration/test_lifecycle.py -q -> after three test-side fixes (earlier SATISFIED
    obligations are not CANCELLED by a withdrawal; a hold bumps the case version so the officer
    re-reads the attempt; a two-hour clock jump expires the test session - 20 minutes used)
    -> 12 passed: AT-30-01 withdrawal (403 staff / 404 stranger / 422 no reason / 200 WITHDRAWN
    with obligations CANCELLED, attempt CANCELLED, assignment REVOKED, public + internal events,
    second withdrawal and a hold on the closed case refused); holds (court order without basis
    422; administrative hold pauses only the listed clock, report submission 409 with hold_id,
    second hold 409, applicant sees on_hold without records, staff actions ON_HOLD/HOLD_ACTIVE,
    stale release 412, release recomputes due_at = original + pause, report then accepted;
    withdrawal refused in REVIEW_PENDING per profile; TR-14 false -> 409 SERVICE_DISABLED,
    unknown item 422, then CLARIFICATION attempt 2 with obligations moved); AT-24 (no grant ->
    AUTHORITY_MISSING; with grant SUSPEND needs evidence 422, plain supervisor 403, SUSPEND 201 ->
    public SUSPENDED, holder history without reasons, stale 412, REINSTATE 201; renewal 403 for
    staff, 201 linked DRAFT with RENEWAL fields and untouched valid_until, second renewal 409;
    +366 days: SUSPEND/REINSTATE inadmissible 409 CERTIFICATE_STATUS_CONFLICT, REVOKE 201 ->
    public REVOKED, history SUSPEND/REINSTATE/REVOKE, reinstatement and renewal of a revoked
    record 409); AT-30 support (routes + appeal 409 with referral, out-of-scope case 422, ticket
    201 on the case queue, stranger sees nothing, staff list/scope, INTERNAL note hidden from
    the requester, requester INTERNAL 403, SUPPORT_ATTACHMENT upload + scan + cited in a reply,
    staff opens it through API-036 and a stranger cannot, staff reply -> IN_PROGRESS, waiting,
    requester reply resumes, requester resolve 403, resolve, requester reopen, resolve, close,
    reply after close 409, case status/version untouched, no-case ticket on the support desk
    queue) (evidence/B13-targeted-tests.log)
  corepack pnpm --dir web typecheck / lint / test --run / build -> clean, **39 passed (19
    files)** incl. SupportTicketPage.test (requester view hides internal controls; reply carries
    the ticket ETag) and CaseLifecycleActions.test (reason + confirmation before the withdraw
    command with If-Match), built (evidence/B13-web-tests.log, B13-web-build.log)
  uv run --directory backend pytest -q (full suite, ALONE, 20:03-20:10Z) -> **210 passed in
    362.43 s**; 0 PostgreSQL termination / recovery lines in that window
    (evidence/B13-backend-tests.log)
  Container proof: docker compose build api web -> api 21919bddf49d (20:11:24Z), web
    328f02f12da7 (20:13:03Z); up -d --wait api worker scheduler web -> all healthy; running
    containers verified against those ids; showmigrations -> cases 0005, certificates 0003,
    support 0001 applied on start; seed_demo re-run (idempotent) so anita holds
    `certificate.status`
  uv run --directory backend python ../scripts/dev/smoke_lifecycle.py http://127.0.0.1:5173 ->
    ALL LIFECYCLE SMOKE STEPS PASSED (**29 steps** through nginx + Keycloak + demo OTP, 20:16Z:
    allowed status actions per grant; SUSPEND without evidence 422; SUSPEND with a CLEAN case
    document 201 -> public verification SUSPENDED; REINSTATE 201 -> history SUSPEND/REINSTATE;
    holder renewal step honestly marked NOT_RUN because the smoke applicant is not the holder of
    AGNI-DEMO-2026-101 (covered by the integration test); administrative hold on an open case
    pauses 2 obligations and disables transition actions with ON_HOLD; release resumes them;
    appeals route 409 SERVICE_DISABLED with the referral; ticket 201; supervisor support scope;
    INTERNAL note hidden from the requester; staff reply -> IN_PROGRESS; RESOLVED; requester
    reopen; requester resolve 403) (evidence/B13-smoke-lifecycle.log)
  Dependency audits: no new dependencies in B13 (pip-audit / pnpm audit last run clean at B12).
Tests not executed and concrete reason: AT-24-06 / AT-30-06 browser + accessibility variants
  (Playwright, B16/B19); AT-24-05 / AT-30-05 threaded races (kernel fence + unique constraints
  exercised by replay/412 paths; drills are B17); SUPERSEDE end-to-end (needs a second ACTIVE
  certificate of the same premises - covered by the admissibility unit test and validation
  paths only); UI-15 hold controls live on the case page (UI-07) rather than on the monitoring
  tabs (documented deviation; the monitoring "Paused" tab shows paused clocks from B10).
Screens inspected: jsdom tests of UI-26 ticket page and UI-07 withdrawal block; SupportPage,
  hold/return forms and the UI-17 status dialog by typecheck + build only (NOTE for B16/B19).
Security/privacy or external-effect considerations: INTERNAL support notes never reach the
  requester; ticket attachments are readable only through ticket scope; holds and status
  instruments require jurisdiction roles (and the `certificate.status` grant) and are audited
  with reasons; withdrawal is the applicant's own action; appeals/fees/declarations/external
  registration stay disabled with the approved referral wording; no support command can touch
  a case, a certificate, a decision or a grant.
Remaining defects and reproduction: NONE known in the product.
Self-review (D-009): diff reviewed against task card B13 proofs - a terminal case cannot be
  reopened through support (support commands never mutate cases; tested), a renewal does not
  extend the source validity (tested), an expired record is not reinstated (tested), the hold
  clock impact is the listed obligations only and release adds exactly the pause length
  (tested); forbidden shortcut respected: conditional legal flows are not enabled and no fake
  appeal filing exists.
Required human input: docs/07 capability model for holds and support scope (see decision 1);
  BL-007; agency-approved appeal / fee / external-registration profiles before any of those
  routes can be enabled.
Next safe task: B14 - Reporting, audit and operational UI.
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
