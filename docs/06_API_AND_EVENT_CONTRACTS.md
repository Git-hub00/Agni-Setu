# API, command and event contracts

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Contract policy

The base path is `/api/v1`. The catalogue below lists paths relative to that prefix. `GET /api/v1/health/*` is routed privately for readiness where configured. Generate OpenAPI from DRF/drf-spectacular, commit it to `contracts/openapi.yaml` and generate the TypeScript client types. The generated schema must match this contract before a frontend feature is considered complete. This pack specifies the contract; it does not include an already running API.

Use JSON UTF-8, UUID strings for internal IDs, ISO 8601 UTC timestamps and decimal strings for area/height/monetary values when precision matters. Reject unknown write fields. Requests are bounded in size; paginated collections default to 25 and maximum 100. Sorting is allowlisted; never accept arbitrary SQL/property expressions. Any supplied reference is checked for scope and cross-record ownership, not merely UUID validity.

## 2. Authentication and CSRF

Browser requests use a same-origin, HttpOnly server session cookie. The CSRF cookie/token is readable to the same-origin frontend as needed and sent in `X-CSRFToken` on every unsafe request. Configure Origin/Referer checks and explicit allowed hosts. OTP endpoints are not exempt merely because the user is unauthenticated: DRF's session-authenticated CSRF behavior alone is insufficient for those login endpoints. Staff OIDC state/nonce/PKCE checks are additional controls, not a substitute for session CSRF elsewhere.

Partner callbacks use their own approved mTLS/OAuth/HMAC scheme and never inherit public browser exemptions. There is no public registration endpoint accepting roles. The demo persona chooser selects an existing synthetic login target; it does not grant roles or bypass the regular local authentication flow. Demo scenario controls are absent from live deployments.

## 3. Common response and pagination

Ordinary success uses `{ "data": ..., "meta": { "request_id": "..." } }`. A list's data is `{items, next_cursor, has_more}`; bounded `total` is optional and must use the same scoped filter population. Reporting also returns `as_of`, `definition_version`, `scope` and `filters`. Detail responses include their current `version` and `allowed_actions`, and send a strong ETag of the form `"application:<uuid>:v12"`.

A command result contains the canonical resource/revision, `command_id`, `accepted_at`, `replayed`, and links to any pending job. Preserve original acceptance facts on replay while the outer `meta.request_id` can identify the new HTTP request. A 202 response includes status/polling links and cannot imply completed business work.

```json
{
  "data": {
    "application_id": "4d8d3da8-b6f0-43f8-86f7-8e46877d6e64",
    "public_reference": "AS-2026-2001",
    "status": "SUBMITTED",
    "version": 8,
    "submission_revision": 1,
    "command_id": "a2f9c4bc-d2d1-4905-a462-2b8dbbb624c3",
    "accepted_at": "2026-09-09T10:00:00Z",
    "replayed": false,
    "next_action": "Completeness review",
    "allowed_actions": [{"key": "view_receipt", "enabled": true, "reason_code": null}]
  },
  "meta": {"request_id": "628ff0cf-c8fb-4cc9-952a-a75e0d3e25c9"}
}
```

## 4. Idempotency and version preconditions

All business POST/PUT/PATCH commands require `Idempotency-Key` containing a new random UUID per logical action. Same principal, target, command and key with identical normalized payload yields the original authorized receipt; a different hash returns IDEMPOTENCY_CONFLICT. Authentication challenge and logout endpoints have their own single-use/rotation semantics and are excluded from generic replay of authenticated session issuance. Repeated GET is safe and has no hidden regulatory side effect.

Existing-resource mutations also require `If-Match` for the resource identified in the route. For a nested `/applications/{id}/...` command this is the application ETag; for `/inspections/{id}/...` it is the inspection ETag; for `/notices/{id}/...` it is the notice ETag, and similarly for finding, job, policy, grant, ticket and certificate commands. A receipt replay is checked before the stale-version check, after current authorization. Missing precondition is 428; stale is 412.

Commands on a child resource that alter case readiness or lifecycle also require `application_version` in the body. This includes inspection scheduling/reassignment/check-in/failure/report/draft acceptance, notice response/review, finding verification and conflict resolution. Resolve the child to its case server-side; clients cannot supply a different case ID. Lock the case and check this dependency version before modifying the child. Increment the case version for readiness-relevant changes and return both resource versions. A pure read marker or profile preference does not increment case version.

