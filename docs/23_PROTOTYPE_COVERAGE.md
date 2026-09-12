# Prototype-to-production coverage and interaction inventory

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Evidence basis and coverage meaning

The reference HTML was parsed as JavaScript and inspected for its named `actions` object and generated forms. The inventory contains **94 named action handlers and 20 distinct generated form IDs**. These are source-code inventory counts, not a claim that all browser combinations have been executed. Compound role/state combinations, checkbox change handlers and field validation still require the test matrix in document11.

A control marked REBUILD keeps the user purpose but replaces browser-local state with the documented backend contract. UI controls only change navigation/display. DEMO controls are confined to an isolated demo deployment. No raw prototype authorization, fixed OTP or direct local-state mutation is reused as production security.

## 2. Every named action

| Source action | Screen | Target contract | Disposition | Required behavior |
| --- | --- | --- | --- | --- |
| close-dialog | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| mobile-menu | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| personas | UI-28 | Normal login API after selecting fixture identity | DEMO | Demo-only persona chooser; actual server identity and role grants still enforced. |
| switch-role | UI-28 | Normal login API after selecting fixture identity | DEMO | Demo-only persona chooser; actual server identity and role grants still enforced. |
| demo-controls | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| about | UI-01, UI-28 | Static reference / demo navigation | DEMO/HELP | Explain product and open permitted demo workspace. Tour never grants authority. |
| tour | UI-01, UI-28 | Static reference / demo navigation | DEMO/HELP | Explain product and open permitted demo workspace. Tour never grants authority. |
| tour-go | UI-01, UI-28 | Static reference / demo navigation | DEMO/HELP | Explain product and open permitted demo workspace. Tour never grants authority. |
| refresh | Relevant active screen | Scoped GET for current route | UI | Refetch canonical data; display stale/failure time; do not lose an unsaved form. |
| search | UI-05 / shared shell | API-020 | UI | Scoped application query plus static permitted-route search. Never search unauthorized records. |
| notifications | UI-19 | API-078 | REBUILD | Open recipient-scoped update and authorized target; unread state is independent of delivery status. |
| read-notification | UI-19 | API-079 | REBUILD | Persist owner read marker once. |
| mark-all-read | UI-19 | API-080 | REBUILD | Mark only explicit current cutoff, not notifications received later. |
| open-notification | UI-19 | API-078 | REBUILD | Open recipient-scoped update and authorized target; unread state is independent of delivery status. |
| notification-detail | UI-19 | API-078 | REBUILD | Open recipient-scoped update and authorized target; unread state is independent of delivery status. |
| notification-filter | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| page | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| filter-tab | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| clear-filters | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| export-cases | UI-05, UI-22, UI-23 | API-082 | REBUILD | Require purpose and field/filter scope; create export job; reauthorize artifact access. |
| sample-details | UI-06, UI-08, UI-12 | Fixture-only data helpers | DEMO | Fill clearly labelled synthetic inputs. Real submission/evidence validation still runs. Never manufacture accepted real evidence. |
| sample-docs | UI-06, UI-08, UI-12 | Fixture-only data helpers | DEMO | Fill clearly labelled synthetic inputs. Real submission/evidence validation still runs. Never manufacture accepted real evidence. |
| sample-doc | UI-06, UI-08, UI-12 | Fixture-only data helpers | DEMO | Fill clearly labelled synthetic inputs. Real submission/evidence validation still runs. Never manufacture accepted real evidence. |
| draft-remove | UI-06 | API-037 | REBUILD | Detach only editable draft reference; accepted historical object remains immutable. |
| draft-preview | UI-06, UI-07, UI-12 | API-036 | REBUILD | Authorized private preview/download of exact scanned version; quarantined object cannot be opened as accepted evidence. |
| save-draft | UI-06 | API-023 | REBUILD | Versioned draft save; distinguish saved server draft from final receipt. |
| wizard-prev | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| wizard-jump | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| document-guide | UI-06 | Approved policy form/checklist read | UI | Display applicable document definitions with formats, limits and accessible help. |
| preview-doc | UI-06, UI-07, UI-12 | API-036 | REBUILD | Authorized private preview/download of exact scanned version; quarantined object cannot be opened as accepted evidence. |
| preview-evidence | UI-06, UI-07, UI-12 | API-036 | REBUILD | Authorized private preview/download of exact scanned version; quarantined object cannot be opened as accepted evidence. |
| download-doc | UI-06, UI-07, UI-12 | API-036 | REBUILD | Authorized private preview/download of exact scanned version; quarantined object cannot be opened as accepted evidence. |
| scrutiny | UI-07, UI-14 | API-027 | REBUILD | Acquire permitted scrutiny action; preserve accountable owner and clock. |
| routing | UI-07, UI-15 | API-028 | REBUILD | Reasoned scoped routing resolution; no arbitrary nearest-circle guess. |
| schedule | UI-11 | API-041 | REBUILD | Eligible officer, versioned booking, overlap constraint and notification. |
| reinspect | UI-14 | API-062 | REBUILD | Create new attempt linked to prior findings/report; do not overwrite old attempt. |
| schedule-week | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| request-info | UI-08 | API-054 | REBUILD | Publish itemized INFORMATION request with reason and policy response clock. |
| info-response | UI-08 | API-056 | REBUILD | Create per-item response revision with clean evidence; applicant cannot close findings. |
| finding-response | UI-08 | API-056 | REBUILD | Create per-item response revision with clean evidence; applicant cannot close findings. |
| modal-sample-file | UI-06, UI-08, UI-12 | Fixture-only data helpers | DEMO | Fill clearly labelled synthetic inputs. Real submission/evidence validation still runs. Never manufacture accepted real evidence. |
| accept-info | UI-08 | API-057 | REBUILD | Require every mandatory response item verified before return to scrutiny. |
| verify-finding | UI-08, UI-14 | API-060 | REBUILD | Record verified closure/return/reinspection need with authorized evidence and reason. |
| return-finding | UI-08, UI-14 | API-060 | REBUILD | Record verified closure/return/reinspection need with authorized evidence and reason. |
| return-review | UI-14 | API-061 | REBUILD | Exactly the prototype meaning: COMPLIANCE_PENDING to REVIEW_PENDING after mandatory finding closure. Not TR-14 report clarification. |
| decision | UI-14 | API-065 | REBUILD | Recheck state, authority, report and mandatory blockers under transaction; reasoned immutable decision. |
| issue | UI-16, UI-20 | API-105; API-104 | REBUILD | Open canonical issuance request already created by approval. Existing job can progress/retry only with permitted recovery authority; never create duplicate decision/certificate. |
| check-in | UI-12 | API-044 | REBUILD | Capture real available location/time or explicit unavailability reason; not proof of physical compliance. |
| practice-report | UI-06, UI-08, UI-12 | Fixture-only data helpers | DEMO | Fill clearly labelled synthetic inputs. Real submission/evidence validation still runs. Never manufacture accepted real evidence. |
| add-evidence | UI-12 | API-033; API-034 | REBUILD | Reserve/upload/scan exact bytes; update matching observation only when canonical CLEAN. |
| save-report | UI-12 | API-045 | REBUILD | Save draft online or visibly local offline. Draft does not enter review. |
| submit-report | UI-12 | API-047 | REBUILD | Complete versioned report with current assignment, evidence and declaration; offline uses sync contract. |
| toggle-offline | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| failed-visit | UI-12 | API-046; API-049 | REBUILD | Record online or offline failed visit with reason; preserve case and create owned rescheduling task. |
| sync-all | UI-13 | API-049 | REBUILD | Process each immutable report/failed-visit manifest independently with original IDs, upload readiness and current authority. |
| sync-one | UI-13 | API-049 | REBUILD | Process each immutable report/failed-visit manifest independently with original IDs, upload readiness and current authority. |
| sync-conflict | UI-13 | API-051 | REBUILD | Show local-versus-server versions and safe attributed proposal; no automatic overwrite. |
| rebase-sync | UI-13 | API-052 | REBUILD | Explicit reviewed rebase creates a NEW manifest/ID linked to old conflict after current checks. Do not edit accepted or submitted payload behind existing ID. |
| demo-conflict | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| scan | UI-15 | Periodic server scanner; scoped obligation refresh | UI/DEMO | Monitoring normally runs automatically. Preserve Refresh monitoring as read/recheck request, not browser authority over time or direct SQL scan. Demo scan uses allowlisted scenario. |
| monitor-tab | Shared shell / relevant screen | Client state; scoped GET after navigation | UI | Accessible focus, URL/filter state and guarded unsaved-draft handling. No business mutation. |
| clock-detail | UI-15 | API-075 | REBUILD | Show calendar, elapsed, pauses, threshold history and next responsible action. |
| manual-escalation | UI-15 | API-076 | REBUILD | Create reasoned intervention; does not itself satisfy the underlying work. |
| ack-escalation | UI-15 | API-077 | REBUILD | Record intervention owner/next action without completing regulatory stage. |
| retry-notification | UI-20 | API-105 | REBUILD | Use same logical job, preserve attempts and refuse blind retry of unknown irreversible effect. |
| retry-job | UI-20 | API-105 | REBUILD | Use same logical job, preserve attempts and refuse blind retry of unknown irreversible effect. |
| job-detail | UI-20 | API-104 | REBUILD | Show sanitized attempts, leases, failure and eligible recovery actions. |
| restore-providers | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| adapter-detail | UI-25 | API-107 | REBUILD | Show approved provider mode/health/ownership. Documentation preview is not a live integration. |
| external-details | UI-25 | API-107 | REBUILD | Show approved provider mode/health/ownership. Documentation preview is not a live integration. |
| print | UI-17 | API-069 | REBUILD | Authorize canonical sample/signed artifact. Print CSS preserves watermark and verification reference. |
| download-certificate | UI-17 | API-069 | REBUILD | Authorize canonical sample/signed artifact. Print CSS preserves watermark and verification reference. |
| copy | UI-17 | Client clipboard of authorized displayed verification URL | UI | Copy canonical nonsecret public locator with success/failure status; never private storage URL. |
| certificate-status | UI-17 | API-071 | REBUILD | Permitted signed/status instrument with reason and evidence; no arbitrary ACTIVE override. |
| export-report | UI-05, UI-22, UI-23 | API-082 | REBUILD | Require purpose and field/filter scope; create export job; reauthorize artifact access. |
| export-audit | UI-05, UI-22, UI-23 | API-082 | REBUILD | Require purpose and field/filter scope; create export job; reauthorize artifact access. |
| audit-detail | UI-23 | API-086 | REBUILD | Scope-check full event detail and redact secrets; events are not editable. |
| invite | UI-21 | API-088 | REBUILD | Approved access request and independently approved grants; no public privileged registration. |
| person-detail | UI-21 | API-087 | REBUILD | Open scoped roster profile and current grants/assignments, no identity secrets. |
| toggle-person | UI-21 | API-089; API-090 | REBUILD | Confirm reason; deactivation revokes current access and identifies pending work. Reactivation requires new approval, not old grants silently revived. |
| new-policy | UI-24 | API-096 | REBUILD | Create editable candidate/version lineage, not direct live configuration mutation. |
| policy-detail | UI-24 | API-097 | REBUILD | Show exact candidate, source references, pinned impact and review history. |
| edit-policy | UI-24 | API-098 | REBUILD | Only editable candidate with ETag and contributor attribution. |
| policy-simulate | UI-24 | API-123 | REBUILD | Run bounded server fixture suite against exact candidate hash; stale/failed results block approval. |
| submit-policy | UI-24 | API-099 | REBUILD | Freeze candidate hash and route independent review. |
| approve-policy | UI-24 | API-100; API-102 | REBUILD | Independent approval and explicit eligible activation; currently pinned cases do not migrate silently. |
| return-policy | UI-24 | API-101 | REBUILD | Attributed actionable return reason, immutable prior review history. |
| ticket | UI-26 | API-113; API-114 | REBUILD | Create/read scoped support record; only authorized staff can reply/resolve. |
| ticket-detail | UI-26 | API-113; API-114 | REBUILD | Create/read scoped support record; only authorized staff can reply/resolve. |
| withdraw | UI-07 | API-030 | REBUILD | Reasoned allowed-stage withdrawal under current profile; close associated work without erasing receipt. |
| advance-clock | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| export-snapshot | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| confirm-reset | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |
| reset | UI-28 | API-120 | DEMO | Allowlisted isolated demo scenarios; absent from live route registration. Confirm destructive reset; no public raw-state dump. |

