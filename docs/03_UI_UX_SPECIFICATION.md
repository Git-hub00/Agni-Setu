# UI/UX design system and screen behavior specification

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Design intent and source fidelity

Preserve the supplied HTML prototype's calm administrative design: white navigation, very light gray canvas, dark navy text, burnt-orange primary action, restrained status colors and generous card spacing. The production build must preserve the information architecture, seven workspaces and meaningful interactions, not the prototype's browser-only persistence or role-switch impersonation.

A deliberate accessibility refinement is larger production typography and controls. The prototype contains small text appropriate to a compact demonstration; do not copy tiny labels into a citizen service. All design changes described here are engineering/UX requirements for the new implementation, not claims that they were already tested in the source HTML.

## 2. Tokens and geometry

```css
:root {
  --color-ink: #182b3b;
  --color-muted: #687786;
  --color-canvas: #f5f7f9;
  --color-surface: #ffffff;
  --color-border: #e3e8ed;
  --color-primary: #bd4525;
  --color-primary-hover: #a7391c;
  --color-primary-soft: #fcf0e9;
  --color-positive: #176e5b;
  --color-positive-soft: #edf7f3;
  --color-information: #376aab;
  --color-information-soft: #eef4fc;
  --color-danger: #b63745;
  --color-danger-soft: #fff0f1;
  --color-warning: #936011;
  --color-warning-soft: #fff7e7;
  --radius-card: 12px;
  --sidebar-width: 232px;
  --shadow-card: 0 6px 24px rgba(28,45,64,.06);
}
```

Use locally hosted properly licensed Inter or system sans-serif fallback; Noto Sans Devanagari may support reviewed Hindi content. Do not depend on a third-party font request for a private case screen. Body 16 px; compact table text minimum 14 px; supporting labels minimum 12 px and tested contrast. Page headings 28-32 px desktop, 24 px mobile. Use a 4/8/12/16/24/32 spacing scale. Buttons have at least 44 px target height as a product design target; this is not a claim that every WCAG AA control has a 44 px statutory minimum.

Desktop >=1200 px uses the 232 px sidebar, 64 px top bar and content padded 32 px with max width 1560 px. Tablet 768-1199 collapses secondary panels; narrow/mobile <=767 uses an accessible drawer, 16 px content padding and stacked cards. Test 360, 390, 768, 1280 and 1440 px viewport widths; no page-level horizontal overflow. Data tables may have an explicitly labelled horizontal region only when a meaningful mobile card alternative is impossible.

Verify actual foreground/background pairs against WCAG 2.2 AA rather than assuming the palette alone guarantees compliance. Use a visible focus ring and do not remove outlines. Status uses text and an icon as well as color. Subtle border color alone is not sufficient for a required input boundary if contrast fails.

## 3. Application shell and navigation

```text
+----------------------+-------------------------------------------------+
| Agni Setu            | Breadcrumb / page context   Alerts   Profile    |
| Current workspace    +-------------------------------------------------+
|                      | Page title + concise next-task explanation      |
| Primary navigation   | Filters / primary action                        |
|                      |                                                 |
| Secondary navigation | Main content / table / form      Task summary   |
|                      |                                                 |
| Help / mode label    | Last updated / next safe action                 |
+----------------------+-------------------------------------------------+
```

Sidebar groups match the prototype: Work, Governance and Help, with labels appropriate to the active workspace. Applicant uses My applications, New application, Premises, Certificates and Notifications. Officer uses Inspections, Schedule, Assigned cases and Sync. Supervisor uses Overview, Applications, Inspections, Reviews, Monitoring, Certificates and Reports. Leadership has read-only oversight. Admin uses Operations, Integrations, Team, Policies and Audit. Policy approver uses Policies and Audit. Public users have no staff sidebar.

The workspace selector lists only workspaces actually granted to the current identity. It does not change identity or grant a role. The prototype's Switch workspace demo impersonation is isolated to the demo environment. Every deep route is checked server-side and route-side. Unknown route shows a useful 404 with an authorized home link, not a blank page.

## 4. Reusable interaction contracts