Uploads are independently versioned. Attaching/detaching them to a draft or response is a case/notice command. A scan completing does not rewrite a submitted revision; accepted references already bind clean immutable object versions. An adverse later security finding raises an owned hold/incident and prevents new unsafe access or decisions.

## 5. Error envelope

Use `application/problem+json` following the Problem Details structure in RFC 9457, with stable project extensions. `type` is a stable URI identifier controlled by the deployment; no need to expose a public help endpoint for every code. `detail` is safe actionable text. `violations` use JSON Pointers and never include secret values. Do not use HTTP 200 for domain errors.

```json
{
  "type": "urn:agni-setu:problem:mandatory-findings-open",
  "title": "Decision cannot be recorded",
  "status": 409,
  "detail": "One mandatory finding still needs verified closure.",
  "instance": "/api/v1/applications/4d8d3da8-b6f0-43f8-86f7-8e46877d6e64/decisions",
  "code": "MANDATORY_FINDINGS_OPEN",
  "request_id": "628ff0cf-c8fb-4cc9-952a-a75e0d3e25c9",
  "retryable": false,
  "violations": [{"pointer": "/finding_ids", "code": "OPEN_FINDING", "message": "Review finding C01 before approval."}]
}
```

401 denotes missing/invalid authentication. 403 is a forbidden action on a known readable resource; out-of-scope IDs return the same 404 as absent IDs. 409 is a domain conflict, 412 a stale precondition, 422 invalid business input, 428 missing precondition, 429 throttling, and 503 a dependency that prevents a safe current result. Unknown provider outcome after an accepted async command is primarily a persisted job state; do not retroactively change the original acceptance into HTTP failure.

## 6. Endpoint catalogue

The capability is necessary but not sufficient: scope, assignment, service mode, authority dates and transition guards also apply. DTO field definitions are in [form and command schemas](24_FORM_SCHEMAS_AND_VALIDATION.md). Conditional APIs return SERVICE_DISABLED before side effects when their profile gate is off.