## 3. Every generated form

| Source form ID | Screen | Input contract | Submit behavior |
| --- | --- | --- | --- |
| wizard-form | UI-06 | DraftCreate / DraftPatch / Submission | Save or submit according to explicit intent. Final receipt only after atomic submit. |
| verify-form | UI-18 | GET /public/certificates/{token} | Validate locator; unknown and unavailable differ; no PII. |
| auth-form | UI-02 | OtpStart / OtpVerify / OIDC callback | No role in submitted payload. Accessible resend/expiry/recovery. |
| schedule-form | UI-11 | ScheduleCommand / ReassignCommand | Eligible officer, time zone and interval, case/inspection version. |
| decision-form | UI-14 | DecisionCommand | Reason/public reason, report and acknowledgement; server guard list. |
| info-request-form | UI-08 | NoticeCreate | Itemized document/clarification requirement and policy-owned response deadline. |
| response-form | UI-08 | NoticeResponse | Per-item explanations plus accepted evidence and declaration. |
| verify-finding-form | UI-14 | FindingVerification | Evidence and attributable closure/return/reinspection decision. |
| policy-form | UI-24 | PolicyDraft / PolicyDraftPatch | Versioned typed fields with bounded enums, never executable code. |
| ticket-form | UI-26 | TicketCreate | Subject, type, narrative and optional readable case reference. |
| ticket-update-form | UI-26 | TicketMessage / TicketStatus | Publish response and move allowed support state; two canonical commands if needed, show partial completion safely. |
| export-form | UI-22 | ExportRequest | Purpose/filter/field scope and cutoff; async download reauthorization. |
| routing-form | UI-15 | RoutingResolution | Approved mapping and written reason, no heuristic unreviewed selection. |
| failed-visit-form | UI-12 | FailedVisit / SyncOperation RECORD_FAILED_VISIT | Reason, capture context and optional accepted evidence. Offline intent not a receipt. |
| escalation-form | UI-15 | EscalationCreate | Named owner, permitted level and useful reason/next action. |
| certificate-status-form | UI-17 | CertificateStatusCommand | Current action eligibility, reason, evidence, interval and successor where required. |
| invite-form | UI-21 | StaffInvitation | Approved identity/access request, finite grant scope; no self-approved elevation. |
| policy-approve-form | UI-24 | PolicyApproval | Exact candidate hash, successful simulation, independent actor and valid interval. |
| policy-return-form | UI-24 | Reason | Actionable review return, no mutable approval history. |
| withdraw-form | UI-07 | Reason | Current case ETag, reason and explicit irreversible-stage warning. |

