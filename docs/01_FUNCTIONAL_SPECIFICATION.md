# Functional specification

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. How to implement this specification

The original thirty requirement IDs are retained. Each requirement below is a minimum behavior contract, not just a screen description. The detailed transitions are in [workflow and policy](02_WORKFLOW_AND_POLICY_SPECIFICATION.md); input fields are in [forms and validation](24_FORM_SCHEMAS_AND_VALIDATION.md); the UI and API documents determine interaction and wire format. Read all four before coding a feature.

`MUST` and `shall` are normative for enabled capabilities. `DEMO ONLY` must never reach live behavior. `PROFILE DEPENDENT` becomes required when the selected live service needs that capability. Database values, timestamps and authority are server-owned unless a field is explicitly editable.

## 2. Common command behavior

Every mutation has one visible initiating action, validation, a pending state, a canonical success result, and an error with the next safe user action. Disable repeated clicking while pending but also enforce server idempotency. A timeout is an unknown outcome until the receipt is checked or the same idempotency key is replayed. Do not tell users to create a new application to solve a timeout.

Sensitive commands show a confirmation summary of the case, action, reason and impact. Success is shown only after server acceptance. Asynchronous work shows `Accepted - processing`, its job identifier and status link, not `Completed`. Refresh and direct URL navigation must reconstruct the screen from the server.

All permissions are checked server-side. The `allowed_actions` returned with a record is a UI hint derived from current authority; it is not a substitute for revalidation when an action arrives. Disabled actions include a human-readable blocker where disclosure is safe. Truly irrelevant actions are hidden.

## 3. Functional requirements

### FR-01 - Applicant identity and account recovery

**Actor:** Applicant. **Module:** `identity`. **Build task:** B03. **Screens:** UI-02, UI-03.

**Required behavior.** Authenticate a verified contact, create or link an applicant profile, rotate the server session, and separate identity verification from proof of authority over a premises.

**Successful path.** A valid one-time challenge creates one authenticated session and opens only that applicant profile.

**Unsuccessful path.** An expired, reused, throttled or incorrect challenge never grants a session; an enumeration-safe response does not reveal account existence.

**Recovery.** Allow resend after the configured cooldown; invalidate superseded challenges. Account-contact replacement requires verified recovery, never an administrator silently changing the owner.

**Acceptance evidence.** Implement the corresponding six `AT-01-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-02 - Staff provisioning and account lifecycle

**Actor:** Operations administrator. **Module:** `identity`. **Build task:** B03. **Screens:** UI-21.

**Required behavior.** Provision staff only from an approved access request. Bind staff to the OIDC issuer and subject; roles and effective-dated grants come from controlled server records.

**Successful path.** An approved invitation links the intended staff subject and exposes only approved workspaces.

**Unsuccessful path.** Public registration cannot request a privileged role; disabled or expired grants are rejected even with an existing session.

**Recovery.** Revoke sessions and increment the authorization epoch; pending assignments move to a visible duty queue without deleting past work.

**Acceptance evidence.** Implement the corresponding six `AT-02-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-03 - Service applicability and premises

**Actor:** Applicant / reviewer. **Module:** `policies`. **Build task:** B04. **Screens:** UI-04, UI-06.

**Required behavior.** Select an enabled service and versioned applicability rules from declared premises characteristics. Preserve the explanation and source version.

**Successful path.** A supported category displays the exact applicable form and document list.

**Unsuccessful path.** Unknown category, overlapping policy or unsupported jurisdiction does not fabricate eligibility.

**Recovery.** Keep the draft; explain unsupported service or route a clarification request to a named queue. Do not accept a live submission without an approved profile.

**Acceptance evidence.** Implement the corresponding six `AT-03-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-04 - Draft creation and editing

**Actor:** Applicant / representative. **Module:** `cases`. **Build task:** B05. **Screens:** UI-05, UI-06.

**Required behavior.** Create DRAFT before submission. Validate each step; autosave only editable draft fields with a version precondition. A draft has no official receipt or processing clock.

**Successful path.** The user returns to the saved draft and sees preserved fields and file status.

**Unsuccessful path.** A second-tab stale save returns a version conflict rather than overwriting newer values.

**Recovery.** Show the field differences and let the user reapply allowed edits to a current version. Retry an ambiguous save with its original key.

**Acceptance evidence.** Implement the corresponding six `AT-04-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-05 - Document and evidence intake