| Component | Required behavior |
| --- | --- |
| Page header | One clear title, short description and at most one visually dominant primary action. |
| Status chip | Human label, icon, accessible text and consistent state mapping; technical code available in details only. |
| Table | Semantic headers, visible sort direction, stable pagination, keyboard-accessible row action, explicit empty/error/loading states. |
| Search | Debounced cancellable request; late results cannot replace newer query; filters encoded in URL. |
| Form field | Visible label, unit/example, required indicator, help text and associated error; no placeholder-only labels. |
| Dialog | Focus trap, meaningful title, Escape/cancel where safe, initial focus, return focus to initiator, no background scroll. |
| Confirmation | Specific action/object/impact, reason where needed; destructive button not auto-focused; no vague Are you sure only. |
| Toast | Supplementary confirmation only; important errors/receipts also remain in page content. |
| Upload row | Progress, cancel/retry, scan state, file size/type and accepted version; progress is not evidence acceptance. |
| Async job | Accepted state, stable job link, last attempt, retry/reconcile policy and final canonical artifact. |
| Error summary | Focusable heading with links to invalid fields; preserve valid input; no raw exception or silent reset. |
| Read-only field | Text or clearly read-only control; do not look editable when no save action exists. |
| Skeleton | Reserve final layout, aria-busy as needed; no flashing synthetic zero values. |
| Offline banner | Connectivity, last sync, local changes and explicit Sync now. Browser online event alone is not server reachability. |
| Audit/history | Immutable chronological explanation, actors and versions with audience filtering. |

## 5. Screen catalogue

| Screen | Route | Name | Access | Requirements |
| --- | --- | --- | --- | --- |
| UI-01 | / | Public service entry | Public | FR-03, FR-22 |
| UI-02 | /sign-in | Applicant OTP / staff sign-in | Public | FR-01, FR-02 |
| UI-03 | /account | Account, contacts and delegations | Authenticated | FR-01, FR-10 |
| UI-04 | /premises | Premises and authorized representatives | Applicant | FR-03, FR-10 |
| UI-05 | /applications | Application list and saved filters | Applicant, Officer, Supervisor, Leadership | FR-04, FR-09, FR-26 |
| UI-06 | /applications/new and /applications/:id/edit | Application wizard | Applicant / representative | FR-03, FR-04, FR-05, FR-06 |
| UI-07 | /applications/:id | Case detail, evidence and timeline | Scoped readers | FR-09, FR-20, FR-30 |
| UI-08 | /applications/:id/notices/:noticeId | Information and deficiency responses | Applicant / scoped reviewer | FR-15, FR-16, FR-17 |
| UI-09 | /overview | Role-specific overview | Applicant, Supervisor, Leadership | FR-07, FR-09, FR-25 |
| UI-10 | /inspections | Assigned and supervised inspection queue | Officer, Supervisor | FR-08, FR-11 |
| UI-11 | /schedule | Appointment calendar and assignment dialog | Officer, Supervisor | FR-08, FR-11 |
| UI-12 | /inspections/:id | Inspection workspace and report | Assigned officer / scoped reader | FR-05, FR-11, FR-12, FR-13, FR-14 |
| UI-13 | /sync | Offline work and conflict resolution | Officer | FR-12, FR-13 |
| UI-14 | /reviews and /applications/:id/review | Evidence review and decision | Supervisor with authority | FR-14, FR-15, FR-17, FR-20 |
| UI-15 | /monitoring | Obligations, exceptions and escalation | Supervisor, Leadership | FR-18, FR-19, FR-24, FR-25 |
| UI-16 | /certificates | Certificate register | Scoped readers | FR-21, FR-24 |
| UI-17 | /certificates/:id | Certificate details and lifecycle | Holder / authority / scoped reader | FR-21, FR-24 |
| UI-18 | /verify and /verify/:token | Public verification result | Public | FR-22 |
| UI-19 | /notifications | Personal notifications and preferences | Authenticated | FR-19, FR-23 |
| UI-20 | /operations | Jobs, delivery failures and recovery | Operations administrator | FR-19, FR-23, FR-29 |
| UI-21 | /team | Staff, grants and assignment availability | Admin / supervisor scoped view | FR-02, FR-08 |
| UI-22 | /reports | Metrics, reports and export jobs | Supervisor, Leadership | FR-25, FR-26 |
| UI-23 | /audit | Audit event search and details | Scoped auditor | FR-26, FR-28 |
| UI-24 | /policies and /policies/:id | Policy versions, review and activation | Admin, Policy approver, scoped readers | FR-03, FR-27 |
| UI-25 | /integrations | Provider configuration and reconciliation | Operations administrator | FR-29 |
| UI-26 | /support and /support/:id | Help, tickets, referrals and permitted appeals | Authenticated; public help only | FR-30 |
| UI-27 | /settings | Personal and permitted operational settings | Authenticated | FR-01, FR-23 |
| UI-28 | /demo | Demonstration controls and walkthrough | Demo-only authorized operator | FR-12, FR-19, FR-29 |

