# Test plan, acceptance cases and verification evidence

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Test status and scope

Every test in this document is **specified, not executed for the new implementation**. Earlier prototype or paper demonstrations do not prove the Django/PostgreSQL build works. Record actual execution by commit, environment, dependency lock, test data, timestamp and result. Use PASS, FAIL, BLOCKED or NOT_RUN; never infer PASS from code existing.

The suite covers normal behavior, invalid input, authority/scope, state transitions, concurrency, duplicate delivery, dependency outages, offline conflicts, browser storage limits, accessibility and recovery. No finite document can enumerate every future defect; unexpected failures must fail safely, produce a reference ID and become a regression test once understood.

## 2. Test layers and tooling

| Layer | Tool and setup | Required assertions |
| --- | --- | --- |
| Pure domain | pytest + Hypothesis; deterministic clock | State guards, interval arithmetic, policy selection, mandatory checklist logic. |
| Database/application | pytest-django with real PostgreSQL | Transactions, constraints, locks, uniqueness, audit/outbox atomicity and rollback. |
| API contract | DRF client + OpenAPI schema validation | Payload, status, error codes, scope, ETags, idempotency and data minimization. |
| Adapter | Approved local simulators and provider sandbox | Success, known failure, unknown outcome, deduplication and reconciliation. |
| UI component | Vitest + Testing Library | Accessible controls, form errors, stale/loading/empty states and no unsafe optimistic success. |
| End-to-end | Playwright + isolated seeded services | Real role journeys and persisted canonical outcomes after browser reload. |
| Accessibility | axe-core plus keyboard/screen-reader/manual checks | Focus, labels, error summaries, contrast, reflow and equivalent chart data. |
| Reliability | Controlled fault harness with dedicated Docker project | Broker/worker/storage outage, lease expiry, unknown remote effect and eventual correct recovery. |
| Performance | Locust + monitored real stack | Measured latency/error rate/resource usage at declared workload and dataset. |
| Recovery | Isolated database/object restore | Counts, hashes, secrets/key access, canonical relations and usable recovered workflow. |

Suggested quality thresholds: at least 85% branch coverage of domain/application code, with 100% of named safety guards and critical state transitions represented by tests. Coverage percentage is not proof of correctness. Include both lower and upper boundary values and stateful property tests. Do not mock away the component whose behavior the test is supposed to prove.

## 3. Core requirement acceptance cases

Each FR has six acceptance cases. The given condition is a deterministic fixture for that FR with its described actor, scope, state and evidence. Execute through API/application service and, where listed, the real UI. Assert canonical rows, state/version, receipt, audit and outbox when the action creates them. Negative cases assert absence of unauthorized/partial side effects.