**Actor:** Permitted uploader. **Module:** `documents`. **Build task:** B05. **Screens:** UI-06, UI-08, UI-12.

**Required behavior.** Use private upload reservations, immutable object identifiers, size/type validation, checksums and malware scanning. Only accepted clean versions may support submission or decisions.

**Successful path.** A valid uploaded file becomes CLEAN with a new immutable document version.

**Unsuccessful path.** A malicious, unsupported, oversized, truncated or still-scanning file cannot satisfy a required evidence item.

**Recovery.** Keep safe draft data and a human-readable upload status; retry a new reservation for a failed upload. Scanner outage leaves QUARANTINED, not CLEAN.

**Acceptance evidence.** Implement the corresponding six `AT-05-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-06 - Atomic application submission

**Actor:** Applicant / representative. **Module:** `cases`. **Build task:** B06. **Screens:** UI-06, UI-07.

**Required behavior.** Validate the full current revision, declarations, accepted files and active profile; atomically freeze the submission, pin policy, allocate receipt, event and obligations.

**Successful path.** One accepted command returns one receipt and SUBMITTED with accountable scrutiny ownership.

**Unsuccessful path.** Missing documents or unapproved profile rejects the command without a receipt or partial stage transition.

**Recovery.** Same key and same payload returns the original accepted result after authorization; changed payload with the same key is rejected.

**Acceptance evidence.** Implement the corresponding six `AT-06-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-07 - Jurisdiction routing and exceptions

**Actor:** System / supervisor. **Module:** `routing`. **Build task:** B06. **Screens:** UI-09, UI-15.

**Required behavior.** Route using an approved effective-dated map and service scope; preserve mapping version and rationale. A missing or multiple match creates a visible owned exception.

**Successful path.** Exactly one applicable mapping selects the expected scrutiny queue.

**Unsuccessful path.** No match does not randomly select an officer, drop the case, or suspend the case-wide clock.

**Recovery.** Supervisor resolves the exception with a valid mapping or authorized referral; keep old routing events and notify permitted participants.

**Acceptance evidence.** Implement the corresponding six `AT-07-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-08 - Assignment and reassignment

**Actor:** Supervisor. **Module:** `inspections`. **Build task:** B07. **Screens:** UI-10, UI-11, UI-21.

**Required behavior.** Assign eligible active officers within jurisdiction, availability and conflict rules. Preserve assignment versions and reasons. One active assignment exists per inspection attempt.

**Successful path.** An eligible officer receives the appointment in the task queue.

**Unsuccessful path.** Concurrent overlapping bookings or assignment to an inactive/out-of-scope officer fails atomically.

**Recovery.** Display available alternatives; reassign through a new version and revoke stale offline authority without deleting earlier evidence.

**Acceptance evidence.** Implement the corresponding six `AT-08-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-09 - Case visibility and timeline

**Actor:** Scoped reader. **Module:** `cases`. **Build task:** B06. **Screens:** UI-05, UI-07, UI-09.

**Required behavior.** Show the authoritative case status, next action, responsible unit, due basis, submitted revisions and audience-filtered chronological events.

**Successful path.** Applicant sees a published information request and own receipt; supervisor sees permitted internal review context.

**Unsuccessful path.** Cross-applicant IDs, internal notes and unauthorized evidence remain inaccessible, including direct URLs and exports.

**Recovery.** A failed refresh keeps previous data visibly stale with timestamp and retry; never invent progress.

**Acceptance evidence.** Implement the corresponding six `AT-09-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-10 - Assisted intake and delegation

**Actor:** Applicant / representative. **Module:** `identity`. **Build task:** B04. **Screens:** UI-03, UI-04, UI-06.

**Required behavior.** Capture beneficiary, acting operator, delegation scope, evidence, consent record where applicable, expiry and revocation. Contacts do not create ownership.

**Successful path.** A valid representative submits for the named beneficiary and both identities are recorded.

**Unsuccessful path.** An expired or unrelated delegation cannot view, edit or submit that beneficiary case.

**Recovery.** The beneficiary may revoke or approve a new delegation through the controlled flow; history remains attributable.

**Acceptance evidence.** Implement the corresponding six `AT-10-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-11 - Appointments and visit outcomes

**Actor:** Supervisor / officer. **Module:** `inspections`. **Build task:** B07. **Screens:** UI-10, UI-11, UI-12.

**Required behavior.** Record appointments, schedule changes, visit start, cancelled and failed attempts with reason codes. A failed visit creates a next-action task, not a favorable report.