### UI-01 - Public service entry

**Route:** `/`. **Access:** Public. **Requirements:** FR-03, FR-22.

**Layout and information:** A restrained public service page with an Agni Setu wordmark, a DEMONSTRATION banner in demo deployments, a short explanation of the service and two dominant actions: Apply / track and Verify certificate. Below: supported services, the application journey and help. No fabricated government emblem or guarantee of fire safety.

**Actions and navigation:** Apply / track opens sign-in with a safe return path; Verify opens UI-18; service cards show enabled categories and a concise eligibility caveat; Help opens public support guidance.

**Errors and edge behavior:** Disabled service cards explain why applications are unavailable. A failed service-catalog request shows unavailable, not an empty assertion that no service exists. Public entry must not reveal private staff navigation.

### UI-02 - Applicant OTP / staff sign-in

**Route:** `/sign-in`. **Access:** Public. **Requirements:** FR-01, FR-02.

**Layout and information:** Two clearly labelled sign-in choices: Applicant sign-in and Staff sign-in. Applicant form has country/contact input, Send code, six-digit code, masked destination, expiry countdown and resend cooldown. Staff button redirects to the configured OIDC provider. Never ask users to choose a privileged role.

**Actions and navigation:** Send code validates contact then requests a challenge. Verify sends challenge ID and code with CSRF. Successful authentication redirects to the intended authorized route or the workspace home. Back/change contact cancels the pending challenge context.

**Errors and edge behavior:** Codes are never displayed in live UI or logs. A local demo inbox may reveal synthetic messages only on an isolated development surface. Invalid/expired code has a generic error; provider failure shows retry and reference ID. Preserve return route only if relative and allowlisted.

### UI-03 - Account, contacts and delegations

**Route:** `/account`. **Access:** Authenticated. **Requirements:** FR-01, FR-10.

**Layout and information:** Account page groups verified contact, display name, language, active sessions where enabled and delegations. Delegation cards state beneficiary, scope, expiry and revocation state. A contact badge says Contact verified, not Identity or ownership certified.

**Actions and navigation:** Edit permitted profile fields; request verified contact change; propose/confirm/revoke delegated access; sign out. Staff cannot alter their own service powers here.

**Errors and edge behavior:** Contact changes require step-up and verification. Revocation shows the affected scope and warning that already submitted history remains. Unsynchronized officer work triggers the approved logout warning; cancel retains session, confirmed logout locks/purges according to device policy.

### UI-04 - Premises and authorized representatives

**Route:** `/premises`. **Access:** Applicant. **Requirements:** FR-03, FR-10.

**Layout and information:** Premises cards/table with name, address/locality, category and relationship to current user. Detail drawer distinguishes the editable master from snapshots already submitted. New premises uses defined units and text hints.

**Actions and navigation:** Create or update an authorized premises; choose it for a new application; inspect delegation scope; view linked cases. Saved master changes do not change past submissions.

**Errors and edge behavior:** Empty state invites Add premises. Similar premises trigger a possible-duplicate warning, not automatic merging. Missing delegation disables Apply for this premises and links to the delegation process.

### UI-05 - Application list and saved filters

**Route:** `/applications`. **Access:** Applicant, Officer, Supervisor, Leadership. **Requirements:** FR-04, FR-09, FR-26.

**Layout and information:** Page title, concise subtitle, primary New application for eligible applicants, search by visible reference/premises, status and date filters. Columns: reference, premises/category, current task/status, responsible unit, due/freshness and last update. Desktop row opens detail; mobile uses stacked cards with the same fields.

**Actions and navigation:** Search updates URL after a 300 ms debounce; filter chips can be removed individually; Clear filters restores default; pagination preserves filters; Export creates a scoped asynchronous job; row click and explicit View both open UI-07. DRAFT rows offer Continue, not a certificate action.

**Errors and edge behavior:** No results has Clear filters; true empty list has New application if permitted. Loading uses stable skeleton rows. Failed load retains filter and shows retry, not zero cases. Leadership has no creation/edit controls, even if manually navigating to the wizard.

### UI-06 - Application wizard

**Route:** `/applications/new and /applications/:id/edit`. **Access:** Applicant / representative. **Requirements:** FR-03, FR-04, FR-05, FR-06.