### FR-01 - Applicant identity and account recovery

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-01-01 | Valid workflow | A valid one-time challenge creates one authenticated session and opens only that applicant profile. | NOT_RUN |
| AT-01-02 | Invalid or blocked workflow | An expired, reused, throttled or incorrect challenge never grants a session; an enumeration-safe response does not reveal account existence. | NOT_RUN |
| AT-01-03 | Recovery path | Allow resend after the configured cooldown; invalidate superseded challenges. Account-contact replacement requires verified recovery, never an administrator silently changing the owner. | NOT_RUN |
| AT-01-04 | Authorization/privacy | Attempt account enumeration, login CSRF, consumed challenge and unauthorized contact replacement; no session or ownership change is granted. | NOT_RUN |
| AT-01-05 | Concurrency/replay | Submit the same OTP verification concurrently; only one challenge consumption is accepted and session issuance follows the documented single-use rule. | NOT_RUN |
| AT-01-06 | Screen and accessibility | On UI-02, UI-03, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-02 - Staff provisioning and account lifecycle

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-02-01 | Valid workflow | An approved invitation links the intended staff subject and exposes only approved workspaces. | NOT_RUN |
| AT-02-02 | Invalid or blocked workflow | Public registration cannot request a privileged role; disabled or expired grants are rejected even with an existing session. | NOT_RUN |
| AT-02-03 | Recovery path | Revoke sessions and increment the authorization epoch; pending assignments move to a visible duty queue without deleting past work. | NOT_RUN |
| AT-02-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-02-05 | Concurrency/replay | Race account/grant revocation with an authorized write; lock ordering yields a documented before/after decision and no post-revocation stale-authority acceptance. | NOT_RUN |
| AT-02-06 | Screen and accessibility | On UI-21, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-03 - Service applicability and premises

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-03-01 | Valid workflow | A supported category displays the exact applicable form and document list. | NOT_RUN |
| AT-03-02 | Invalid or blocked workflow | Unknown category, overlapping policy or unsupported jurisdiction does not fabricate eligibility. | NOT_RUN |
| AT-03-03 | Recovery path | Keep the draft; explain unsupported service or route a clarification request to a named queue. Do not accept a live submission without an approved profile. | NOT_RUN |
| AT-03-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-03-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-03-06 | Screen and accessibility | On UI-04, UI-06, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-04 - Draft creation and editing

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-04-01 | Valid workflow | The user returns to the saved draft and sees preserved fields and file status. | NOT_RUN |
| AT-04-02 | Invalid or blocked workflow | A second-tab stale save returns a version conflict rather than overwriting newer values. | NOT_RUN |
| AT-04-03 | Recovery path | Show the field differences and let the user reapply allowed edits to a current version. Retry an ambiguous save with its original key. | NOT_RUN |
| AT-04-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-04-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-04-06 | Screen and accessibility | On UI-05, UI-06, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-05 - Document and evidence intake

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-05-01 | Valid workflow | A valid uploaded file becomes CLEAN with a new immutable document version. | NOT_RUN |
| AT-05-02 | Invalid or blocked workflow | A malicious, unsupported, oversized, truncated or still-scanning file cannot satisfy a required evidence item. | NOT_RUN |
| AT-05-03 | Recovery path | Keep safe draft data and a human-readable upload status; retry a new reservation for a failed upload. Scanner outage leaves QUARANTINED, not CLEAN. | NOT_RUN |
| AT-05-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-05-05 | Concurrency/replay | Repeat upload completion and scan delivery; one immutable document version/result is linked, and mismatched checksum or object replacement is rejected. | NOT_RUN |
| AT-05-06 | Screen and accessibility | On UI-06, UI-08, UI-12, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-06 - Atomic application submission

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-06-01 | Valid workflow | One accepted command returns one receipt and SUBMITTED with accountable scrutiny ownership. | NOT_RUN |
| AT-06-02 | Invalid or blocked workflow | Missing documents or unapproved profile rejects the command without a receipt or partial stage transition. | NOT_RUN |
| AT-06-03 | Recovery path | Same key and same payload returns the original accepted result after authorization; changed payload with the same key is rejected. | NOT_RUN |
| AT-06-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-06-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-06-06 | Screen and accessibility | On UI-06, UI-07, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-07 - Jurisdiction routing and exceptions

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-07-01 | Valid workflow | Exactly one applicable mapping selects the expected scrutiny queue. | NOT_RUN |
| AT-07-02 | Invalid or blocked workflow | No match does not randomly select an officer, drop the case, or suspend the case-wide clock. | NOT_RUN |
| AT-07-03 | Recovery path | Supervisor resolves the exception with a valid mapping or authorized referral; keep old routing events and notify permitted participants. | NOT_RUN |
| AT-07-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-07-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-07-06 | Screen and accessibility | On UI-09, UI-15, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-08 - Assignment and reassignment

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-08-01 | Valid workflow | An eligible officer receives the appointment in the task queue. | NOT_RUN |
| AT-08-02 | Invalid or blocked workflow | Concurrent overlapping bookings or assignment to an inactive/out-of-scope officer fails atomically. | NOT_RUN |
| AT-08-03 | Recovery path | Display available alternatives; reassign through a new version and revoke stale offline authority without deleting earlier evidence. | NOT_RUN |
| AT-08-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-08-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-08-06 | Screen and accessibility | On UI-10, UI-11, UI-21, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-09 - Case visibility and timeline

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-09-01 | Valid workflow | Applicant sees a published information request and own receipt; supervisor sees permitted internal review context. | NOT_RUN |
| AT-09-02 | Invalid or blocked workflow | Cross-applicant IDs, internal notes and unauthorized evidence remain inaccessible, including direct URLs and exports. | NOT_RUN |
| AT-09-03 | Recovery path | A failed refresh keeps previous data visibly stale with timestamp and retry; never invent progress. | NOT_RUN |
| AT-09-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-09-05 | Concurrency/replay | Change data and scope during refresh/export; result uses the documented cutoff and current authorization, with no cross-scope cache or internally inconsistent totals. | NOT_RUN |
| AT-09-06 | Screen and accessibility | On UI-05, UI-07, UI-09, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-10 - Assisted intake and delegation

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-10-01 | Valid workflow | A valid representative submits for the named beneficiary and both identities are recorded. | NOT_RUN |
| AT-10-02 | Invalid or blocked workflow | An expired or unrelated delegation cannot view, edit or submit that beneficiary case. | NOT_RUN |
| AT-10-03 | Recovery path | The beneficiary may revoke or approve a new delegation through the controlled flow; history remains attributable. | NOT_RUN |
| AT-10-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-10-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-10-06 | Screen and accessibility | On UI-03, UI-04, UI-06, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-11 - Appointments and visit outcomes

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-11-01 | Valid workflow | An agreed time slot appears in both the officer queue and applicant timeline. | NOT_RUN |
| AT-11-02 | Invalid or blocked workflow | An inaccessible site or no-show does not complete an inspection or silently reset elapsed time. | NOT_RUN |
| AT-11-03 | Recovery path | Create a new attempt or reschedule an unstarted attempt under policy; preserve the failure record and unresolved case obligations. | NOT_RUN |
| AT-11-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-11-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-11-06 | Screen and accessibility | On UI-10, UI-11, UI-12, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-12 - Offline drafts and explicit synchronization

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-12-01 | Valid workflow | An offline draft synchronizes once after reauthentication and current-authority checks. | NOT_RUN |
| AT-12-02 | Invalid or blocked workflow | Browser eviction, revoked assignment or unavailable storage must not be represented as server-accepted evidence. | NOT_RUN |
| AT-12-03 | Recovery path | Warn about unsynchronized work; handle storage errors visibly. Retain a locked local conflict package only under approved recovery rules. | NOT_RUN |
| AT-12-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-12-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-12-06 | Screen and accessibility | On UI-12, UI-13, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-13 - Versioned inspection report and provenance

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-13-01 | Valid workflow | A submitted report binds actor, server time, client capture time and object hashes and enters REVIEW_PENDING. | NOT_RUN |
| AT-13-02 | Invalid or blocked workflow | A stale report or changed evidence reference cannot replace a newer accepted report. | NOT_RUN |
| AT-13-03 | Recovery path | Return structured conflicts; corrections create an attributed addendum or replacement revision through authorized review, not a raw update. | NOT_RUN |
| AT-13-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-13-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-13-06 | Screen and accessibility | On UI-12, UI-14, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-14 - Deterministic checklist evaluation

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-14-01 | Valid workflow | Complete compliant evidence creates an eligible-for-review result, not an automatic approval. | NOT_RUN |
| AT-14-02 | Invalid or blocked workflow | A high numeric score cannot compensate for one mandatory FAIL or unauthorized NA. | NOT_RUN |
| AT-14-03 | Recovery path | Create itemized findings; require verified closure and any necessary reinspection before reevaluation. | NOT_RUN |
| AT-14-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-14-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-14-06 | Screen and accessibility | On UI-12, UI-14, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-15 - Information requests and deficiency notices

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-15-01 | Valid workflow | Applicant receives one notice with actionable items and response controls. | NOT_RUN |
| AT-15-02 | Invalid or blocked workflow | Empty reasons, contradictory items or duplicate publication using the same logical command are rejected or replayed. | NOT_RUN |
| AT-15-03 | Recovery path | Correct through a superseding notice with a clear relationship; retain the original and clock disposition. | NOT_RUN |
| AT-15-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-15-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-15-06 | Screen and accessibility | On UI-08, UI-14, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-16 - Applicant response versions

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-16-01 | Valid workflow | A complete response moves its item to RESPONSE_RECEIVED and notifies the review queue. | NOT_RUN |
| AT-16-02 | Invalid or blocked workflow | Unrelated or quarantined evidence and attempts to edit a closed notice are rejected. | NOT_RUN |
| AT-16-03 | Recovery path | Allow a new permitted response revision or request reopening of the item through review; display what is still missing. | NOT_RUN |
| AT-16-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-16-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-16-06 | Screen and accessibility | On UI-08, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-17 - Verification, return and reinspection

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-17-01 | Valid workflow | All mandatory findings verified closed return the case to review. | NOT_RUN |
| AT-17-02 | Invalid or blocked workflow | A document upload or applicant checkbox alone cannot close a mandatory safety finding. | NOT_RUN |
| AT-17-03 | Recovery path | Return specific unresolved items or create a new inspection attempt; retain the deficiency cycle and its original timing history. | NOT_RUN |
| AT-17-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-17-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-17-06 | Screen and accessibility | On UI-08, UI-14, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-18 - Persistent stage and case clocks

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-18-01 | Valid workflow | A four-working-hour internal obligation started at 09:00 is due 13:00; a permitted one-hour pause moves it to 14:00. | NOT_RUN |
| AT-18-02 | Invalid or blocked workflow | Overlapping pauses must not double-subtract; reassignment, downtime and failed notifications do not automatically pause clocks. | NOT_RUN |
| AT-18-03 | Recovery path | Recompute from immutable events and approved calendar; show an auditable correction instead of editing timestamps silently. | NOT_RUN |
| AT-18-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-18-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-18-06 | Screen and accessibility | On UI-15, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-19 - Reminders and accountable escalation

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-19-01 | Valid workflow | A due obligation generates one escalation task even with two schedulers. | NOT_RUN |
| AT-19-02 | Invalid or blocked workflow | A restart, duplicate delivery or completed obligation cannot generate a second logical escalation for the same threshold. | NOT_RUN |
| AT-19-03 | Recovery path | Reconcile due work from the database; unresolved delivery failures remain visible and escalation can be acknowledged without falsifying business resolution. | NOT_RUN |
| AT-19-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-19-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-19-06 | Screen and accessibility | On UI-15, UI-19, UI-20, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-20 - Guarded decisions and authority

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-20-01 | Valid workflow | A permitted reviewer with all mandatory blockers closed records one favorable decision and creates issuance intent. | NOT_RUN |
| AT-20-02 | Invalid or blocked workflow | Self-approval when prohibited, revoked authority, stale case version or mandatory failure blocks the decision. | NOT_RUN |
| AT-20-03 | Recovery path | Reload and review current evidence; no technical administrator override. Appeal or corrective instrument uses a separate authorized lifecycle. | NOT_RUN |
| AT-20-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-20-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-20-06 | Screen and accessibility | On UI-14, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-21 - Issuance and external registration

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-21-01 | Valid workflow | One favorable decision produces one published instrument and COMPLETED. | NOT_RUN |
| AT-21-02 | Invalid or blocked workflow | Signer timeout, invalid signature or object-store failure does not produce COMPLETED or REJECTED. | NOT_RUN |
| AT-21-03 | Recovery path | Reconcile the stable issuance request before retry; resume failed jobs without allocating another certificate number. | NOT_RUN |
| AT-21-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-21-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-21-06 | Screen and accessibility | On UI-16, UI-17, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-22 - Privacy-safe public verification

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-22-01 | Valid workflow | A valid registry token shows the correct instrument state and limited premises identifier. | NOT_RUN |
| AT-22-02 | Invalid or blocked workflow | An outage, stale external record or unknown token never yields an active assertion or sensitive applicant detail. | NOT_RUN |
| AT-22-03 | Recovery path | Show temporarily unverifiable with retry and support guidance; do not cache a stale active response as current. | NOT_RUN |
| AT-22-04 | Authorization/privacy | Use anonymous lookup and inspect every response field; only the approved public subset appears, with no private case IDs, contacts or evidence URLs. | NOT_RUN |
| AT-22-05 | Concurrency/replay | Advance the clock across expiry and interrupt source connectivity; an earlier active response is not reused as a current assertion. | NOT_RUN |
| AT-22-06 | Screen and accessibility | On UI-01, UI-18, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-23 - Notifications and delivery visibility

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-23-01 | Valid workflow | A notice appears in-app even while the optional email gateway is unavailable. | NOT_RUN |
| AT-23-02 | Invalid or blocked workflow | A delivery bounce or provider timeout cannot change application outcome or expose message contents to unrelated staff. | NOT_RUN |
| AT-23-03 | Recovery path | Retry safe attempts with provider idempotency where supported; ambiguous outcomes reconcile and display uncertainty. | NOT_RUN |
| AT-23-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-23-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-23-06 | Screen and accessibility | On UI-19, UI-20, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-24 - Certificate lifecycle and continuing obligations

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-24-01 | Valid workflow | An eligible holder creates a linked renewal draft without modifying the original certificate. | NOT_RUN |
| AT-24-02 | Invalid or blocked workflow | An expired follow-up clock does not automatically revoke or extend validity. | NOT_RUN |
| AT-24-03 | Recovery path | An authorized status action records its basis; a superseding instrument preserves the predecessor and public history allowed by policy. | NOT_RUN |
| AT-24-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-24-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-24-06 | Screen and accessibility | On UI-16, UI-17, UI-15, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-25 - Operational dashboards and metrics

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-25-01 | Valid workflow | Status totals reconcile to the same filtered population and cutoff. | NOT_RUN |
| AT-25-02 | Invalid or blocked workflow | Drafts, failed jobs and unknown external statuses cannot be counted as rejected applications. | NOT_RUN |
| AT-25-03 | Recovery path | Report unavailable rather than zero on failure; stale projections are labelled and can be rebuilt from source records. | NOT_RUN |
| AT-25-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-25-05 | Concurrency/replay | Change data and scope during refresh/export; result uses the documented cutoff and current authorization, with no cross-scope cache or internally inconsistent totals. | NOT_RUN |
| AT-25-06 | Screen and accessibility | On UI-09, UI-15, UI-22, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-26 - Controlled exports

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-26-01 | Valid workflow | A permitted filtered CSV contains only authorized records and escaped user-controlled cells. | NOT_RUN |
| AT-26-02 | Invalid or blocked workflow | An expired permission or object URL cannot authorize a new download; another user cannot obtain the export by guessing its ID. | NOT_RUN |
| AT-26-03 | Recovery path | Cancel or expire unsafe exports; regenerate under current scope. Keep a manifest and access audit, not permanent public links. | NOT_RUN |
| AT-26-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-26-05 | Concurrency/replay | Change data and scope during refresh/export; result uses the documented cutoff and current authorization, with no cross-scope cache or internally inconsistent totals. | NOT_RUN |
| AT-26-06 | Screen and accessibility | On UI-05, UI-22, UI-23, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-27 - Policy and master-data governance

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-27-01 | Valid workflow | An approved future version affects only submissions governed by its effective interval. | NOT_RUN |
| AT-27-02 | Invalid or blocked workflow | The preparer cannot approve their own version; overlapping active intervals and invalid schemas are rejected. | NOT_RUN |
| AT-27-03 | Recovery path | Return the draft with comments or publish a correcting new version. Migration of existing cases needs a separate approved plan and recorded impact. | NOT_RUN |
| AT-27-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-27-05 | Concurrency/replay | Race policy activation with submission and attempt overlapping activation; exactly one applicable pinned version or explicit error results. | NOT_RUN |
| AT-27-06 | Screen and accessibility | On UI-24, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-28 - Business and sensitive-access audit

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-28-01 | Valid workflow | A decision and its audit/outbox records commit together with correlation identifiers. | NOT_RUN |
| AT-28-02 | Invalid or blocked workflow | An audit-write failure rolls back a critical mutation; unauthorized audit queries do not expose personal content. | NOT_RUN |
| AT-28-03 | Recovery path | Recover the dependency and retry safely; export integrity checkpoints to separately controlled storage for tamper detection. | NOT_RUN |
| AT-28-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-28-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-28-06 | Screen and accessibility | On UI-23, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-29 - Integration ownership and reconciliation

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-29-01 | Valid workflow | A duplicate partner event is acknowledged without another local business effect. | NOT_RUN |
| AT-29-02 | Invalid or blocked workflow | An older status event cannot overwrite a newer authoritative outcome; a failed partner call is not reported successful. | NOT_RUN |
| AT-29-03 | Recovery path | Reconcile from an approved source endpoint or manual evidence workflow; conflicts remain assigned until resolved with provenance. | NOT_RUN |
| AT-29-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-29-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-29-06 | Screen and accessibility | On UI-20, UI-25, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |

