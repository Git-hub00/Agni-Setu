# Codex and Claude Code implementation task cards

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## Operating rule

Execute tasks in dependency order. A task is not complete merely because files were generated. Each card is a vertical implementation contract with evidence. The default is one task at a time; safe parallel work requires isolated worktrees and stable shared contracts. Keep the shared schema, identity and migrations under one owner.

For each task, read the relevant FR sections, transition rules, API entries, field schemas, screen details and tests. Use [traceability](15_REQUIREMENTS_TRACEABILITY.md) to locate them. Read AGENTS.md at the start of each resumed session. Do not copy all documents into every prompt.

## B00 - Baseline and dependency lock

**Dependencies:** None. **Target:** Inspect repository, preserve user work, approve stack ADRs, record exact package/image versions and local environment.

**Implement:** Read all index/ADR/source/status summaries; inspect current Git work and compare any existing stack. Record source hashes and exact dependency candidates.

**Expected areas:** `docs/DEPENDENCY_LOCK.md, docs/21_IMPLEMENTATION_STATUS.md, infra/images.lock.json, accepted ADR notes.`

**Proof required:** A compatibility install and hello-world Django/React build; no business implementation claimed.

**Forbidden shortcut / stop condition:** No confirmed target repo or conflicting existing architecture: record the issue and seek the specific owner decision, not arbitrary replacement.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B01 - Repository and runnable skeleton

**Dependencies:** B00. **Target:** Create Django/React workspaces, Compose infrastructure, health probes and reproducible task commands.

**Implement:** Create runnable folders, config separation, local infrastructure, scripts, health endpoints and empty accessible application shell.

**Expected areas:** `backend/config, web/src/app, infra/compose, scripts/dev, .github/workflows.`

**Proof required:** Fresh checkout can install frozen locks and start healthy services; bad production config fails; root route and API health tested.

**Forbidden shortcut / stop condition:** Do not add fake full-product pages or commit secrets to make boot easier.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B02 - Domain persistence and command kernel

**Dependencies:** B01. **Target:** Create foundational migrations, authorization fences, command receipts, audit, outbox and deterministic clock tests.

**Implement:** Implement custom principal before migrations, foundational entities, typed errors, command receipt, lock ordering, audit/outbox and injected clock.

**Expected areas:** `backend/agni/platform, identity initial models, cases initial models, tests/integration and properties.`

**Proof required:** Rollback leaves no receipt/outbox; duplicate command has one result; stale version rejected; critical audit failure aborts mutation.

**Forbidden shortcut / stop condition:** Do not use SQLite to claim PostgreSQL concurrency proof or on_commit-only messaging.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B03 - Identity, sessions and scoped permissions

**Dependencies:** B02. **Target:** Implement applicant OTP, staff OIDC, approved grants, anti-abuse, CSRF and cross-user access tests.

**Implement:** Implement OTP/provider sink, OIDC, session rotation, CSRF, scope selectors, grants and revocation; expose actual sign-in/account shell.

**Expected areas:** `identity API/services/adapters, web/features/identity, security tests, local identity configuration.`

**Proof required:** Anonymous/cross-scope/inactive/grant-expired denied; login CSRF tested; repeated OTP fails; OIDC subject mapping and logout proven.

**Forbidden shortcut / stop condition:** No public privileged signup, role payload trust or fixed live OTP.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B04 - Service policy and master data

**Dependencies:** B03. **Target:** Build immutable policy packages, independent approval, applicability, routing versions and premises delegation.

**Implement:** Implement service/artifact schemas, independent policy review, interval validation, activation fence, premises and delegation.

**Expected areas:** `policies, routing mappings, cases premises, UI-03/04/24.`

**Proof required:** Self-approval blocked; policy activation races submission deterministically; overlapping policy rejected; delegation revocation denied.

**Forbidden shortcut / stop condition:** Live policy remains disabled without approved evidence; demo uses explicitly synthetic package.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B05 - Drafts, files and application wizard

**Dependencies:** B04. **Target:** Build real server drafts, versioned documents, quarantined uploads, scan jobs and accessible wizard.

**Implement:** Implement versioned draft wizard, file reservations, private storage, scan worker and clean evidence links.

**Expected areas:** `documents, cases drafts, web/features/cases/forms, UI-06.`

**Proof required:** Missing/oversized/malicious/wrong-case/still-scanning files blocked; stale autosave conflict; reload preserves saved draft.

**Forbidden shortcut / stop condition:** Do not map scanner outage to CLEAN or turn draft creation into submission.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B06 - Submission, routing and case visibility

**Dependencies:** B05. **Target:** Commit atomic submission and receipt, route exceptions, case lists and audience-filtered timeline.

**Implement:** Implement atomic explicit submission, receipt, policy pinning, queue ownership, route exceptions and scoped timeline.

**Expected areas:** `cases submission/services/selectors, routing exceptions, UI-05/07/09.`