**Successful path.** An agreed time slot appears in both the officer queue and applicant timeline.

**Unsuccessful path.** An inaccessible site or no-show does not complete an inspection or silently reset elapsed time.

**Recovery.** Create a new attempt or reschedule an unstarted attempt under policy; preserve the failure record and unresolved case obligations.

**Acceptance evidence.** Implement the corresponding six `AT-11-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-12 - Offline drafts and explicit synchronization

**Actor:** Assigned officer. **Module:** `offline`. **Build task:** B11. **Screens:** UI-12, UI-13.

**Required behavior.** Download a minimum scoped assignment package; store bounded local drafts; distinguish local saving, uploads and server acceptance. Provide explicit foreground synchronization.

**Successful path.** An offline draft synchronizes once after reauthentication and current-authority checks.

**Unsuccessful path.** Browser eviction, revoked assignment or unavailable storage must not be represented as server-accepted evidence.

**Recovery.** Warn about unsynchronized work; handle storage errors visibly. Retain a locked local conflict package only under approved recovery rules.

**Acceptance evidence.** Implement the corresponding six `AT-12-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-13 - Versioned inspection report and provenance

**Actor:** Assigned officer. **Module:** `inspections`. **Build task:** B08. **Screens:** UI-12, UI-14.

**Required behavior.** Accept a report only with current assignment, checklist version, complete observations and accepted evidence. Submitted reports are immutable revisions.

**Successful path.** A submitted report binds actor, server time, client capture time and object hashes and enters REVIEW_PENDING.

**Unsuccessful path.** A stale report or changed evidence reference cannot replace a newer accepted report.

**Recovery.** Return structured conflicts; corrections create an attributed addendum or replacement revision through authorized review, not a raw update.

**Acceptance evidence.** Implement the corresponding six `AT-13-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-14 - Deterministic checklist evaluation

**Actor:** Officer / decision authority. **Module:** `inspections`. **Build task:** B08. **Screens:** UI-12, UI-14.

**Required behavior.** Use PASS, FAIL, NOT_VERIFIED and policy-permitted NOT_APPLICABLE. Mandatory failures and unverified items block a favorable decision; each NA requires rationale.

**Successful path.** Complete compliant evidence creates an eligible-for-review result, not an automatic approval.

**Unsuccessful path.** A high numeric score cannot compensate for one mandatory FAIL or unauthorized NA.

**Recovery.** Create itemized findings; require verified closure and any necessary reinspection before reevaluation.

**Acceptance evidence.** Implement the corresponding six `AT-14-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-15 - Information requests and deficiency notices

**Actor:** Reviewer / supervisor. **Module:** `notices`. **Build task:** B09. **Screens:** UI-08, UI-14.

**Required behavior.** Publish versioned itemized notices, accepted response evidence types, reasons, owner and deadline. Information requests concern completeness; deficiencies concern findings.

**Successful path.** Applicant receives one notice with actionable items and response controls.

**Unsuccessful path.** Empty reasons, contradictory items or duplicate publication using the same logical command are rejected or replayed.

**Recovery.** Correct through a superseding notice with a clear relationship; retain the original and clock disposition.

**Acceptance evidence.** Implement the corresponding six `AT-15-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-16 - Applicant response versions

**Actor:** Applicant / representative. **Module:** `notices`. **Build task:** B09. **Screens:** UI-08.

**Required behavior.** Attach a response to each requested item using accepted file versions and explanation. Responses never delete earlier submissions or automatically close findings.

**Successful path.** A complete response moves its item to RESPONSE_RECEIVED and notifies the review queue.

**Unsuccessful path.** Unrelated or quarantined evidence and attempts to edit a closed notice are rejected.

**Recovery.** Allow a new permitted response revision or request reopening of the item through review; display what is still missing.

**Acceptance evidence.** Implement the corresponding six `AT-16-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-17 - Verification, return and reinspection

**Actor:** Reviewer / supervisor. **Module:** `notices`. **Build task:** B09. **Screens:** UI-08, UI-14.

**Required behavior.** Verify each response against its finding. Record evidence, reviewer, result and whether physical reinspection is required. Only authorized review closes a finding.

**Successful path.** All mandatory findings verified closed return the case to review.

**Unsuccessful path.** A document upload or applicant checkbox alone cannot close a mandatory safety finding.

**Recovery.** Return specific unresolved items or create a new inspection attempt; retain the deficiency cycle and its original timing history.