### FR-30 - Support, withdrawal and profile-dependent appeals

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-30-01 | Valid workflow | A user creates a scoped ticket or an allowed withdrawal with clear acknowledgement and history. | NOT_RUN |
| AT-30-02 | Invalid or blocked workflow | A helpdesk response cannot reopen a terminal case, approve a certificate or imply a legally filed appeal. | NOT_RUN |
| AT-30-03 | Recovery path | Escalate to the correct authority; offer the approved referral route when appeals are not enabled. Keep all original outcomes intact. | NOT_RUN |
| AT-30-04 | Authorization/privacy | Use another applicant/jurisdiction, an expired grant or an unassigned actor; operation and sensitive read are denied with no leaked data or side effect. | NOT_RUN |
| AT-30-05 | Concurrency/replay | Repeat the logical command and race it against a current version change; one canonical effect or a documented conflict, never duplicate state/history or silent overwrite. | NOT_RUN |
| AT-30-06 | Screen and accessibility | On UI-26, UI-07, test direct navigation, keyboard action, reload, loading/empty/failed/stale states and narrow viewport. Correct canonical state is restored; no dead control or misleading success. | NOT_RUN |


## 4. Required state and concurrency properties

| ID | Property / test |
| --- | --- |
| PROP-01 | For every application state and every command, exactly the permitted transitions succeed; all unlisted transitions leave state unchanged. |
| PROP-02 | A favorable decision implies all applicable mandatory findings/evidence guards passed on the bound versions. |
| PROP-03 | COMPLETED department issuance implies exactly one published registry/artifact relationship for the final decision. |
| PROP-04 | Replaying any accepted business command does not create another receipt, notice, decision or instrument. |
| PROP-05 | A same key with a different normalized payload never reuses a previous success as if it applied to new content. |
| PROP-06 | Overlapping pause intervals are unioned; active elapsed time never becomes negative and is monotone outside authorized correction. |
| PROP-07 | Reassignment and failed appointments do not reset the independent case clock. |
| PROP-08 | Two schedulers create one logical threshold action per obligation cycle/threshold. |
| PROP-09 | Two competing active bookings for one officer cannot overlap after commit. |
| PROP-10 | Revocation and a sensitive command serialize through the same authorization fence. |
| PROP-11 | A stale worker lease cannot complete or overwrite a newer attempt's result. |
| PROP-12 | An expired certificate cannot verify ACTIVE even if its projection was never refreshed by a scheduler. |
| PROP-13 | A partner event with an older source version cannot overwrite a newer authoritative projection. |
| PROP-14 | A response from one case cannot satisfy an item/finding in another case. |
| PROP-15 | A retained submitted revision's referenced object hash cannot be changed by an upload replacement. |
| PROP-16 | All role-scoped KPI drill-downs reconcile to the exact same reporting population and cutoff. |