## 4. Non-button interaction coverage

Search, filter inputs, page size, sort headers, date range, tab selection and calendar week changes update URL/local display state and refetch only scoped data. Form input change marks a draft dirty and never silently submits. File input triggers bounded reservation/upload and displays progress plus scan state. Checkbox declarations are never preselected; accessibility labels communicate each purpose. Demo provider/clock switches call only allowlisted demo controls. Normal user preferences persist through their own account settings contract.

Direct URLs, browser Back/Forward, reload, opening a new tab and deep links from notifications must have identical permission checks and canonical state. Case detail tabs include overview, documents, inspections, notices, timeline and certificate when applicable. Unauthorized tabs are not loaded. Breadcrumbs retain origin queue/filter, not a brittle fixed history count.

The source singular certificate URL `/certificate/:id` maps to the new canonical `/certificates/:id`; source `/portal`, `/login`, `/register` correspond to public entry, sign-in and account completion. Internal IDs are UUIDs, while AS-2026 references remain search/display keys. Inspection source URLs used case IDs; the new app resolves a real inspection-attempt UUID and does not confuse case and attempt identity. A reference-lookup redirect may aid demo navigation but must scope-check before revealing the target.

## 5. Explicit and intentional changes from browser mock behavior

The backend framework/database are deliberately reselected (ADR01/02), not copied from the old blueprint. A production role switcher is removed; actual identity determines workspace access. Fixed demo OTP, simulated GPS, instant CLEAN files and ordinary-browser sample signing remain nonproduction conveniences only. Real file scanning, accountable clocks, database locking and controlled job recovery replace browser writes.