**Layout and information:** Four-step wizard: Service and premises; Details and declarations; Documents; Review and submit. Left/upper stepper indicates complete/current/blocked steps. Desktop form max-width 920 px with requirements side panel; mobile one column. Sticky bottom actions: Back, Save and exit, Next / Submit. Display saved-at and local-unsaved indicators.

**Actions and navigation:** Create draft on the first successful server save. Autosave after 800 ms of settled valid edits and on explicit save; serialize saves to prevent stale out-of-order writes. Upload rows show filename, size, progress, scanning, accepted/rejected and Replace/Remove where permitted. Review includes a frozen preview, declared actor/beneficiary and current policy label. Submit confirms and opens receipt/detail after canonical success.

**Errors and edge behavior:** Next validates the current step; Submit validates the entire draft server-side. Upload failure preserves other data. Missing clean required files disable submit with item links. A profile change before submission refreshes requirements and requires another review. No success screen on timeout; offer Check submission / Retry safely. Never autosave a regulatory transition.

### UI-07 - Case detail, evidence and timeline

**Route:** `/applications/:id`. **Access:** Scoped readers. **Requirements:** FR-09, FR-20, FR-30.

**Layout and information:** Case header shows reference, premises, status, received date and current next action. Main tabs: Summary, Documents, Inspections, Notices and responses, Timeline, Outcome. Right rail or mobile summary panel shows accountable unit, clock basis and permitted actions. Internal audit and public timeline remain separate.

**Actions and navigation:** Open files through authorized access; navigate to a notice, report or outcome; download receipt; permitted supervisor can start scrutiny, resolve routing, request visit, open review or add a hold. Applicant may withdraw only where allowed; action opens a reasoned confirmation. All actions refresh the canonical case and timeline.

**Errors and edge behavior:** A stale version banner blocks unsafe pending commands until refreshed. A missing resource uses the same not-found screen as unauthorized scope. Internal notes never appear for applicants. Closed cases remain readable but no longer editable. The public certificate action is a separate privacy-safe route.

### UI-08 - Information and deficiency responses

**Route:** `/applications/:id/notices/:noticeId`. **Access:** Applicant / scoped reviewer. **Requirements:** FR-15, FR-16, FR-17.

**Layout and information:** Notice header explains Information required or Corrections required, published reason, deadline basis and response status. Each item has requirement, accepted evidence types, current response history and reviewer feedback. Two-column reviewer view compares required evidence with response; applicant gets a linear task list.

**Actions and navigation:** Applicant uploads accepted evidence and submits new item responses; reviewer accepts/returns items and records findings verification; a separate Accept information or Complete corrections action is available only when all required guards pass. Reinspection opens an attempt dialog.

**Errors and edge behavior:** Returned items retain prior replies. Superseded notices link to the current notice and disallow response. Missing scan/evidence keeps the response unsubmitted. The status Response received must never be styled as Verified closed. An appeal is not offered as the name of a deficiency response.

### UI-09 - Role-specific overview

**Route:** `/overview`. **Access:** Applicant, Supervisor, Leadership. **Requirements:** FR-07, FR-09, FR-25.

**Layout and information:** Role-specific overview. Applicant: My open applications, Action required, Upcoming visits and certificates. Supervisor: Received/open count, Due soon, Overdue, Review waiting; below, priority work and latest events. Leadership: the same aggregate definitions with jurisdiction filters and read-only drill-downs.

**Actions and navigation:** KPI cards navigate to UI-05 or UI-15 with exact applied filters; due/review rows open the case/obligation; Refresh shows last successful update. The walkthrough appears only in demo.

**Errors and edge behavior:** KPI counts and row totals use the same cutoff/filter population. Do not use different live calls that make the same screen disagree. A reporting failure shows unavailable; prior data can remain with Stale as of timestamp. Applicant sees only their own records.

### UI-10 - Assigned and supervised inspection queue

**Route:** `/inspections`. **Access:** Officer, Supervisor. **Requirements:** FR-08, FR-11.

**Layout and information:** Inspection queue with Today / Upcoming / Overdue / Unassigned / Completed filters appropriate to role. Cards show appointment, locality, purpose, case reference, checklist readiness, assignment version and due target. Officer home favors large touch controls over wide dense tables.

**Actions and navigation:** Open inspection; download offline package while online; Start visit when allowed; supervisors can schedule/reassign. Filter state persists in URL. A map is optional and disabled with explanation if the approved provider is absent.

**Errors and edge behavior:** An unavailable officer or scheduling conflict is actionable, not hidden. A completed/failed attempt opens read-only history. A package download needs current authority and displays expiry; no promise of indefinite offline availability.