**Acceptance evidence.** Implement the corresponding six `AT-17-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-18 - Persistent stage and case clocks

**Actor:** System / supervisor. **Module:** `obligations`. **Build task:** B10. **Screens:** UI-15.

**Required behavior.** Persist case-wide and per-stage obligations, time basis, pinned calendar, budget, responsible queue, pauses and satisfaction events.

**Successful path.** A four-working-hour internal obligation started at 09:00 is due 13:00; a permitted one-hour pause moves it to 14:00.

**Unsuccessful path.** Overlapping pauses must not double-subtract; reassignment, downtime and failed notifications do not automatically pause clocks.

**Recovery.** Recompute from immutable events and approved calendar; show an auditable correction instead of editing timestamps silently.

**Acceptance evidence.** Implement the corresponding six `AT-18-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-19 - Reminders and accountable escalation

**Actor:** System / supervisor. **Module:** `obligations`. **Build task:** B10. **Screens:** UI-15, UI-19, UI-20.

**Required behavior.** Create one logical threshold action for an obligation cycle, route to active duty ownership and retain delivery attempts. Escalation never decides a safety case.

**Successful path.** A due obligation generates one escalation task even with two schedulers.

**Unsuccessful path.** A restart, duplicate delivery or completed obligation cannot generate a second logical escalation for the same threshold.

**Recovery.** Reconcile due work from the database; unresolved delivery failures remain visible and escalation can be acknowledged without falsifying business resolution.

**Acceptance evidence.** Implement the corresponding six `AT-19-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-20 - Guarded decisions and authority

**Actor:** Decision authority. **Module:** `decisions`. **Build task:** B12. **Screens:** UI-14.

**Required behavior.** Bind a reasoned outcome to expected case version, submitted revision, report, finding set, policy and effective authority. Enforce separation where the profile requires it.

**Successful path.** A permitted reviewer with all mandatory blockers closed records one favorable decision and creates issuance intent.

**Unsuccessful path.** Self-approval when prohibited, revoked authority, stale case version or mandatory failure blocks the decision.

**Recovery.** Reload and review current evidence; no technical administrator override. Appeal or corrective instrument uses a separate authorized lifecycle.

**Acceptance evidence.** Implement the corresponding six `AT-20-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-21 - Issuance and external registration

**Actor:** System / authorized registrar. **Module:** `certificates`. **Build task:** B12. **Screens:** UI-16, UI-17.

**Required behavior.** Keep APPROVED_PENDING_ISSUE until the required artifact, signature or demo watermark, registry entry and publication checks succeed. Register external instruments without pretending to issue them.

**Successful path.** One favorable decision produces one published instrument and COMPLETED.

**Unsuccessful path.** Signer timeout, invalid signature or object-store failure does not produce COMPLETED or REJECTED.

**Recovery.** Reconcile the stable issuance request before retry; resume failed jobs without allocating another certificate number.

**Acceptance evidence.** Implement the corresponding six `AT-21-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-22 - Privacy-safe public verification

**Actor:** Public. **Module:** `certificates`. **Build task:** B12. **Screens:** UI-01, UI-18.

**Required behavior.** Return minimal approved registry fields, status, source and checked-at freshness. ACTIVE, EXPIRED, SUSPENDED, REVOKED and SUPERSEDED remain distinct.

**Successful path.** A valid registry token shows the correct instrument state and limited premises identifier.

**Unsuccessful path.** An outage, stale external record or unknown token never yields an active assertion or sensitive applicant detail.

**Recovery.** Show temporarily unverifiable with retry and support guidance; do not cache a stale active response as current.

**Acceptance evidence.** Implement the corresponding six `AT-22-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-23 - Notifications and delivery visibility

**Actor:** System / recipient. **Module:** `notifications`. **Build task:** B10. **Screens:** UI-19, UI-20.

**Required behavior.** Render versioned templates, create in-app notification intent transactionally, track each channel attempt and obey contact preferences and mandatory service rules.

**Successful path.** A notice appears in-app even while the optional email gateway is unavailable.

**Unsuccessful path.** A delivery bounce or provider timeout cannot change application outcome or expose message contents to unrelated staff.

**Recovery.** Retry safe attempts with provider idempotency where supported; ambiguous outcomes reconcile and display uncertainty.