**Proof required:** Repeated submit returns same receipt; DB failure no accepted receipt; no-match route is visible; applicant cannot see internal notes.

**Forbidden shortcut / stop condition:** No receipt before validated commit; no unowned open cases.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B07 - Assignment and appointment management

**Dependencies:** B06. **Target:** Create inspection attempts, availability checks, conflict-safe booking, cancellation and failed-visit flows.

**Implement:** Implement attempts/assignments, appointment interval constraints, availability fences, calendar UI and failed-visit handling.

**Expected areas:** `inspections models/services, UI-10/11/12 initial.`

**Proof required:** Two concurrent bookings cannot overlap; inactive officer denied; failed attempt preserved; reassign does not reset case clock.

**Forbidden shortcut / stop condition:** No unchecked calendar-only conflict handling or completed attempt edits.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B08 - Inspection reports and checklist evaluation

**Dependencies:** B07. **Target:** Implement observations, evidence, immutable report revisions and deterministic mandatory blockers.

**Implement:** Implement checklist schema/evaluator, report drafts, immutable accepted report and evidence provenance.

**Expected areas:** `inspections/domain and application, UI-12, report contract tests.`

**Proof required:** Mandatory FAIL/NOT_VERIFIED/invalid NA blocks readiness; wrong-case evidence denied; duplicate submit creates one report.

**Forbidden shortcut / stop condition:** No numeric score can override mandatory blockers; no applicant-controlled report author.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B09 - Notices, responses and correction cycles

**Dependencies:** B08. **Target:** Build itemized information and deficiencies, response versions, verification and reinspection.

**Implement:** Implement information/deficiency rounds, per-item response versions, return/verify workflows and reinspection.

**Expected areas:** `notices, findings review, UI-08/14.`

**Proof required:** Response alone does not close finding; accepting incomplete info round blocked; correction loop returns to right state.

**Forbidden shortcut / stop condition:** Do not reuse appeal terminology for missing-document response or mutate published notices.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B10 - Clocks, outbox dispatch and notifications

**Dependencies:** B09. **Target:** Deliver persistent obligation calculations, unique escalation actions, retry-safe jobs and delivery tracking.

**Implement:** Implement interval clock domain, persistent due scans, threshold uniqueness, outbox delivery, notification attempts and operations skeleton.

**Expected areas:** `obligations, notifications, platform job services, run_schedulers, UI-15/19/20.`

**Proof required:** Overlapping pauses union; weekend/holiday boundaries; two schedulers one escalation; broker failure recovers; delivery failure does not reject case.

**Forbidden shortcut / stop condition:** Do not represent long deadlines only in Celery ETA or permit blind irreversible retry.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B11 - Offline field application

**Dependencies:** B10. **Target:** Installable PWA, minimum local packages, explicit synchronization and version/authority conflict workflows.

**Implement:** Implement IndexedDB schemas, static-shell PWA, package retrieval, local file/operation queue and reviewed conflicts.

**Expected areas:** `web/offline, sync API/services, UI-13, browser device tests.`

**Proof required:** Offline/reconnect accepted once; stale assignment and revoked authority blocked; local migration preserves drafts; explicit sync works without Background Sync.

**Forbidden shortcut / stop condition:** Do not silently set new base_version, clear failed IndexedDB stores or claim remote wipe.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B12 - Decisions, issuance and verification

**Dependencies:** B11. **Target:** Implement guarded decisions, durable sample issuance, registry, status-safe verification and signer adapter boundary.

**Implement:** Implement readiness guard, authority-fenced decision, durable sample rendering/issuance, registry and public verification.

**Expected areas:** `decisions, certificates, signer ports/simulator, UI-14/16/17/18.`

**Proof required:** One favorable decision/instrument; unknown signer reconciles; approval not completed before publication; stale/outage verification never active.

**Forbidden shortcut / stop condition:** No forged official signature, certificate number reallocation on retry or admin completion override.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B13 - Lifecycle, support and conditional routes

**Dependencies:** B12. **Target:** Build renewal and status instruments, support, withdrawal, hold controls and disabled/referral appeal pathways.

**Implement:** Implement allowed withdrawal, renewal linkage, status instruments, holds, support and disabled/referral conditional appeals/declarations.

**Expected areas:** `support, certificates lifecycle, case holds, UI-26.`

**Proof required:** Terminal case cannot reopen through support; renewal does not extend source validity; expired record not reinstated; hold clock impact correct.

**Forbidden shortcut / stop condition:** Enable conditional legal flows only with full approved profile; no fake filed appeal.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B14 - Reporting, audit and operational UI

**Dependencies:** B13. **Target:** Build reconciled metrics, scoped exports, read auditing, job recovery and responsive role workspaces.

**Implement:** Implement scoped metric selectors, report definitions, controlled exports, audit reader and full operational/staff UI.

**Expected areas:** `reporting, audit, operations UI, UI-21/22/23/27.`

**Proof required:** Seed totals reconcile; failed query != zero; CSV formula protection; export scope rechecked; unrelated audit payload hidden.