Run concurrency tests with separate database connections/processes and synchronization barriers. A sequential loop is not proof of a race condition being handled. Explicitly assert which transaction succeeds, which fails and why.

## 5. End-to-end journey suite

| ID | Journey and required proof |
| --- | --- |
| E2E-01 | Applicant -> new draft -> clean uploads -> submit -> receipt -> reload -> same immutable submission. |
| E2E-02 | Missing mandatory document and pending scan block submission while preserving the draft. |
| E2E-03 | Timeout after accepted submit -> same-key retry -> one application receipt. |
| E2E-04 | Wrong/multiple routing match -> visible owned exception -> authorized resolution. |
| E2E-05 | Schedule -> overlap conflict -> alternative booking -> applicant/officer calendar consistency. |
| E2E-06 | Failed visit -> retained failed attempt -> new scheduled attempt -> unchanged case clock. |
| E2E-07 | Mandatory failed checklist -> no approval -> deficiency notice. |
| E2E-08 | Applicant response -> review return -> new response -> verified closure -> review queue. |
| E2E-09 | Correction requiring physical revisit -> reinspection -> accepted new report -> authorized closure. |
| E2E-10 | Offline report -> partial uploads -> clean scans -> one canonical report receipt. |
| E2E-11 | Offline report after reassignment -> conflict -> reviewed resolution, no overwrite. |
| E2E-12 | Two reviewers decide on same case -> one decision, one structured conflict. |
| E2E-13 | Approval -> renderer failure -> pending issuance -> safe recovery -> one certificate. |
| E2E-14 | Unknown signing outcome -> reconcile existing provider request -> no second signature request when outcome uncertain. |
| E2E-15 | Public active/expired/suspended/revoked/superseded/unknown/unavailable scenarios render distinctly and privately. |
| E2E-16 | Renewal creates linked new draft without changing source certificate validity. |
| E2E-17 | Policy preparer cannot approve; independent approval activates new version; old cases remain pinned. |
| E2E-18 | Admin deactivation revokes access and exposes assignment handoff; admin cannot decide case. |
| E2E-19 | Leadership reports/exports match fixture oracle; formula injection and changed-scope download blocked. |
| E2E-20 | Support/referral/withdrawal does not reopen or overwrite terminal regulatory decisions. |