### UI-11 - Appointment calendar and assignment dialog

**Route:** `/schedule`. **Access:** Officer, Supervisor. **Requirements:** FR-08, FR-11.

**Layout and information:** Accessible agenda/week view with day navigation, current timezone and officer filter. Every booking also appears in an equivalent list for keyboard/screen-reader users. Scheduling drawer contains officer, start/end, reason, required constraints and notification preview.

**Actions and navigation:** Select date, move week, create or reschedule an unstarted attempt, reassign with reason, cancel and create next action. Save performs server conflict checks, then updates calendar and case.

**Errors and edge behavior:** Conflicting appointments highlight the conflicting interval without exposing out-of-scope case details. No drag-and-drop-only operation. Cancellation cannot silently erase the original attempt. Browser local timezone cannot shift appointments without the service timezone label.

### UI-12 - Inspection workspace and report

**Route:** `/inspections/:id`. **Access:** Assigned officer / scoped reader. **Requirements:** FR-05, FR-11, FR-12, FR-13, FR-14.

**Layout and information:** Mobile-first inspection workspace: case/attempt summary, online/offline badge, assignment and package freshness, progress through eight demo checklist items, then report summary. Each item has PASS/FAIL/NOT_VERIFIED/allowed NA, observation notes and evidence rows. Bottom action bar: Save draft and Submit report. Failed visit is a separate secondary action.

**Actions and navigation:** Check in records optional GPS or unavailability reason; add evidence via camera/file picker; save local or server draft with explicit destination; submit validates required items, uploads, assignment and case versions. Accepted report opens a read-only receipt with server revision.

**Errors and edge behavior:** Camera/GPS denied has a permitted manual reason path, not fake coordinates. Mandatory NA requires policy permission and reason. Offline submit queues a local operation only and says Not yet received by server. Stale assignment shows a conflict screen, not silent overwrite. Only demo has Fill practice report.

### UI-13 - Offline work and conflict resolution

**Route:** `/sync`. **Access:** Officer. **Requirements:** FR-12, FR-13.

**Layout and information:** Synchronization center groups Not uploaded, Waiting for scan, Ready to submit, Conflicts and Accepted. Each operation shows case/attempt, captured time, package/assignment version, local evidence size, last attempt and canonical receipt if accepted.

**Actions and navigation:** Sync now or Sync this operation refreshes session and sequentially processes uploads then manifest. Open conflict shows local and server facts side by side; propose rebase/new report or discard only with explicit confirmation. Approved recovery can export an encrypted package only when implemented and permitted.

**Errors and edge behavior:** Manual sync always exists; background sync is optional. Never show Success before a receipt. Storage quota/eviction warnings explain limitations. Revoked authority locks submission and requires supervisor recovery; no browser button can reinstate it.

### UI-14 - Evidence review and decision

**Route:** `/reviews and /applications/:id/review`. **Access:** Supervisor with authority. **Requirements:** FR-14, FR-15, FR-17, FR-20.

**Layout and information:** Review queue sorted by due action, then receipt age. Review page has submission summary, report/evidence viewer, itemized findings, correspondence, policy basis and Decision readiness. A sticky decision panel shows blockers, authority scope and reason fields.

**Actions and navigation:** Return for clarification; publish deficiencies; verify corrections; require reinspection; record Approve or Reject through a confirmation summarizing evidence versions and public reason. User must explicitly acknowledge the review summary; no preselected approval.

**Errors and edge behavior:** Approval stays disabled for mandatory fail/unverified/evidence/authority blockers. Backend still rechecks. A conflict reloads changed evidence and requires renewed review. Technical admin cannot access decision controls. Successful approval displays certificate processing, not certificate issued.

### UI-15 - Obligations, exceptions and escalation

**Route:** `/monitoring`. **Access:** Supervisor, Leadership. **Requirements:** FR-18, FR-19, FR-24, FR-25.

**Layout and information:** Monitoring page has tabs Due soon, Overdue, Routing exceptions, Unassigned, Escalations and Paused. Rows show obligation type, owner, clock basis, start, due/paused state, elapsed age, last meaningful action and next step. Clock drawer shows budget, calendar and pause timeline.

**Actions and navigation:** Open case/clock; acknowledge intervention; create manual escalation with reason; resolve route/assignment through their actual commands. Leadership can inspect but not intervene. Advanced authorized hold controls explicitly list affected obligations.