**Forbidden shortcut / stop condition:** Do not use mock dashboard totals in the server-backed app.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B15 - Integration contracts and reconciliation

**Dependencies:** B14. **Target:** Implement local simulators, signed partner inbox, ownership rules, ordered processing and controlled reconciliation.

**Implement:** Implement provider test contracts, authenticated partner inbox, source ownership/ordering and reconciliation.

**Expected areas:** `integrations ports/adapters/models, UI-25, contracts/events.`

**Proof required:** Duplicate event no duplicate effect; different body same ID conflicts; older source status cannot overwrite newer; unauth callback rejected.

**Forbidden shortcut / stop condition:** Do not claim actual government integration when only simulator was tested.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B16 - Security and accessibility hardening

**Dependencies:** B15. **Target:** Validate threat scenarios, accessible journeys, browser matrix, uploads, identity revocation and secrets scans.

**Implement:** Run security boundary matrix, accessibility and responsive routes, dangerous-file/resource-limit checks and secret/config scans.

**Expected areas:** `tests/security, tests/e2e/accessibility, relevant UI fixes and hardening config.`

**Proof required:** Critical/high issues resolved; keyboard and mobile core tasks complete; no token/PII leaks; full authorization matrix tested.

**Forbidden shortcut / stop condition:** Do not disable checks or suppress failures to produce a green report.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B17 - Reliability, performance and recovery proof

**Dependencies:** B16. **Target:** Run concurrency/fault/load suites, object/database recovery drill and measurement reports.

**Implement:** Execute deterministic concurrent commands, fault injection, workload measurements and isolated DB/object restore.

**Expected areas:** `tests/load, tests/integration/faults, scripts/ops, evidence.`

**Proof required:** Measured p95 and resource usage; invariant preservation after crashes; restore verifies object hashes and accepted records.

**Forbidden shortcut / stop condition:** Do not substitute a mocked unit test for physical restart or restore evidence.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B18 - Production packaging and release evidence

**Dependencies:** B17. **Target:** Create hardened images, CI/CD approvals, upgrade/rollback runbooks, SBOM and release evidence.

**Implement:** Build hardened release images, approval-gated pipelines, rollback playbook, dependency inventory/SBOM and operational dashboards.

**Expected areas:** `infra/containers/production, .github/workflows, scripts/ops, release manifests.`

**Proof required:** Production checks fail unsafe settings; migration compatibility tested; image scans and backup rehearsal attached.

**Forbidden shortcut / stop condition:** No development servers, sample keys, debug endpoints or public infrastructure consoles in live packaging.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B19 - Full demonstration acceptance

**Dependencies:** B18. **Target:** Validate all role journeys and mapped prototype controls with deterministic fixtures; fix and retest defects.

**Implement:** Walk every role through happy and failed scenarios with exact synthetic dataset; compare implemented screens and prototype action inventory.

**Expected areas:** `tests/e2e, docs/23_PROTOTYPE_COVERAGE.md implementation evidence, demo release notes.`

**Proof required:** All180 core scenario assertions and additional concurrency/security suites accounted for; every enabled route/button functional.

**Forbidden shortcut / stop condition:** A test blocked by missing external credentials is labelled BLOCKED, not PASS.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.

## B20 - Agency pilot activation

**Dependencies:** B19. **Target:** Complete legal/policy/integration/security/operations approvals before any official live case or certificate.

**Implement:** Collect agency decisions and live provider evidence, validate enabled profile, onboard operators and approve controlled pilot population.

**Expected areas:** `approved policy/gate evidence, release approval, operator roster and monitoring.`

**Proof required:** All applicable LIVE gates approved and non-demo UAT signed; rollback/on-call ready.

**Forbidden shortcut / stop condition:** No live cases or official certificates before approval, regardless of demo completeness.

**Handoff:** list exact files changed, migration effects, commands actually run, passed/failed/blocked checks, screenshots where relevant, outstanding risk and the next eligible task. Update [implementation status](21_IMPLEMENTATION_STATUS.md). Restart affected API/worker/scheduler processes before reporting observed behavior.


## Task prompt template

```text
Implement task Bxx from docs/17_AGENT_TASK_CARDS.md in this repository.
Read AGENTS.md, the implementation status, and only the linked specification
sections needed for this task. Inspect existing code before editing.
Use the selected stack and preserve the canonical states, permissions and APIs.
Implement real server-backed behavior, validation, failure recovery and tests.
Do not weaken safety controls or replace missing integrations with hidden mocks.
Run the task's verification commands, restart affected processes, and record
actual evidence. Report blocked tests honestly. Update status and stop after
this task's acceptance gate, with a precise next-step handoff.
```

## Multi-agent handoff format

Record task ID, source commit, owned files, schema/contract versions, tests executed, current branch/worktree, known conflicts and next action. Codex and Claude must not both modify the same migration or contract without coordination. The reviewer checks behavior and evidence against this pack, not just the implementation author's summary.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