## 6. Fault injection suite

Use a separate Docker project and synthetic secrets/data. Inject database unavailable before command, broken connection after commit, broker unavailable after outbox commit, worker kill after remote effect, expired lease with late completion, scanner unavailable, object missing/corrupt, notification bounce, invalid/duplicate webhook, schema mismatch, report-cache loss and outage across multiple obligation thresholds. Each test records expected canonical counts, visible state, recovery owner and final reconciliation.

Do not mark a test passed merely because no exception appeared. Query the business rows, outbox, job attempts, audit and provider simulator ledger. Ensure an irreversible action is not duplicated when the provider result is unknown. Clean up only the dedicated test project after evidence is collected.

## 7. Performance test protocol

Reference dataset:10,000 synthetic applications, realistic related evidence metadata and notices, no real personal data. Workload:100 concurrent active users with measured mix of70% scoped reads,20% draft/response mutations and10% inspection/review actions. Separate upload throughput and heavy rendering tests from ordinary command-latency measurements. Warm-up5 minutes, steady measurement15 minutes, and a documented burst phase; record host CPU/RAM/disk, DB pool, worker concurrency, image digests and network conditions.

Targets: p95 ordinary case reads<800 ms; p95 non-file command acceptance<1.5 s; no lost accepted intent; no duplicate canonical decisions/instruments; normal dispatch lag<60 s. Report p50/p95/p99, error rates by code, queue depth, CPU/memory and database locks. These are proposed targets until measured. Failing a target triggers query/capacity analysis, not hard-coded fake delays or omitted slow samples.