**Acceptance evidence.** Implement the corresponding six `AT-23-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-24 - Certificate lifecycle and continuing obligations

**Actor:** Holder / authority. **Module:** `certificates`. **Build task:** B13. **Screens:** UI-16, UI-17, UI-15.

**Required behavior.** Support renewal, permitted declarations and status actions from approved profiles. A renewal is a new linked case; status instruments have reasons and authority.

**Successful path.** An eligible holder creates a linked renewal draft without modifying the original certificate.

**Unsuccessful path.** An expired follow-up clock does not automatically revoke or extend validity.

**Recovery.** An authorized status action records its basis; a superseding instrument preserves the predecessor and public history allowed by policy.

**Acceptance evidence.** Implement the corresponding six `AT-24-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-25 - Operational dashboards and metrics

**Actor:** Supervisor / leadership. **Module:** `reporting`. **Build task:** B14. **Screens:** UI-09, UI-15, UI-22.

**Required behavior.** Calculate metrics from scoped authoritative records at one cutoff; show definitions, filters and freshness. Distinguish decisions, publication and waiting periods.

**Successful path.** Status totals reconcile to the same filtered population and cutoff.

**Unsuccessful path.** Drafts, failed jobs and unknown external statuses cannot be counted as rejected applications.

**Recovery.** Report unavailable rather than zero on failure; stale projections are labelled and can be rebuilt from source records.

**Acceptance evidence.** Implement the corresponding six `AT-25-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-26 - Controlled exports

**Actor:** Permitted exporter. **Module:** `reporting`. **Build task:** B14. **Screens:** UI-05, UI-22, UI-23.

**Required behavior.** Create scoped, purpose-recorded exports with field minimization, cutoff, requester, expiring access and spreadsheet-formula protection.

**Successful path.** A permitted filtered CSV contains only authorized records and escaped user-controlled cells.

**Unsuccessful path.** An expired permission or object URL cannot authorize a new download; another user cannot obtain the export by guessing its ID.

**Recovery.** Cancel or expire unsafe exports; regenerate under current scope. Keep a manifest and access audit, not permanent public links.

**Acceptance evidence.** Implement the corresponding six `AT-26-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-27 - Policy and master-data governance

**Actor:** Preparer / independent approver. **Module:** `policies`. **Build task:** B04. **Screens:** UI-24.

**Required behavior.** Create immutable proposed versions of forms, checklists, calendars, routing and service rules. Independently approve and schedule activation; pin submitted cases.

**Successful path.** An approved future version affects only submissions governed by its effective interval.

**Unsuccessful path.** The preparer cannot approve their own version; overlapping active intervals and invalid schemas are rejected.

**Recovery.** Return the draft with comments or publish a correcting new version. Migration of existing cases needs a separate approved plan and recorded impact.

**Acceptance evidence.** Implement the corresponding six `AT-27-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-28 - Business and sensitive-access audit

**Actor:** System / permitted auditor. **Module:** `audit`. **Build task:** B02. **Screens:** UI-23.

**Required behavior.** Persist case events and audit records for mutations, decisions, grants, exports and sensitive reads. Protect audit from normal application update/delete rights.

**Successful path.** A decision and its audit/outbox records commit together with correlation identifiers.

**Unsuccessful path.** An audit-write failure rolls back a critical mutation; unauthorized audit queries do not expose personal content.

**Recovery.** Recover the dependency and retry safely; export integrity checkpoints to separately controlled storage for tamper detection.

**Acceptance evidence.** Implement the corresponding six `AT-28-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-29 - Integration ownership and reconciliation

**Actor:** Integration operator / system. **Module:** `integrations`. **Build task:** B15. **Screens:** UI-20, UI-25.

**Required behavior.** Verify partner identity, source ownership, schema, event ID and source sequence. Preserve incoming events before processing; quarantine invalid or out-of-order data.

**Successful path.** A duplicate partner event is acknowledged without another local business effect.

**Unsuccessful path.** An older status event cannot overwrite a newer authoritative outcome; a failed partner call is not reported successful.

**Recovery.** Reconcile from an approved source endpoint or manual evidence workflow; conflicts remain assigned until resolved with provenance.