The source conflict rebase edited an operation's base version in place. The production protocol creates a new immutable manifest linked to the old conflict after review; this is necessary for unambiguous idempotency. The source Issue button becomes progress/recovery of the issuance request already reserved by the accepted decision. It does not create a second certificate.

Baseline withdrawal is deliberately limited to the stages explicitly listed in the policy specification. The source prototype also offered withdrawal from REVIEW_PENDING. This more conservative initial policy is a visible engineering/demo choice pending agency approval, not a claim that law prohibits review-stage withdrawal. Add a reviewed policy capability and race tests before expanding it. Other unsupported legal features show a clear referral/disabled explanation, not a silently missing button.

Source report `return-review` means verified corrections return to REVIEW_PENDING; map it to complete-corrections. The newly specified report-clarification return is a separate command and initially always creates a physical reinspection. Offline failed visits remain supported and receive a distinct canonical visit-outcome receipt.

## 6. Visual parity contract

Use the exact prototype as the visual reference for navy navigation, orange primary action, neutral surfaces, readable status chips, tables, KPI cards, detail tabs, drawers and mobile field workspace. Document03 defines implementable tokens, dimensions, interaction states and accessibility. Capture baseline desktop 1440x900 and mobile 390x844 snapshots for each applicable role/screen; compare intent and hierarchy, not raster-perfect text wrapping across platforms. Record approved visual changes and never excuse a missing workflow as a styling choice.

Every source action has a disposition above. Every added production action must also be mapped to a capability, API, validation, error and test before implementation is called complete.

## 7. Implementation evidence (B19, 2026-09-12; baseline 2.0.0 build on `main`)