## 8. Accessibility and device acceptance

Test360/390/768/1280/1440 px layouts, keyboard-only task completion, focus restoration in dialogs, error-summary links, screen-reader field names, contrast,200% zoom/reflow, reduced motion and camera/GPS denial. Run the officer offline suite on approved Android Chrome and any additional supported browsers; Firefox/Safari lack of Background Sync must not break explicit synchronization.

Automated axe results are useful but do not replace manual task testing. Record browser/OS versions rather than saying works on all devices. Hindi UI activation requires reviewed translations and complete critical-path coverage; untranslated legal text is not accepted.

## 9. Test evidence format

For each run store test ID, FR/TR/API/UI mapping, commit, environment, data seed/version, dependency lock hash, timestamp, command, expected result, actual result, PASS/FAIL/BLOCKED/NOT_RUN, redacted logs/screenshots and defect reference. A BLOCKED test identifies missing credentials/provider/device and exact manual reproduction instructions. Do not ask users to paste secrets into committed reports.

## 10. Release exit criteria

All applicable core FR acceptance cases, state/authority guards and enabled screen routes must pass. Critical/high security defects and data-integrity failures block release. Every planned live adapter has its actual contract evidence; simulator-only coverage is labelled. Recovery objectives have a measured drill. Conditional disabled features have tested disabled/referral behavior and cannot accidentally activate. Owners approve remaining documented risks. The implementation status document, not this template, records actual progress.


## 12. Additional explicit preservation tests

| Test | Scenario | Expected result | Status |
| --- | --- | --- | --- |
| AT-X-01 | Failed visit recorded offline, then synchronized twice | One FAILED attempt, one visit-outcome receipt and one rescheduling obligation; case remains INSPECTION_PENDING. | NOT_RUN |
| AT-X-02 | Report and failed-visit operation race for same attempt | Only first valid fenced transaction commits; other is a structured conflict, never two terminal outcomes. | NOT_RUN |
| AT-X-03 | Policy passes simulation, then candidate changes | Old simulation cannot authorize approval of new candidate; a new run is required. | NOT_RUN |
| AT-X-04 | Temporary upload overwritten after completion | Accepted/scanned immutable object identity and content remain unchanged; new bytes cannot replace evidence. | NOT_RUN |
| AT-X-05 | Renderer restarted after verification token reservation | Same encrypted token is recoverable and produces the canonical URL; no new certificate or locator is issued. | NOT_RUN |

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