**Acceptance evidence.** Implement the corresponding six `AT-29-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.

### FR-30 - Support, withdrawal and profile-dependent appeals

**Actor:** Applicant / support / authority. **Module:** `support`. **Build task:** B13. **Screens:** UI-26, UI-07.

**Required behavior.** Track support tickets separately from regulatory notices. Withdrawal is a guarded case action. Appeals use the approved separate process and do not erase a final decision.

**Successful path.** A user creates a scoped ticket or an allowed withdrawal with clear acknowledgement and history.

**Unsuccessful path.** A helpdesk response cannot reopen a terminal case, approve a certificate or imply a legally filed appeal.

**Recovery.** Escalate to the correct authority; offer the approved referral route when appeals are not enabled. Keep all original outcomes intact.

**Acceptance evidence.** Implement the corresponding six `AT-30-*` checks in [the test plan](11_TEST_PLAN_AND_ACCEPTANCE.md), including server/API assertions rather than UI-only observations. Verify persisted state, returned result, audit visibility and absence of unintended side effects. A relevant provider failure must leave the case in its valid business state.


## 4. Detailed cross-role journeys

### 4.1 New application without deficiencies

1. Applicant signs in, chooses service and authorized premises, and receives the versioned requirements.
2. The wizard saves a DRAFT. Every document row independently shows upload and scan state.
3. Review screen summarizes submitted data, missing items and declarations. Submission is blocked while required evidence is not accepted.
4. Submit returns a receipt, immutable revision number and responsible scrutiny queue. Applicant cannot edit the frozen submission.
5. Supervisor starts scrutiny, records acceptance of completeness and requires an inspection. A booking is saved only after current eligibility and overlap checks.
6. Officer completes the checklist and submits a report. A server receipt, not a local toast, establishes acceptance.
7. Reviewer inspects the evidence. The favorable action is enabled only after all applicable guards pass.
8. A favorable decision creates issuance work. The user follows job status until publication.
9. Applicant sees the sample certificate; public verification independently reads the registry status. Leadership and operational metrics update from the same source data.

### 4.2 Information request before inspection

Supervisor publishes specific completeness items; case enters INFO_REQUIRED. Applicant responds item by item. The case remains INFO_REQUIRED while responses are waiting for review. `Accept information` requires all mandatory items accepted and returns it to SCRUTINY. An incomplete item can be returned with a new reason and deadline treatment from policy. Merely uploading a file never accepts the response.

### 4.3 Deficiency after inspection

A mandatory failed item creates a finding and a published deficiency notice; case enters COMPLIANCE_PENDING. Applicant supplies corrective evidence. Reviewer either verifies closure, returns the response, or creates a reinspection. Only complete verified closure returns the case to REVIEW_PENDING. New attempts have new identifiers; the original failed observations remain available.

### 4.4 Rejected or withdrawn case

The terminal record is immutable as an outcome. The applicant can view permitted reasons, download the decision record and follow the approved referral, fresh-application or appeal route. A new application can copy eligible premises fields, but not pretend old evidence is current. A terminal case must not reappear as DRAFT through a generic edit or helpdesk command.

### 4.5 Operational interruption

With the broker stopped, a valid API command may still commit its outbox intent and show accepted work pending dispatch. With PostgreSQL unavailable, it cannot claim acceptance. A failed PDF, scan, notification or signing job appears in operations with reason, attempt history, owner and next recovery action. The operations administrator cannot change the regulatory status to conceal the failure.

## 5. Business outcomes and safety invariants

- No `COMPLETED` department-issued case without a published instrument bound to its final favorable decision.
- No favorable decision with unresolved mandatory evidence or finding blockers.
- No signature, scanner or email-provider outage converted into a rejection.
- No destructive overwrite of a submitted document, report, notice or decision.
- No application-number sequence or difficult-to-guess identifier treated as authorization.
- No role switch granting a role the authenticated identity does not possess.
- No KPI improvements asserted from synthetic fixture results.

## 6. Global user-visible error rules

For invalid fields, retain entered values, show an error summary linked to controls and explain correction. For an expired session, save only permitted local draft state, request sign-in and resume the intended route. For forbidden access, do not reveal existence or applicant details. For version conflict, show the server version and safe compare/reapply action. For dependency outage, show retry and reference ID with a timestamp; never reset the form or display zero records as a successful empty result.

Background retry limits and permanent failure states are in the recovery specification. The user must not see stack traces, database error text, provider credentials, access tokens or hidden internal case notes.

## 7. Scope-dependent actions

Appeal, statutory payment, external registration, certificate suspension/reinstatement and legal hold are offered only when a valid profile grants them. The demonstration may illustrate these with synthetic authority and obvious labels. A disabled live feature has an explanatory service message and approved support/referral action. Hiding a required legal step behind a feature flag is not a valid way to activate the dependent live service.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