| ID | Method | Path | Capability | Input | Success | FR | Behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| API-001 | GET | /auth/csrf | public | None | 200 CsrfBootstrap | FR-01 | Set CSRF cookie; return token to same-origin caller; never authenticate. |
| API-002 | POST | /auth/otp/challenges | public | OtpStart | 202 Challenge | FR-01 | Enumeration-safe challenge; anti-abuse limits; sender adapter. |
| API-003 | POST | /auth/otp/verify | public | OtpVerify | 200 Session | FR-01 | Consume single-use challenge; rotate authenticated server session. |
| API-004 | GET | /auth/oidc/start | public | OidcStartQuery | 302 redirect | FR-02 | Create PKCE/state/nonce server-side, redirect to staff identity provider. |
| API-005 | GET | /auth/oidc/callback | public | OidcCallbackQuery | 302 relative redirect | FR-02 | Validate token and approved staff mapping; never trust user-supplied roles. |
| API-006 | POST | /auth/logout | session | Empty | 204 | FR-01 | Flush current session and initiate allowed provider logout when relevant. |
| API-007 | GET | /me | session | None | 200 Principal | FR-01 | Identity, scopes, workspaces, feature gates and authorization epoch. |
| API-008 | PATCH | /me/preferences | self.preferences | Preferences | 200 Preferences | FR-23 | Update locale and optional channel choices; cannot suppress mandatory notices. |
| API-009 | POST | /me/contact-changes | self.contact | ContactChange | 202 Challenge | FR-01 | Step-up and verify new contact; existing contact notification; no arbitrary ownership change. |
| API-010 | GET | /premises | premises.read | ListQuery | 200 Page<Premises> | FR-03 | Owner/delegation-scoped results. |
| API-011 | POST | /premises | premises.create | PremisesCreate | 201 Premises | FR-03 | Create reusable premises master, not a received application. |
| API-012 | GET | /premises/{id} | premises.read | None | 200 Premises | FR-10 | Scope-filtered representation. |
| API-013 | PATCH | /premises/{id} | premises.edit | PremisesPatch | 200 Premises | FR-03 | New master version; never change prior submitted snapshots. |
| API-014 | GET | /delegations | delegation.read | ListQuery | 200 Page<Delegation> | FR-10 | Only beneficiary, delegate or separately authorized reviewer. |
| API-015 | POST | /delegations | delegation.propose | DelegationCreate | 201 Delegation | FR-10 | Propose scoped delegation pending beneficiary verification. |
| API-016 | POST | /delegations/{id}/confirm | delegation.confirm | Reason | 200 Delegation | FR-10 | Verify beneficiary and scope before activation. |
| API-017 | POST | /delegations/{id}/revoke | delegation.revoke | Reason | 200 Delegation | FR-10 | Revoke through authorization fence; pending work remains attributed. |
| API-018 | GET | /services | public | ServiceCatalogQuery | 200 ServiceCatalog | FR-03 | Only enabled public services and safe availability explanations. |
| API-019 | POST | /services/{id}/applicability | service.read | ApplicabilityInput | 200 ApplicabilityResult | FR-03 | Nonbinding form requirements; submission revalidates policy. |
| API-020 | GET | /applications | case.read | CaseListQuery | 200 Page<CaseSummary> | FR-09 | Scope before filter/count; stable cursor; excludes drafts from received metrics. |
| API-021 | POST | /applications | case.create | DraftCreate | 201 Application | FR-04 | Create DRAFT with draft identifier; no receipt or case target. |
| API-022 | GET | /applications/{id} | case.read | None | 200 CaseDetail | FR-09 | Current canonical detail and allowed actions with safe blockers. |
| API-023 | PATCH | /applications/{id}/draft | case.edit_draft | DraftPatch | 200 Application | FR-04 | Editable fields only; optimistic version check; original revisions preserved. |
| API-024 | POST | /applications/{id}/submit | case.submit | Submission | 200 SubmissionReceipt | FR-06 | TR-01 with snapshot, policy, routing ownership, obligations, audit and outbox. |
| API-025 | GET | /applications/{id}/timeline | case.read | CursorQuery | 200 Page<CaseEvent> | FR-09 | Audience-filtered event projection, no internal note leakage. |
| API-026 | GET | /applications/{id}/revisions | case.read | CursorQuery | 200 Page<SubmissionRevision> | FR-06 | Immutable accepted revisions visible by scope. |
| API-027 | POST | /applications/{id}/start-scrutiny | case.scrutinize | Reason | 200 CaseDetail | FR-07 | TR-02 and scrutiny-stage task ownership. |
| API-028 | POST | /applications/{id}/resolve-routing | case.route | RoutingResolution | 200 CaseDetail | FR-07 | Resolve exception with active mapping and documented authority. |
| API-029 | POST | /applications/{id}/require-inspection | case.scrutinize | InspectionRequest | 201 Inspection | FR-11 | TR-05, new requested attempt and obligation. |
| API-030 | POST | /applications/{id}/withdraw | case.withdraw | Reason | 200 CaseDetail | FR-30 | TR-13 only permitted stages; close affected obligations with reasons. |
| API-031 | POST | /applications/{id}/holds | case.hold | HoldCreate | 201 Hold | FR-18 | Record authorized hold and only policy-permitted clock impacts. |
| API-032 | POST | /holds/{id}/release | case.hold | Reason | 200 Hold | FR-18 | Close hold interval; recompute impacted obligations without erasing age. |
| API-033 | POST | /uploads | document.upload | UploadReservation | 201 UploadTicket | FR-05 | Scope validate target; reserve immutable object key and bounded upload. |
| API-034 | POST | /uploads/{id}/complete | document.upload | UploadComplete | 202 DocumentVersion | FR-05 | Verify immutable object size/hash/type; quarantine and durable scan intent. |
| API-035 | GET | /documents/{id} | document.read | None | 200 DocumentVersion | FR-05 | Safe metadata, revision and scan status, not unrestricted object URL. |
| API-036 | POST | /documents/{id}/access | document.read | DocumentAccess | 200 DownloadTicket | FR-05 | Audit and return short-lived least-scope download/preview mechanism. |
| API-037 | POST | /documents/{id}/detach | document.edit_draft | Reason | 200 Application | FR-05 | Detach only unsubmitted draft reference; do not destroy accepted evidence. |
| API-038 | GET | /inspections | inspection.read | InspectionListQuery | 200 Page<Inspection> | FR-11 | Assigned or supervised scope; due and appointment filters. |
| API-039 | GET | /inspections/{id} | inspection.read | None | 200 InspectionDetail | FR-13 | Attempt, assignment, checklist, report versions and allowed actions. |
| API-040 | GET | /schedule | inspection.read | ScheduleQuery | 200 Schedule | FR-11 | Time-window and authorized officer scope. |
| API-041 | POST | /inspections/{id}/schedule | inspection.assign | ScheduleCommand | 200 Inspection | FR-08 | Booking overlap constraint, assignment revision, applicant notice. |
| API-042 | POST | /inspections/{id}/reassign | inspection.assign | ReassignCommand | 200 Inspection | FR-08 | Current eligibility and booking check; supersede assignment and revoke old package. |
| API-043 | POST | /inspections/{id}/cancel | inspection.assign | Reason | 200 Inspection | FR-11 | Cancel uncompleted attempt; create required next-action task. |
| API-044 | POST | /inspections/{id}/check-in | inspection.perform | CheckIn | 200 Inspection | FR-11 | Record corroborating capture/GPS and visit state; not proof of compliance. |
| API-045 | PUT | /inspections/{id}/draft | inspection.perform | ReportDraft | 200 ReportDraft | FR-13 | Save server draft; inspection ETag guards current editable workspace. |
| API-046 | POST | /inspections/{id}/fail-visit | inspection.perform | FailedVisit | 200 Inspection | FR-11 | Persist FAILED attempt and rescheduling obligation; no case rejection. |
| API-047 | POST | /inspections/{id}/reports | inspection.perform | ReportSubmit | 201 ReportReceipt | FR-13 | Immutable accepted report; TR-06 if prerequisites valid. |
| API-048 | GET | /inspections/{id}/offline-package | inspection.perform | None | 200 OfflinePackage | FR-12 | Minimal authorized assignment snapshot with expiry and versions. |
| API-049 | POST | /sync/operations | inspection.perform | SyncOperation | 200 SyncReceipt | FR-12 | Reauthenticate, validate base/assignment/schema/evidence; no last-write-wins. |
| API-050 | GET | /sync/operations/{operationId} | inspection.perform | None | 200 SyncReceipt | FR-12 | Owner-scoped canonical accepted outcome or absence; no fabricated receipt. |
| API-051 | POST | /inspections/{id}/conflicts | inspection.perform | ConflictProposal | 201 Conflict | FR-13 | Store safe conflict proposal, not active report overwrite. |
| API-052 | POST | /conflicts/{id}/resolve | inspection.review | ConflictResolution | 200 Conflict | FR-13 | Authorized rebase/new report/decline; preserve both versions and reason. |
| API-053 | GET | /applications/{id}/notices | notice.read | CursorQuery | 200 Page<Notice> | FR-15 | Role-audience filtered notices and their item states. |
| API-054 | POST | /applications/{id}/notices | notice.publish | NoticeCreate | 201 Notice | FR-15 | Publish info or deficiency notice and guarded case transition. |
| API-055 | GET | /notices/{id} | notice.read | None | 200 NoticeDetail | FR-15 | Published content and permitted response history. |
| API-056 | POST | /notices/{id}/responses | notice.respond | NoticeResponse | 201 ResponseRevision | FR-16 | New per-item response version; no automatic finding closure. |
| API-057 | POST | /notices/{id}/accept-information | notice.review | Reason | 200 CaseDetail | FR-16 | TR-04 only after all required item verifications accepted. |
| API-058 | POST | /notice-items/{id}/review | notice.review | ItemReview | 200 NoticeItem | FR-17 | Accept or return with evidence and reason; reviewer cannot be applicant. |
| API-059 | GET | /applications/{id}/findings | inspection.read | None | 200 FindingList | FR-14 | Current finding status with immutable observations and linked responses. |
| API-060 | POST | /findings/{id}/verify | finding.verify | FindingVerification | 200 Finding | FR-17 | Authorized verified closure or return; version check and evidence binding. |
| API-061 | POST | /applications/{id}/complete-corrections | case.review | Reason | 200 CaseDetail | FR-17 | TR-08 only when all mandatory finding guards cleared. |
| API-062 | POST | /applications/{id}/reinspect | case.review | ReinspectionRequest | 201 Inspection | FR-17 | TR-09 new attempt linked to findings; original age preserved. |
| API-063 | POST | /applications/{id}/return-review | case.review | ReviewReturn | 201 Inspection | FR-13 | TR-14 clarification/addendum route; retain accepted report. |
| API-064 | GET | /applications/{id}/decision-readiness | case.review | None | 200 DecisionReadiness | FR-20 | Server-calculated guard list; read result never authorizes later command by itself. |
| API-065 | POST | /applications/{id}/decisions | case.decide | DecisionCommand | 201 DecisionReceipt | FR-20 | TR-10 or TR-12 with authority fence, immutable evidence set and outcome. |
| API-066 | GET | /applications/{id}/decisions | case.read | None | 200 DecisionList | FR-20 | Published decision plus authorized internal context projection. |
| API-067 | GET | /certificates | certificate.read | CertificateListQuery | 200 Page<Certificate> | FR-21 | Scoped authoritative register and pending-issuance cards. |
| API-068 | GET | /certificates/{id} | certificate.read | None | 200 CertificateDetail | FR-24 | Instrument provenance, status history and allowed lifecycle actions. |
| API-069 | POST | /certificates/{id}/access | certificate.read | DocumentAccess | 200 DownloadTicket | FR-21 | Authorized sample/signed artifact, labelled by mode. |
| API-070 | POST | /certificates/{id}/renewals | case.create | RenewalCreate | 201 Application | FR-24 | New linked DRAFT under current applicable policy; no validity extension. |
| API-071 | POST | /certificates/{id}/status-actions | certificate.status | CertificateStatusCommand | 201 StatusInstrument | FR-24 | Profile-permitted authority/reason action; cannot resurrect expired or revoked record arbitrarily. |
| API-072 | POST | /applications/{id}/external-registration | certificate.register_external | ExternalRegistration | 201 Certificate | FR-21 | Conditional TR-15, preserve external issuer/source artifact. |
| API-073 | GET | /public/certificates/{token} | public | None | 200 Verification or 404/503 | FR-22 | Minimal non-cacheable authoritative assertion; rate-limited; unknown != revoked. |
| API-074 | GET | /obligations | obligation.read | ObligationQuery | 200 Page<Obligation> | FR-18 | Open/overdue/risk scoped by a single cutoff. |
| API-075 | GET | /obligations/{id} | obligation.read | None | 200 ObligationDetail | FR-18 | Clock calculation breakdown, calendar, pauses and threshold history. |
| API-076 | POST | /obligations/{id}/escalations | obligation.intervene | EscalationCreate | 201 Escalation | FR-19 | Reasoned manual intervention, does not satisfy underlying work. |
| API-077 | POST | /escalations/{id}/acknowledge | obligation.intervene | Reason | 200 Escalation | FR-19 | Record intervention owner and next action, not regulatory completion. |
| API-078 | GET | /notifications | self.notifications | NotificationQuery | 200 Page<Notification> | FR-23 | Current recipient only; mark as read is separate from delivered status. |
| API-079 | POST | /notifications/{id}/read | self.notifications | Empty | 200 Notification | FR-23 | Idempotent read marker. |
| API-080 | POST | /notifications/read-through | self.notifications | ReadThrough | 200 ReadSummary | FR-23 | Mark only notifications up to explicit timestamp/id boundary. |
| API-081 | GET | /reports/summary | report.read | ReportQuery | 200 MetricsSnapshot | FR-25 | Single-cutoff reconciled metrics and definitions. |
| API-082 | POST | /exports | export.create | ExportRequest | 202 ExportJob | FR-26 | Persist scope, purpose, field set and cutoff; asynchronous generation. |
| API-083 | GET | /exports/{id} | export.read | None | 200 ExportJob | FR-26 | Owner or specially authorized status; validate current scope. |
| API-084 | POST | /exports/{id}/access | export.read | Reason | 200 DownloadTicket | FR-26 | Reauthorize requester, scope, expiry and purpose before access. |
| API-085 | GET | /audit-events | audit.read | AuditQuery | 200 Page<AuditEvent> | FR-28 | Permitted event fields; query itself audited. |
| API-086 | GET | /audit-events/{id} | audit.read | None | 200 AuditEvent | FR-28 | Safe redacted detail and integrity metadata. |
| API-087 | GET | /staff | staff.read | StaffQuery | 200 Page<StaffSummary> | FR-02 | Scoped roster; no secret or recovery data. |
| API-088 | POST | /staff/invitations | staff.provision | StaffInvitation | 201 Invitation | FR-02 | Approved request reference, no self-authorized statutory grant. |
| API-089 | POST | /staff/{id}/deactivate | staff.provision | Reason | 200 StaffSummary | FR-02 | Authorization fence increment, sessions revoked, unowned-work alerts. |
| API-090 | POST | /staff/{id}/reactivate | staff.provision | AccessApproval | 200 StaffSummary | FR-02 | New approved activation; old grants do not automatically revive. |
| API-091 | POST | /authority-grants | grant.prepare | GrantProposal | 201 GrantProposal | FR-02 | Create proposed effective scoped powers; preparation alone grants nothing. |
| API-092 | POST | /authority-grants/{id}/approve | grant.approve | Reason | 200 AuthorityGrant | FR-02 | Independent designated approver, current authority and fence update. |
| API-093 | POST | /authority-grants/{id}/revoke | grant.revoke | Reason | 200 AuthorityGrant | FR-02 | Serialize with case commands through subject authorization fence. |
| API-094 | POST | /staff/{id}/availability | inspection.assign | Availability | 201 Availability | FR-08 | Future availability record; existing conflicts surfaced, never silently cancelled. |
| API-095 | GET | /policies | policy.read | PolicyQuery | 200 Page<PolicyVersion> | FR-27 | Scope and policy stage filters. |
| API-096 | POST | /policies | policy.prepare | PolicyDraft | 201 PolicyVersion | FR-27 | Create a new immutable-version lineage with editable draft payload. |
| API-097 | GET | /policies/{id} | policy.read | None | 200 PolicyDetail | FR-27 | Payload, diff, approvals, effective interval, references and impact preview. |
| API-098 | PATCH | /policies/{id} | policy.prepare | PolicyDraftPatch | 200 PolicyVersion | FR-27 | Only editable DRAFT/RETURNED, record every preparer. |
| API-099 | POST | /policies/{id}/submit-review | policy.prepare | Reason | 200 PolicyVersion | FR-27 | Schema and completeness validation; freeze review candidate hash. |
| API-100 | POST | /policies/{id}/approve | policy.approve | PolicyApproval | 200 PolicyVersion | FR-27 | Independent approver; valid interval and no activation overlap. |
| API-101 | POST | /policies/{id}/return | policy.approve | Reason | 200 PolicyVersion | FR-27 | Reasoned return without overwriting prior review event. |
| API-102 | POST | /policies/{id}/activate | policy.activate | PolicyActivation | 200 PolicyVersion | FR-27 | Same service fence as submission; start only at approved effective time. |
| API-103 | GET | /jobs | operations.read | JobQuery | 200 Page<Job> | FR-19 | Operational metadata with sensitive payloads redacted. |
| API-104 | GET | /jobs/{id} | operations.read | None | 200 JobDetail | FR-23 | Attempts, lease, ambiguity, owner, next permitted action. |
| API-105 | POST | /jobs/{id}/retry | operations.recover | RecoveryCommand | 202 Job | FR-19 | Same logical action; refuse blind retry of ambiguous irreversible effect. |
| API-106 | POST | /jobs/{id}/reconcile | operations.recover | RecoveryCommand | 202 Job | FR-29 | Query/verify provider outcome before completion or retry decision. |
| API-107 | GET | /integrations | operations.read | None | 200 IntegrationList | FR-29 | Mode, health, ownership and sanitized configuration; no secrets. |
| API-108 | POST | /integrations/{id}/test | operations.configure | IntegrationTest | 202 Job | FR-29 | Approved non-destructive endpoint and credentials; no arbitrary URL fetch. |
| API-109 | POST | /integrations/{id}/events | partner.event | PartnerEvent | 202 PartnerReceipt | FR-29 | Persist authenticated inbox; duplicates acknowledged; process asynchronously. |
| API-110 | GET | /integration-conflicts | operations.read | ListQuery | 200 Page<IntegrationConflict> | FR-29 | Owned schema, order and source conflicts. |
| API-111 | POST | /integration-conflicts/{id}/resolve | integration.reconcile | IntegrationResolution | 200 IntegrationConflict | FR-29 | Approved evidence-based resolution; no fabricated partner outcome. |
| API-112 | GET | /tickets | ticket.read | TicketQuery | 200 Page<Ticket> | FR-30 | Requester or approved support scope. |
| API-113 | POST | /tickets | ticket.create | TicketCreate | 201 Ticket | FR-30 | Separate support lifecycle and owner; no legal filing implied. |
| API-114 | GET | /tickets/{id} | ticket.read | None | 200 TicketDetail | FR-30 | Audience-filtered public replies and staff internal notes. |
| API-115 | POST | /tickets/{id}/messages | ticket.respond | TicketMessage | 201 TicketMessage | FR-30 | Attachment scan/auth, audience and attributable sender. |
| API-116 | POST | /tickets/{id}/status | ticket.manage | TicketStatus | 200 Ticket | FR-30 | Guarded support status action; no case mutation. |
| API-117 | POST | /appeals | appeal.submit | AppealCreate | 201 Appeal | FR-30 | Conditional enabled profile only; separate immutable challenged decision reference. |
| API-118 | POST | /appeals/{id}/decisions | appeal.decide | AppealDecision | 201 AppealDecision | FR-30 | Conditional authorized separate instrument; source outcome retained. |
| API-119 | POST | /certificates/{id}/declarations | declaration.submit | DeclarationCreate | 201 Declaration | FR-24 | Conditional approved continuing obligation, evidence and receipt. |
| API-120 | POST | /demo/scenarios | demo.control | DemoScenario | 200 DemoScenarioResult | FR-29 | Only isolated demo deployment; no live route registration. |
| API-121 | GET | /health/live | probe | None | 200 Liveness | FR-29 | Process liveness; no environment or credential dump. |
| API-122 | GET | /health/ready | probe | None | 200/503 Readiness | FR-29 | Database and mandatory startup configuration; operational degradation separated. |
| API-123 | POST | /policies/{id}/simulate | policy.simulate | PolicySimulation | 200 PolicySimulationResult | FR-27 | Run bounded deterministic fixtures against candidate hash; persist result, never mutate active cases. |