Recorded against the code on `main` after B18 (`6aa6967`) and the B19 acceptance run. Status values: **IMPLEMENTED** (route + server contract + automated or acceptance evidence), **PARTIAL** (server contract exists, the browser control is reduced or absent - stated), **REPLACED** (an intentional design change from s.5), **NOT_IMPLEMENTED** (with the reason and the current alternative). Evidence names the test module, smoke script (`scripts/dev/smoke_*.py`, all run by `scripts/dev/acceptance_run.py`) or browser spec (`web/e2e`). Routes are the SPA paths in `web/src/app/router.tsx`; API functions are in `web/src/api/*.ts`. Nothing below claims a live legal certificate, a real provider or government integration.

### 7.1 Named actions

| Source action | Implementation | Evidence | Status |
| --- | --- | --- | --- |
| close-dialog | Confirmation and command forms are inline disclosure panels with their own Cancel/close controls and focus management (no modal layer); unsaved wizard input is kept on the server draft | `web/e2e/*` axe + keyboard; vitest page tests | IMPLEMENTED (inline panels) |
| mobile-menu | `AppShell` header collapses to a workspace menu below 640 px; `nav[aria-label="Workspaces"]` | `web/e2e` 360/390 px overflow checks (B16), `journeys.spec.ts` | IMPLEMENTED |
| personas, switch-role | Real sign-ins only: applicant OTP through the demo inbox, staff through the local Keycloak realm personas (`arjun`, `meera`, `anita`, `suresh`, `priya`, ...); server role grants decide the workspaces | `smoke_identity.py`, `web/e2e/helpers.ts`, `tests/security/test_boundaries.py` | REPLACED (s.5: role switcher removed) |
| demo-controls, toggle-offline, demo-conflict, restore-providers, advance-clock, export-snapshot, confirm-reset, reset | No UI-28 demo console and no API-120. Available instead: `seed_demo --scenario baseline --require-demo` (idempotent, refuses non-demo databases), the demo inbox route (`GET /demo/inbox`, registered only with demo controls outside production), the injected test clock (`ClockPort`, tests only), offline behaviour driven by the browser's own connectivity, fault drills in `scripts/ops/`. Live mode has no such routes (proven by `prod_boot_check.py` B14 and `tests/unit/test_production_settings.py`) | status21 s.3u gap G-01 | NOT_IMPLEMENTED (demo console deferred; live packaging unaffected) |
| about, tour, tour-go | `HomePage` states the development/demo nature, links the workspaces and the public verification; no guided tour | `HomePage.test.tsx`, `public-a11y.spec.ts` | PARTIAL (no tour) |
| refresh | Every list/detail is a TanStack Query with refetch on focus and explicit Refresh buttons on lifecycle panels; stale/failed states rendered with the request id | vitest page tests (`ApplicationsListPage.test.tsx` DEPENDENCY_UNAVAILABLE), `CaseLifecycleActions` | IMPLEMENTED |
| search | `/applications?q=` URL-synced scoped query (`applicationsQuery`), server-side scope | `ApplicationsListPage.test.tsx`, `tests/integration/test_submission.py` AT-09 | IMPLEMENTED |
| notifications, open-notification, notification-detail | `/notifications` (`notificationsQuery`, API-078) with target links | `NotificationsPage.test.tsx`, `smoke_clocks.py`, `tests/integration/test_clocks.py` | IMPLEMENTED |
| read-notification | `markRead` (API-079) | same | IMPLEMENTED |
| mark-all-read | `readThrough(cutoff)` (API-080) - later notifications stay unread | same | IMPLEMENTED |
| notification-filter | unread-only toggle (`?unread_only=true`) | same | IMPLEMENTED |
| page | Cursor paging (`has_more` / `next_cursor` in the URL) instead of numbered pages | `ApplicationsListPage.tsx` | IMPLEMENTED (cursor variant) |
| filter-tab, clear-filters | URL-synced status filters and clear on `/applications`, `/inspections`, `/certificates`, `/monitoring`, `/audit` | vitest page tests | IMPLEMENTED |
| export-cases, export-report, export-audit | `/reports` `createExport` (API-082) with purpose, filters, cutoff and field set (`CASES/case-summary`, `CERTIFICATES/register`, `AUDIT/audit-summary`), worker-generated CSV with formula neutralisation, `requestExportAccess` re-authorised ticket (API-084), 24 h expiry | `tests/integration/test_reporting_audit.py`, `tests/unit/test_reporting_rules.py`, `smoke_reporting.py` | IMPLEMENTED |
| sample-details, sample-docs, sample-doc, modal-sample-file, practice-report | No fixture-fill buttons in the UI; synthetic inputs come from `seed_demo` and the smoke scripts (which generate labelled synthetic files) | `scripts/dev/smoke_drafts.py`, `smoke_reports.py` | NOT_IMPLEMENTED (demo convenience) |
| draft-remove | A requirement is satisfied by the newest CLEAN version; re-uploading supersedes the reference while every accepted version stays immutable. No detach control (API-037 not exposed) | `tests/integration/test_uploads.py`, `test_drafts.py` | PARTIAL |
| draft-preview, preview-doc, preview-evidence, download-doc | `requestDocumentAccess(PREVIEW/DOWNLOAD)` (API-036): audited, ticketed, quarantined versions refused | `test_uploads.py`, `smoke_drafts.py`, `tests/security/test_boundaries.py` | IMPLEMENTED |
| save-draft | `saveDraft` PATCH with `If-Match` + `draft_revision` (API-023); receipt only after submit | `test_drafts.py` AT-04, `smoke_drafts.py` | IMPLEMENTED |
| wizard-prev, wizard-jump | `ApplicationWizardPage` steps (service/premises, details/declarations, documents, review) with Back/Next and the step list | `journeys.spec.ts` (wizard route), wizard vitest | IMPLEMENTED |
| document-guide | Requirement list with formats/limits from the pinned policy in the wizard; `/applicant/premises` applicability check (API-020) | `test_applicability_routing_delegation.py`, `smoke_policy.py` | IMPLEMENTED |
| scrutiny | `startScrutiny` (API-027) | `test_case_commands.py`, `smoke_submission.py` | IMPLEMENTED |
| routing | `resolveRouting` (API-028) on the owned exception | `test_submission.py` AT-07, `smoke_submission.py` | IMPLEMENTED |
| schedule | `/schedule` window + `scheduleInspection` (API-041) with GiST overlap exclusion | `test_inspections.py` AT-08/11, `smoke_inspections.py` | IMPLEMENTED |
| reinspect | `requireReinspection` (API-062) - new attempt linked to findings | `test_notices.py` AT-17, `smoke_notices.py` | IMPLEMENTED |
| schedule-week | `scheduleQuery(startsAt, endsAt)` window navigation on `/schedule` | `SchedulePage.tsx`, `journeys.spec.ts` | IMPLEMENTED |
| request-info | `publishNotice` (API-054) itemised with policy response clock | `test_notices.py` AT-15, `smoke_notices.py` | IMPLEMENTED |
| info-response, finding-response | `submitResponse` + `uploadResponseEvidence` (API-056) per item, revisions never close findings | `test_notices.py` AT-16, `smoke_notices.py` | IMPLEMENTED |
| accept-info | `acceptInformation` (API-057) after every mandatory item reviewed | same | IMPLEMENTED |
| verify-finding, return-finding | `verifyFinding` (API-060) with reviewer-cited evidence | `test_notices.py` AT-17 | IMPLEMENTED |
| return-review | `completeCorrections` (API-061): COMPLIANCE_PENDING -> REVIEW_PENDING after mandatory closure | `test_notices.py`, `smoke_notices.py` | IMPLEMENTED |
| decision | `/applications/:id/review` `recordDecision` (API-065) behind `readinessQuery` guard list; authority grant + evidence snapshot + immutable rationale | `test_decisions.py` AT-20, `smoke_decisions.py` | IMPLEMENTED |
| issue | Approval reserves the issuance request; `/operations` `retryJob` / `reconcileJob` (API-105) act on the same logical job, refuse blind retry after UNKNOWN; `reconcile_issuance` command | `test_decisions.py` AT-21, `tests/faults/test_crash_after_remote_effect.py`, `smoke_decisions.py` | IMPLEMENTED (recovery semantics) |
| check-in | `checkIn` (API-044) with real location or explicit unavailability reason | `test_inspections.py`, `smoke_inspections.py` | IMPLEMENTED |
| add-evidence | `uploadFile(INSPECTION)` (API-033/034), CLEAN gate before the observation accepts it | `test_reports.py` AT-13, `smoke_reports.py` | IMPLEMENTED |
| save-report | `saveReportDraft` (API-045) online; Dexie local save offline (visibly local) | `test_reports.py`, `web/src/offline/sync.test.ts`, `smoke_offline.py` | IMPLEMENTED |
| submit-report | `submitReport` (API-047) with current assignment, evidence and declaration; offline through `postSyncOperation` | `test_reports.py`, `test_sync.py` AT-12, `smoke_reports.py` | IMPLEMENTED |
| failed-visit | `failVisit` (API-046) online; `RECORD_FAILED_VISIT` sync operation offline (API-049) | `test_inspections.py` AT-11, `test_sync.py`, `smoke_offline.py` | IMPLEMENTED |
| sync-all, sync-one | `/sync` processes each frozen manifest with its original `operation_id` (API-049), receipts by `fetchSyncReceipt` | `test_sync.py`, `sync.test.ts`, `smoke_offline.py` | IMPLEMENTED |
| sync-conflict | `proposeConflict` (API-051) shows local vs server; no overwrite | same | IMPLEMENTED |
| rebase-sync | `resolveConflict(PROPOSE_NEW_REPORT)` creates a NEW manifest id linked to the conflict (API-052) | same | IMPLEMENTED |
| scan | `/monitoring` refresh reads scoped obligations; the server scheduler (`run_schedulers`) owns the scan; no browser authority over time | `test_clocks.py` AT-18/19, `smoke_clocks.py` | IMPLEMENTED (read/recheck only) |
| monitor-tab | `/monitoring` urgency/state filters ("Monitoring tabs") | `MonitoringPage` vitest | IMPLEMENTED |
| clock-detail | `obligationQuery` (API-075): calendar, elapsed, pauses, thresholds, next action | `test_clocks.py`, `smoke_clocks.py` | IMPLEMENTED |
| manual-escalation | `createEscalation` (API-076) | same | IMPLEMENTED |
| ack-escalation | `acknowledgeEscalation` (API-077) | same | IMPLEMENTED |
| retry-notification, retry-job | `retryJob` (API-105): same logical job, attempts preserved, UNKNOWN refused | `test_reporting_audit.py` (recovery), `tests/faults`, `smoke_reporting.py` | IMPLEMENTED |
| job-detail | `/operations` job rows with sanitised attempts, lease, failure code and eligible actions (API-104) | `OperationsPage` vitest, `smoke_clocks.py` | IMPLEMENTED |
| adapter-detail, external-details | `/integrations` `integrationQuery` (API-107) mode/health/ownership + allowlisted `testIntegration` probe (API-108) | `test_integrations.py`, `smoke_integrations.py` | IMPLEMENTED |
| print | No print action or print stylesheet; the sample PDF (download) carries the watermark and verification reference | - | NOT_IMPLEMENTED |
| download-certificate | `requestCertificateAccess` (API-069) ticketed artifact | `test_decisions.py`, `smoke_decisions.py` | IMPLEMENTED |
| copy | Verification URL displayed and linkable on `/certificates/:id`; no clipboard button | - | NOT_IMPLEMENTED |
| certificate-status | `recordStatusAction` (API-071) suspend/reinstate/revoke instruments with reason + evidence | `test_lifecycle.py` AT-24, `smoke_lifecycle.py` | IMPLEMENTED |
| audit-detail | `/audit` `auditEventQuery` (API-086) scoped, redacted, the read itself audited | `test_reporting_audit.py` AT-28, `smoke_reporting.py` | IMPLEMENTED |
| invite | No self-service invitation form. Staff identities come from the OIDC realm and `provision_demo_staff`; authority is granted through `proposeGrant` -> independent `approveGrant` (API-088/091) on `/team`; reactivation needs an approved access request id | `test_grants_and_provisioning.py` AT-02, `smoke_reporting.py` | PARTIAL |
| person-detail | `/team` roster with current grants and pending proposals (API-087) | same | IMPLEMENTED |
| toggle-person | `deactivateStaff` (revokes grants, bumps epoch) / `reactivateStaff` (API-089/090) with reason | `test_grants_and_provisioning.py`, `test_sessions.py`, `smoke_reporting.py` | IMPLEMENTED |
| new-policy, edit-policy | API-096/098 exist and are exercised (`smoke_policy.py` creates and patches a candidate; `test_policy_governance.py`), but `/policy` offers detail + governance commands only - no create/edit form | `test_policy_governance.py` AT-27, `smoke_policy.py` | PARTIAL (API only) |
| policy-detail | `/policy/:id` `policyDetailQuery` (API-097) | same, `journeys.spec.ts` | IMPLEMENTED |
| policy-simulate, submit-policy, approve-policy, return-policy | `runPolicyCommand` simulate / submit / approve + activate / return (API-123/099/100+102/101) with SoD and stale-candidate refusal | `test_policy_governance.py`, `smoke_policy.py` | IMPLEMENTED |
| ticket, ticket-detail | `/support` `createTicket`, `/support/:id` `addTicketMessage` (REQUESTER/INTERNAL), `changeTicketStatus` (API-113/114) | `test_lifecycle.py` AT-30, `smoke_lifecycle.py` | IMPLEMENTED |
| withdraw | `withdrawApplication` (API-030) allowed stages only, ETag + reason | `test_lifecycle.py`, `smoke_lifecycle.py` | IMPLEMENTED |