**Errors and edge behavior:** Acknowledged is not resolved. Paused clocks remain visible with reason and authorization, while independent case age continues. Worker or email failures appear as dependencies, not excuses to erase overdue counts. A manual refresh cannot advance demonstration time except on UI-28.

### UI-16 - Certificate register

**Route:** `/certificates`. **Access:** Scoped readers. **Requirements:** FR-21, FR-24.

**Layout and information:** Register distinguishes Published certificates, Pending issuance and Historical/invalid status. Show certificate number, premises, outcome kind, issue/validity dates and effective status. A visible DEMONSTRATION column/badge persists in demo exports.

**Actions and navigation:** Open detail; download allowed artifact; start a permitted renewal; supervisor may inspect pending issuance job. Search by exact visible certificate number or authorized premises.

**Errors and edge behavior:** Do not list a reserved number as an issued active instrument. Pending issuance cards explain the dependency and last job update. Applicant cannot see other holders. Table failure must not imply a certificate has been revoked.

### UI-17 - Certificate details and lifecycle

**Route:** `/certificates/:id`. **Access:** Holder / authority / scoped reader. **Requirements:** FR-21, FR-24.

**Layout and information:** Certificate detail shows status prominently, sample watermark or approved issuer, number, premises subset, validity interval, original/source record and artifact. Separate tabs: Status history, Related applications and Continuing obligations where enabled. QR links only to approved public verification origin.

**Actions and navigation:** Download, print, copy permitted verification link, open prior/successor instrument, create renewal, or authorized status action with reason and evidence. Private download requires fresh permission. Print stylesheet excludes navigation and preserves demo watermark.

**Errors and edge behavior:** Unavailable artifact leaves registry state visible with download retry; it does not generate another certificate. Expired, suspended, revoked and superseded are different. Status dialog offers only policy-permitted transitions; generic arbitrary status editing is forbidden.

### UI-18 - Public verification result

**Route:** `/verify and /verify/:token`. **Access:** Public. **Requirements:** FR-22.

**Layout and information:** Public verification has a single token/number lookup and optional device QR scanning. Result card displays effective status, approved minimum premises label, issuer/source, issue/valid-until dates and checked-at time. Demo records are unmistakably marked Not an official certificate.

**Actions and navigation:** Submit lookup; scan QR only after camera consent; copy permitted reference; retry an unavailable lookup. QR input is validated and never opens arbitrary scanned URLs automatically.

**Errors and edge behavior:** Unknown lookup shows Record not found without private hints. Registry outage or stale external source shows Unable to verify now in neutral/amber, never green ACTIVE. No owner contact, full file, detailed inspection finding or internal officer notes appear. Active results are not cached offline.

### UI-19 - Personal notifications and preferences

**Route:** `/notifications`. **Access:** Authenticated. **Requirements:** FR-19, FR-23.

**Layout and information:** Chronological personal notifications with unread filter and grouped service labels. A notification shows human-readable event, event time, read state and safe action link. Optional channel delivery status may appear for the account holder but not unrelated recipients.

**Actions and navigation:** Open target, mark read, mark read through current visible boundary, filter and update optional preferences. Navigation rechecks target permission; read status does not change case state.

**Errors and edge behavior:** Deleted/now-forbidden targets show a safe explanation. Failed email delivery does not remove in-app notification. New notifications arriving after Mark all read boundary remain unread.

### UI-20 - Jobs, delivery failures and recovery

**Route:** `/operations`. **Access:** Operations administrator. **Requirements:** FR-19, FR-23, FR-29.

**Layout and information:** Operations dashboard: database/readiness, outbox lag, oldest due job, worker heartbeat, dead-letter count, unknown provider outcomes and provider health. Job detail exposes sanitized attempts, lease, next retry, owner and correlation IDs; no full sensitive request body.

**Actions and navigation:** Retry safe job; reconcile unknown outcome; assign intervention; inspect delivery attempt; open provider contract; download a redacted diagnostic bundle when authorized. Each recovery action requires reason and current job version.

**Errors and edge behavior:** Unknown signing outcome disables blind retry. A dead-letter row does not allow an administrator to set case COMPLETED. Restore providers is demo-only; production recovery requires real external actions and subsequent health checks. Readiness and business dependency degradation are distinct.

### UI-21 - Staff, grants and assignment availability

**Route:** `/team`. **Access:** Admin / supervisor scoped view. **Requirements:** FR-02, FR-08.

**Layout and information:** Staff roster with display name, active state, role scopes, grant expiry and workload summary. Detail has access requests, approved grants, availability and immutable history. Sensitive identity-provider IDs are staff-management data, not public fields.