## 7. Canonical detail projections

### Principal and session

`Principal` contains `id`, `display_name`, `kind`, `workspaces`, `active_workspace`, `scopes` as safe human labels, `capabilities` for current UI hints, `authz_epoch`, `session_expires_at` and `feature_gates`. Never return provider access/refresh tokens, OTP hashes, secret references or all other users' grants. `Session` returns this principal projection after rotating the session cookie.

### Case summary/detail

`CaseSummary` contains ID, visible reference, premises label/category/locality, status, submitted_at, owner unit, next_action, due summary, updated_at and version. `CaseDetail` adds mode/source ownership, beneficiary/operator identities permitted to this reader, immutable submitted revision references, policy label/version, routing exception, current attempt, open notice/finding summary, outcome/issuance summary and allowed actions. Large event/doc/report lists are separate paginated resources rather than one unbounded payload.

### Inspection and report

`InspectionDetail` contains attempt ID/number/purpose, case summary, current assignment ID/version, schedule/timezone, status/version, checklist artifact/version, current draft version, accepted report references and offline package availability. A report receipt contains report ID/revision/hash, server acceptance time, operation/command ID and new inspection/application versions. Client capture timestamps are additional metadata, never the sole acceptance timestamp.

### Notice and findings

`NoticeDetail` contains immutable published content, type/round, due obligation, each item's required evidence and safe response history, verifier result and current item version. Applicant projection omits internal notes. `DecisionReadiness` returns `ready`, evaluated_at, application_version, policy/grant references safe to show, and a list of `{code,passed,message,evidence_refs}` guards. A subsequent decision must recalculate all guards.

