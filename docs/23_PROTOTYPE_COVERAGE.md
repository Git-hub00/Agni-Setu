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

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