Totals for the 94 named actions: IMPLEMENTED 71, PARTIAL 6 (`about/tour/tour-go` counted as 3, `draft-remove`, `invite`, `new-policy`/`edit-policy` counted as 2 -> see rows), REPLACED 2, NOT_IMPLEMENTED 15 (8 demo-console controls, 5 fixture-fill helpers, `print`, `copy`). Every NOT_IMPLEMENTED item is a demonstration convenience or a client-side nicety; no regulatory command is missing.

### 7.2 Generated forms

| Source form ID | Implementation | Evidence | Status |
| --- | --- | --- | --- |
| wizard-form | `ApplicationWizardPage`: `saveDraft` per step, `submitApplication` (API-024) only from the review step with declarations | `test_drafts.py`, `test_submission.py`, `smoke_submission.py` | IMPLEMENTED |
| verify-form | `/verify` -> `publicVerificationQuery` (API-073): unknown vs unavailable distinct, no PII, rate-limited | `test_decisions.py` AT-22, `tests/security`, `public-a11y.spec.ts`, `journeys.spec.ts` | IMPLEMENTED |
| auth-form | `SignInPage`: OTP start/verify, staff OIDC link; no role in payload | `test_otp_sign_in.py` AT-01, `test_oidc_and_scope.py`, `web/e2e/helpers.ts` | IMPLEMENTED |
| schedule-form | `SchedulePage` / inspection detail: officer, interval, `application_version`, `If-Match` | `test_inspections.py`, `smoke_inspections.py` | IMPLEMENTED |
| decision-form | `ReviewPage`: outcome, reason, public reason, acknowledgement; server guard list | `test_decisions.py`, `smoke_decisions.py` | IMPLEMENTED |
| info-request-form | `CaseNotices` publish form (items, deadline from policy) | `test_notices.py`, `smoke_notices.py` | IMPLEMENTED |
| response-form | `NoticePage` per-item explanation + evidence upload + declaration | same | IMPLEMENTED |
| verify-finding-form | `ReviewPage` finding verification with evidence citation | same | IMPLEMENTED |
| policy-form | Server contract (`PolicyDraft` / patch) exercised through the API; no browser form (see `new-policy`) | `test_policy_governance.py`, `smoke_policy.py` | PARTIAL (API only) |
| ticket-form | `SupportPage` create ticket (subject, type, narrative, optional case) | `test_lifecycle.py`, `smoke_lifecycle.py` | IMPLEMENTED |
| ticket-update-form | `SupportTicketPage` message + status as two commands with visible partial completion | same | IMPLEMENTED |
| export-form | `ReportsPage` purpose / filters / field set / cutoff | `test_reporting_audit.py`, `smoke_reporting.py` | IMPLEMENTED |
| routing-form | Routing exception resolution on the case (approved mapping + reason) | `test_submission.py` AT-07, `smoke_submission.py` | IMPLEMENTED |
| failed-visit-form | Inspection detail online form + offline `RECORD_FAILED_VISIT` | `test_inspections.py`, `test_sync.py`, `smoke_offline.py` | IMPLEMENTED |
| escalation-form | `MonitoringPage` (owner, level, reason, next action) | `test_clocks.py`, `smoke_clocks.py` | IMPLEMENTED |
| certificate-status-form | `CertificateDetailPage` status dialog (action eligibility, reason, evidence, interval) | `test_lifecycle.py`, `smoke_lifecycle.py` | IMPLEMENTED |
| invite-form | Grant proposal form on `/team` (finite scope, independent approval); no identity invitation | `test_grants_and_provisioning.py`, `smoke_reporting.py` | PARTIAL |
| policy-approve-form | `/policy/:id` approve with reason against the exact candidate hash + simulation | `test_policy_governance.py`, `smoke_policy.py` | IMPLEMENTED |
| policy-return-form | `/policy/:id` return with reason (immutable review history) | same | IMPLEMENTED |
| withdraw-form | `CaseLifecycleActions` withdraw with reason, ETag and stage warning | `test_lifecycle.py`, `smoke_lifecycle.py` | IMPLEMENTED |

Totals for the 20 forms: IMPLEMENTED 18, PARTIAL 2 (`policy-form`, `invite-form`).

### 7.3 Non-button interaction coverage (s.4) - evidence

URL-synced filters/paging (`/applications`, `/audit`, `/monitoring`), direct URLs / reload / deep links with server-side permission checks (`journeys.spec.ts`, `applicant-a11y.spec.ts` deep link to another applicant's case -> scoped error), file input -> reservation/upload/scan state (`smoke_drafts.py`, `test_uploads.py`), declarations never preselected (`test_submission.py` AT-06-02), `/certificate/:id` singular alias is not implemented (canonical `/certificates/:id` only), reference lookup by AS-2026 display key through `/applications?q=`.

### 7.4 Visual parity (s.6)

Not executed as pixel/snapshot comparison. Tokens and layout follow `docs/03`; the browser suite asserts accessibility, headings, no horizontal overflow at 360-1440 px and CSP cleanliness. Snapshot capture at 1440x900 / 390x844 per role remains an open B20 item.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