### Certificate and verification

Private certificate detail includes artifact access action, immutable issuance/external registration reference, administrative status history, predecessor/successor and related obligations. Public Verification includes only policy-approved fields: certificate_number, effective_status, minimal premises display/locality, issued_at, valid_until, issuer/source label, checked_at and is_demo. It does not return applicant contacts, drawings, private case IDs, grant IDs or report evidence. Unknown token returns 404 with no private lookup hints. Unavailable/stale authoritative lookup returns 503 and no `valid:true`.

### Operational records

Job detail contains job/logical action IDs, kind, safe aggregate reference, state, attempts, next_attempt_at, lease status, error code, owner and allowed recovery actions. Payloads and credentials are redacted. Export status includes filters/field set, as_of, state, row_count when complete, expires_at and permitted access action. Do not return a permanent object URL.

## 8. Event contracts

Events use this envelope. `event_id` and `logical_action_id` are stable UUIDs. `aggregate_version` orders events for an aggregate; `event_ordinal` orders multiple events in one command. Consumers deduplicate by event_id and apply schema compatibility rules. `occurred_at` is authoritative server time; client captured times live inside the appropriate evidence metadata.

```json
{
  "event_id": "58cf881e-3c5a-4053-91fc-3517f393b5c4",
  "event_type": "application.submitted.v1",
  "schema_version": 1,
  "aggregate_type": "application",
  "aggregate_id": "4d8d3da8-b6f0-43f8-86f7-8e46877d6e64",
  "aggregate_version": 8,
  "event_ordinal": 1,
  "occurred_at": "2026-09-09T10:00:00Z",
  "actor_id": "75b1c5f0-cdce-4cda-80b6-53e342a869de",
  "command_id": "a2f9c4bc-d2d1-4905-a462-2b8dbbb624c3",
  "correlation_id": "628ff0cf-c8fb-4cc9-952a-a75e0d3e25c9",
  "payload": {
    "submission_revision": 1,
    "policy_version": 1,
    "owner_queue_key": "CENTRAL-PILOT-SCRUTINY"
  }
}
```