**Actions and navigation:** Create invitation against an approved request; prepare/approve/revoke grants with separation; deactivate/reactivate; manage availability; supervisors view only scoped roster/assignment controls. Reassignment uses the inspection flow, not editing a staff counter.

**Errors and edge behavior:** Admin cannot self-grant decision authority. Deactivation warns about current assignments and immediately revokes server access. Reactivation does not restore expired/revoked powers. OIDC subject mismatch requires verified recovery, not email-only account takeover.

### UI-22 - Metrics, reports and export jobs

**Route:** `/reports`. **Access:** Supervisor, Leadership. **Requirements:** FR-25, FR-26.

**Layout and information:** Reports contain definition cards for Received, Open, Published, Rejected, Withdrawn, Overdue obligations and Median/P90 resolution. Filters: time window, service, jurisdiction, category and source mode. Graphs have equivalent data tables and labelled axes.

**Actions and navigation:** Drill down to exact filtered cases, export selected report/field set with purpose, track export job and access artifact. Display as-of cutoff, exclusions, sample size and definition version on every export.

**Errors and edge behavior:** No data is distinct from provider/query failure. Drafts excluded from received metrics. A short sample does not support claimed performance improvement. Download expiry and changed permission produce clear regeneration guidance.

### UI-23 - Audit event search and details

**Route:** `/audit`. **Access:** Scoped auditor. **Requirements:** FR-26, FR-28.

**Layout and information:** Audit explorer is a scoped chronological search with event type, actor role, case reference, correlation ID and time filters. Detail shows a safe change summary, policy/grant references and integrity checkpoint information. Avoid default dumping of entire before/after personal payloads.

**Actions and navigation:** Search, filter, open record and request permitted audit export with purpose. Sensitive audit reads are themselves audited without creating infinite recursive content logs.

**Errors and edge behavior:** Unauthorized users see no audit navigation. Restricted values are redacted even when a user can see the event metadata. A hash badge says Integrity checked against checkpoint, not Unhackable or immutable under all administrators.

### UI-24 - Policy versions, review and activation

**Route:** `/policies and /policies/:id`. **Access:** Admin, Policy approver, scoped readers. **Requirements:** FR-03, FR-27.

**Layout and information:** Policy list shows service, version, mode, effective interval, stage and preparer/approver. Editor has structured sections: applicability, forms/docs, checklist, authority, clocks, routing, outcomes and integrations. Raw JSON is an optional authorized advanced view with validation. Detail includes diff and impact preview.

**Actions and navigation:** Create version, edit draft, validate, submit for review, independently approve/return and activate at approved time. Show existing-case pinning and require migration approval for any planned retroactive change.

**Errors and edge behavior:** Self-approval, overlapping effective intervals, missing required profile data and schema errors block publication. Changing a submitted review payload invalidates prior approval. Never silently activate a policy because Save was clicked.

### UI-25 - Provider configuration and reconciliation

**Route:** `/integrations`. **Access:** Operations administrator. **Requirements:** FR-29.

**Layout and information:** Integration cards show type, SIMULATED/SANDBOX/LIVE badge, enabled state, approved capabilities, last health check and source freshness. Detail shows field ownership, source sequence and sanitized conflict records. Secret values are never returned to the frontend.

**Actions and navigation:** Test allowlisted non-destructive operation, inspect source record, trigger controlled reconciliation and resolve a conflict with evidence. Secret rotation uses approved secret-management references, not a free-text credentials table in the UI.

**Errors and edge behavior:** Test success is not proof all partner workflows are live. Sequence gaps and mismatched payloads stay quarantined. No arbitrary destination URL or fetched document link supplied by an applicant is executed by this screen.

### UI-26 - Help, tickets, referrals and permitted appeals

**Route:** `/support and /support/:id`. **Access:** Authenticated; public help only. **Requirements:** FR-30.

**Layout and information:** Help explains common steps, technical issues and non-emergency scope. Authenticated tickets show category, subject, case link, conversation, owner and status. Applicant conversation excludes internal support notes. Profile-dependent appeal has visibly distinct legal wording and receipt.

**Actions and navigation:** Create a ticket, attach accepted files, respond, track, resolve/reopen under support policy. An authorized support agent can request more information or escalate. Withdrawal remains a separate guarded case action. Disabled appeal offers approved referral, not a fake filing form.