Required event families include the transition events in [workflow](02_WORKFLOW_AND_POLICY_SPECIFICATION.md), plus `document.scan_completed.v1`, `inspection.assignment_changed.v1`, `notice.response_received.v1`, `finding.reviewed.v1`, `obligation.threshold_reached.v1`, `notification.delivery_updated.v1`, `policy.approved.v1`, `policy.activated.v1`, `authority.revoked.v1`, `export.completed.v1`, `integration.conflict_detected.v1` and `ticket.updated.v1`. Each has a committed JSON Schema and consumer contract tests. Event payloads contain safe IDs, not whole uploaded files or unnecessary personal data.

## 9. Representative commands

### Submit application

`POST /api/v1/applications/{id}/submit` with the draft ETag and a stable idempotency key:

```json
{
  "draft_revision": 4,
  "reviewed_policy_version_id": "af9e2214-8d57-4c15-8da7-c9c1d8b0d613",
  "declaration_acceptances": [{"code": "ACCURATE_INFORMATION", "version": 1, "accepted": true}],
  "document_version_ids": ["c44f6dbe-d1b1-481b-bde8-c1a68d0bd1d2"]
}
```

This example intentionally contains only one file reference; a service requiring three documents must reject it unless the complete accepted required set is actually supplied. Examples do not override policy validation.

### Record a decision

`POST /api/v1/applications/{id}/decisions` with current case ETag:

```json
{
  "kind": "APPROVE",
  "submission_revision_id": "86b6a1e0-c26a-4bc4-87d8-e9e9f0062c57",
  "report_id": "6c8237d1-269a-4583-9802-0ea13a1315bf",
  "reason": "Reviewed the submitted record and verified closure evidence for the demonstration checklist.",
  "public_reason": "The demonstration review is complete. Sample certificate processing has started.",
  "review_acknowledged": true
}
```

Never allow `actor_id`, `approved_by`, `certificate_number`, `status=COMPLETED` or caller-specified authority in this payload. The server identifies the current effective grant and evidence snapshot.

## 10. API compatibility and test gates

Additive read fields are compatible; removing/renaming required fields, changing enum semantics, broadening public data or changing command retry behavior requires a versioned contract and consumer migration. Validate OpenAPI responses in contract tests. Test all endpoints for anonymous, wrong role, right role/wrong scope, inactive grant, stale version, duplicate key and malformed input where applicable.

Partner APIs have independently approved schemas and signing requirements; the browser API is not automatically a government interoperability standard. A mapping adapter must prove compatibility against the partner's actual contract. No fabricated production endpoint, token or acknowledgement belongs in the implementation.


## 12. Read/write version headers on UI-facing projections

All scoped detail and collection items for mutable resources include `version` and a current `etag` string when an action needs that resource's precondition. The frontend must not guess a grant/job/notice ETag from a case version. Access commands use the version of the route resource even when they only create an access receipt; the authorization check is repeated at download time. A201 response includes Location for the new resource. A204 response has no JSON body. Redirects do not use the ordinary success envelope. Rate-limit/precondition replies preserve request_id and safe Retry-After where applicable.

GET /auth/csrf returns a token for the same-origin request plus its cookie; Challenge includes challenge_id, masked_destination, expires_at, resend_after and next_action, never the code. Offline SyncReceipt is discriminated by operation_type and accepted_entity_kind (REPORT or VISIT_OUTCOME), canonical ID, accepted_at and returned versions. A no-content/redirect response is tested separately from JSON schema responses.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