**Errors and edge behavior:** A support ticket is not an emergency response or legal appeal unless explicitly implemented under its own enabled profile. No support action can bypass an evidence guard, grant authority or rewrite an outcome. Out-of-scope attached case IDs rejected.

### UI-27 - Personal and permitted operational settings

**Route:** `/settings`. **Access:** Authenticated. **Requirements:** FR-01, FR-23.

**Layout and information:** Personal settings: language, timezone display preference constrained by service labels, notification preferences and accessibility display options. Administrator settings contain safe operational values with explanation and version history; legal policy belongs in UI-24.

**Actions and navigation:** Save settings; validate numeric bounds; preview preference changes. System tuning updates require permission and audit; service clock policy cannot be changed through a generic setting.

**Errors and edge behavior:** Failure preserves existing server settings and local edits with retry. Sensitive secrets are write-only through approved management, never readable. Required communications cannot be disabled by an optional marketing-style checkbox.

### UI-28 - Demonstration controls and walkthrough

**Route:** `/demo`. **Access:** Demo-only authorized operator. **Requirements:** FR-12, FR-19, FR-29.

**Layout and information:** A separate demo-only panel with scenario names, demonstration clock, synthetic provider fault switches, walkthrough and reset warning. It is never part of the live navigation or route registration.

**Actions and navigation:** Select demo persona only within isolated demo authentication; advance controlled fake clock; inject known provider faults; trigger conflict scenario; export sanitized demo snapshot; reset after confirmation. Show what data will be replaced.

**Errors and edge behavior:** Reset requires explicit typed confirmation and refuses non-demo database/service mode. Demonstration clock cannot alter host clock or live timestamps. Fault switches never accept arbitrary shell commands or external targets.


## 6. Application wizard state and field behavior

The wizard's state is a server DRAFT plus an explicitly marked unsaved edit buffer. Saving cannot change the stage. Required field definitions and units are centralized in [form schemas](24_FORM_SCHEMAS_AND_VALIDATION.md). Step navigation may revisit previous valid steps; jumping ahead validates prerequisites. The last review step shows all current requirements and any changed policy since draft creation.

Pressing Enter submits the current form action only when intended; it must not accidentally finalize an application from a text field. Cancel/Save and exit leaves the draft, while a submitted case cannot be silently discarded. Leaving with unsaved edits or local files opens a warning. An autosave failure says Not saved and offers retry, rather than a permanent Saved badge.

On a version conflict, compare the changed fields to the latest draft. Explicitly reapply the user's chosen edits with a new expected version and command key. Do not discard the server version or resend the full stale object as an overwrite. The form must also handle a file scan completing while the user is on Review.

## 7. Error, empty and pending screens

Implement route-level errors for 401, 403/404, 409/412, 429, 503 and unexpected 500. Error pages provide reference ID, safe explanation and next action. Session expiry preserves an allowed return route. Stale data always has a timestamp. Loading, empty and unavailable are visually distinct.

For a slow command, keep the disabled primary action and show Working. After network timeout, change to Outcome not confirmed with Check status / Retry safely; use the original idempotency key. Do not display a red Failed label if the server may already have committed. For a job, separate queued, executing, retry waiting, reconciliation needed and completed states.

## 8. Accessibility, language and content

Target WCAG 2.2 AA. Test keyboard-only navigation, focus order, screen-reader labels and validation announcements, 200% zoom, 320 CSS px reflow, reduced-motion preference and high-contrast settings. Every chart has a data table or equivalent text summary. Dates have explicit locale/timezone; color is not the only status cue. No CAPTCHA or OTP timing interaction should make an accessible task impossible; the security-approved recovery/assisted channel remains available.

Use plain English task wording: Documents needed, Response received, Waiting for review, Certificate processing and Could not verify right now. Explain technical terms on first use. Internal queue or job error codes appear under Details, not as the only user message. Translation must preserve legal terminology and approved notices; machine-generated untranslated placeholders cannot be enabled for live Hindi service.

## 9. Acceptance screenshots and visual review

For each UI screen, capture desktop and relevant mobile states from the implemented server-backed app: loading, normal, empty, validation failure and role restriction. Capture the real correction cycle, issuance failure and offline conflict, not just the landing page. Compare structure and design tokens against the reference prototype. Visual consistency is required, but pixel-perfect imitation of unsafe tiny controls is not.

See [prototype coverage](23_PROTOTYPE_COVERAGE.md) for every discovered prototype route and action's production classification. An action not backed by a complete feature must be removed or visibly disabled by a documented gate, never left as a dead button.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
