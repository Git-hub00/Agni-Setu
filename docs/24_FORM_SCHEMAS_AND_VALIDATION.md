# Form schemas, command DTOs and validation rules

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Validation conventions

Schemas below describe the write contract consumed by both backend serializers and generated frontend types. `optional` means the field may be absent; explicit `null` is accepted only where written. UUID references are never trusted solely because they parse. All user text is Unicode-normalized where appropriate, trimmed without destroying meaningful internal spaces, bounded in length and rendered safely. Reject control characters where they make display/audit ambiguous.

Unknown write properties are rejected. Numeric dimensions use decimal strings and Decimal validation, never binary floating point for persisted exact amounts. Date intervals are half-open unless the service explicitly specifies otherwise. Human display dates are not accepted as ambiguous `09/10/26` strings.

Use three validation levels: syntax/shape at the API boundary; field and cross-field business validation in the application/domain layer; relational integrity/uniqueness/constraints in PostgreSQL. Client validation provides helpful early feedback but cannot bypass server validation.

## 2. Applicant and premises form

| Field | UI control | Rule and message |
| --- | --- | --- |
| Display/beneficiary name | Text | 2-160 characters; explain this is the applicant or authorized organization name. |
| Contact | Email or phone | Validate selected channel; phone uses E.164; verification is a separate challenge. |
| Service | Select from enabled catalog | Required; unsupported service shows referral rather than a fake application. |
| Premises name | Text | 2-160; no automatic identity matching by similar name. |
| Address line 1 | Text | 5-200; required. |
| Address line 2 | Text | Optional, maximum200. |
| Locality / ward | Text + approved ward select | Required; ward drives approved routing, not a free-text guessed mapping. |
| Postal code | Text/inputmode numeric | Demo six-digit validation; preserve as string. |
| Category | Approved dropdown | Restaurant, Office, Hospital, School, Residential, Hotel or Warehouse in demo. |
| Area | Decimal input + square metres label | >0 with max2 decimal places; never assume submitted units. |
| Height | Decimal input + metres label | >=0 with max2 decimals; no legal threshold inferred from value. |
| Floors | Integer control | 1-300 engineering bound; unusual values require reviewed form configuration. |
| Occupancy | Integer control | Optional unless service requires; zero not treated as missing. |
| Premises authorization | Document requirement | Required by demo evidence package; a contact verification badge does not satisfy it. |
| Declarations | Individually labelled checkbox | No prechecked boxes; store exact code/version/text snapshot on submission. |

Engineering bounds prevent unreasonable payloads; they are not Delhi building eligibility rules. Live applicability and precise required fields come from the approved form schema. Changing an enabled form requires a versioned policy process.

## 3. Document requirements and upload UX

Demo base requirements: `ownership` (Premises authorization), `plan` (Fire-safety layout), `electrical` (Electrical inspection record). Hospital, School and Hotel additionally require `evacuation` (Evacuation plan). `occupancy` (Occupancy/capacity statement) is an optional sample unless the selected profile marks it required. Requiredness comes from the policy snapshot, not hard-coded screen conditional branches.

Per-file demo limit10 MiB; permitted PDF/JPEG/PNG; up to20 files and50 MiB in the active application package. A scanned clean technical result does not mean substantively verified. Replace creates a new immutable version and keeps old accepted evidence where referenced. Removing an unsubmitted file detaches the draft link; it does not delete a submitted record.

## 4. Observation and notice item schemas

`Observation` fields: `item_code` known in the exact checklist; `result` PASS/FAIL/NOT_VERIFIED/NOT_APPLICABLE; `note` string0..2000, required10..2000 for FAIL, NOT_VERIFIED and NA; `document_version_ids` unique accepted evidence IDs; `captured_at` optional UTC; `location` optional structured coordinates with accuracy. Reject duplicate item codes. Submission includes all required items; no extra invented checklist code.

`NoticeItemInput` fields: `code` stable within notice; `title`5..200; `description`10..4000; `required` boolean; `finding_id` required for deficiency items tied to a finding; `acceptable_evidence_types` nonempty approved code list; `public_guidance` optional0..2000. The notice response deadline is derived from approved budget, not item-specific arbitrary date strings unless the profile permits them.

Demo checklist:

| Code | Item | Mandatory | Evidence required | NA permitted |
| --- | --- | --- | --- | --- |
| C01 | Means of escape | Yes | Yes | No |
| C02 | Portable fire extinguishers | Yes | Yes | No |
| C03 | Alarm and detection test | Yes | Yes | No |
| C04 | Fire-water and suppression provision | Yes | Yes when applicable | Yes, with rationale and review |
| C05 | Electrical safety documentation | Yes | Accepted document reference | No |
| C06 | Emergency signage and lighting | Yes | Yes | No |
| C07 | Emergency access observations | No | Optional | Yes with rationale |
| C08 | Staff training records | No | Optional | Yes with rationale |

This is a synthetic educational checklist. It is not a complete legal fire inspection standard. Even optional/advisory findings remain visible and may block a specific profile where expressly configured.

## 5. Shared command metadata

Existing resources use If-Match and business commands use Idempotency-Key as defined in [API contracts](06_API_AND_EVENT_CONTRACTS.md). Commands on child resources that change readiness also carry `application_version`. This applies even when their primary DTO below is `Reason`. Server responses return updated child and case versions. Never infer concurrency from client timestamps.

Reasons are meaningful human explanations, not dummy dots used to satisfy a length rule. Use context-specific reason codes plus explanatory text. Public and internal reasons are separate where necessary; no internal note is copied to an applicant notification automatically.

## 6. Input DTO catalogue

### `Empty`

No body fields; send `{}` or no body only when the endpoint explicitly permits it.

### `Reason`

reason: string 10..4000 characters. For case-linked child commands also require application_version: positive integer, as defined in API common rules.

### `OtpStart`

contact: email or E.164 phone string; channel: EMAIL or SMS; purpose: SIGN_IN or CONTACT_CHANGE; locale: en by default. No role or principal_id.

### `OtpVerify`

challenge_id: UUID; code: six ASCII digits. No user, scope or role fields. Challenge binds purpose/contact server-side.

### `Preferences`

locale: supported enabled locale; optional_channels: unique array from EMAIL,SMS; reduced_motion: boolean. Mandatory service messages cannot be disabled.

### `ContactChange`

new_contact: validated email/E.164; channel: EMAIL or SMS; step_up_challenge_id: UUID. Account is current authenticated principal.

### `PremisesCreate`

display_name: 2..160; address_line1: 5..200; address_line2: optional 0..200; locality: 2..100; ward_key: approved key; postal_code: six digits for demo; category_key: approved category; area_sqm: decimal string >0; height_m: decimal string >=0; floor_count: integer 1..300; occupancy_count: optional integer 0..1000000; ownership_basis_document_id: optional accepted document reference where required. Beneficiary/delegation references required only for assisted creation.

### `PremisesPatch`

Only editable fields from PremisesCreate; at least one field; no owner_id, created_at, source authority or historical snapshot fields. Ownership transfer is a separate approved process, not this patch.

### `DelegationCreate`

beneficiary_id: UUID resolved through verified workflow; premises_id: UUID or service_id: UUID as allowed scope; delegate_contact: verified-contact identifier; capabilities: allowlisted applicant operations; effective_from/until: UTC timestamps with finite end; basis_document_id: accepted evidence where required; reason: 10..4000. Proposer cannot self-confirm beneficiary authority.

### `ApplicabilityInput`

premises_id: optional readable UUID; declared_category: approved key; jurisdiction_or_ward_key: key; area_sqm and height_m: decimal strings; occupancy_type: approved key; intended_service_date: optional ISO date. Return uncertainty for unsupported categories, never invent a legal determination.

### `DraftCreate`

service_id: UUID; premises_id: UUID; beneficiary_id: optional UUID only under active delegation; delegation_id: required for assisted action; application_type: NEW or RENEWAL; prior_certificate_id: required for RENEWAL. Server assigns DRAFT and IDs.

### `DraftPatch`

draft_revision: positive integer; form_schema_key: pinned draft schema; fields: validated allowlisted premises/service payload; declaration_drafts: optional list; attachment_links: optional accepted/referenced upload IDs belonging to case. No status, receipt, policy approval or actor fields.

### `Submission`

draft_revision: positive integer; reviewed_policy_version_id: UUID; declaration_acceptances: array of {code,version,accepted:true}; document_version_ids: unique UUID array containing required accepted evidence. Server reselects applicable policy and rejects a changed review expectation.

### `RoutingResolution`

target_jurisdiction_id: UUID; target_queue_id: UUID; routing_artifact_id: UUID; reason: 10..4000; exception_id: current open UUID. Targets must be valid under service authority.

### `InspectionRequest`

purpose: INITIAL; reason: 10..4000; preferred_window_start/end: optional pair of UTC timestamps. Checklist version is server-selected from pinned policy.

### `HoldCreate`

kind: ADMINISTRATIVE or COURT_ORDER; reason: 10..4000; basis_document_id: optional/required by profile; starts_at: UTC; requested_end_at: optional UTC; affected_obligation_ids: unique UUID array; command_block_scope: approved list. Backdated start requires specific authority.

### `UploadReservation`

target_type: APPLICATION_DRAFT,NOTICE_RESPONSE,INSPECTION_EVIDENCE,SUPPORT_ATTACHMENT or POLICY_BASIS; target_id: scoped UUID; original_name: 1..180; media_type: allowed hint; size_bytes: positive integer <= configured bound; sha256: optional 64 lowercase hex; requirement_code/item_code: required for relevant evidence slot. Server generates bucket/key.

### `UploadComplete`

object_version_id: provider opaque reference from reserved upload; sha256: 64 hex; size_bytes: expected positive integer. Server reads/verifies trusted storage metadata; body values alone do not mark file complete.

### `DocumentAccess`

purpose: PREVIEW or DOWNLOAD or PRINT; reason: optional 10..500 when sensitive access requires it. Only the stored original/approved derivative may be accessed; no destination URL.

### `ScheduleCommand`

officer_id: eligible UUID; starts_at/ends_at: UTC with end>start; appointment_timezone: configured service IANA zone; reason: 10..4000; application_version: positive integer. Optional notification_note: public text <=1000.

### `ReassignCommand`

new_officer_id: eligible UUID; reason: 10..4000; application_version: positive integer; starts_at/ends_at: required only if time changes. Recheck all booking constraints.

### `CheckIn`

application_version: positive integer; assignment_version: positive integer; captured_at: UTC; latitude/longitude/accuracy_m: nullable together; location_unavailable_reason: required when location absent; notes: optional <=2000. No fabricated GPS fallback.

### `ReportDraft`

application_version: positive integer; assignment_version: positive integer; checklist_version: expected key; observations: array of Observation; summary: optional <=4000; captured_at: optional UTC; local_revision: optional positive integer. Incomplete observations are allowed only for drafts.

### `FailedVisit`

application_version: positive integer; assignment_version: positive integer; reason_code: SITE_INACCESSIBLE,APPLICANT_UNAVAILABLE,SAFETY_CONCERN,WEATHER,OFFICER_UNAVAILABLE or OTHER; reason: 10..4000; captured_at: UTC; document_version_ids: optional accepted UUID array; suggested_window: optional date interval. Failure is not a completed checklist.

### `ReportSubmit`

application_version: positive integer; assignment_version: positive integer; checklist_version: expected key; observations: complete unique array of Observation; summary: 10..4000; captured_at: UTC or explicit capture_unavailable_reason; declaration_accepted: true; source_operation_id: optional UUID for online/offline relation.

### `SyncOperation`

Common envelope: operation_id UUID; operation_type SUBMIT_INSPECTION_REPORT or RECORD_FAILED_VISIT; inspection_id UUID; application_version/base_inspection_version/assignment_version positive integers; schema_version supported version; captured_at UTC. For SUBMIT_INSPECTION_REPORT require checklist_version, complete observations, summary and declaration_accepted exactly as ReportSubmit. For RECORD_FAILED_VISIT require reason_code, reason, optional accepted document_version_ids and suggested_window exactly as FailedVisit; checklist observations and approval recommendations are forbidden. Idempotency key and operation identity bind unchanged normalized content. Both variants use current authorization, assignment and case-version checks. The response names the accepted report or visit-outcome record, not a fabricated report for a failed visit.

### `ConflictProposal`

application_version: current known integer; operation_id: original UUID; local_manifest: versioned SyncOperation; safe_local_summary: 10..4000; reason: 10..4000. Server records conflict, not active evidence.

### `ConflictResolution`

application_version: current integer; outcome: PROPOSE_NEW_REPORT,REINSPECTION_REQUIRED or DECLINE; reason: 10..4000; selected_evidence_ids: optional accepted UUID array; replacement_assignment_id: optional authorized UUID. A replacement manifest is independently revalidated.

### `NoticeCreate`

type: INFORMATION or DEFICIENCY; public_reason: 10..4000; items: nonempty array of NoticeItemInput; proposed_response_budget_minutes: optional positive integer within approved policy; supersedes_notice_id: optional same-case UUID. Deadlines derived server-side, not arbitrary browser strings.

### `NoticeResponse`

application_version: positive integer; responses: nonempty array of {notice_item_id:UUID,explanation:10..4000,document_version_ids:unique UUID array}; declaration_accepted:true. Response is a new revision; no close-finding field.

### `ItemReview`

application_version: positive integer; response_revision_id: UUID; outcome: ACCEPTED or RETURNED; reason: 10..4000; evidence_refs: accepted UUID array where required. Returned response requires actionable public explanation.

### `FindingVerification`

application_version: positive integer; response_revision_id: UUID or null when permitted direct inspection evidence; outcome: VERIFIED_CLOSED,RETURNED or REINSPECTION_REQUIRED; reason: 10..4000; evidence_document_ids: accepted scoped UUID array; report_id: optional matching inspection report. Reviewer identity is server-owned.

### `ReinspectionRequest`

finding_ids: unique nonempty same-case UUID array; reason: 10..4000; previous_inspection_id: same-case UUID. New attempt number and checklist are server-selected.

### `ReviewReturn`

report_id: same-case UUID; items_requiring_clarification: nonempty code/text array; reason: 10..4000; requires_new_visit: literal true in baseline 2.0. A new physical attempt is required by this baseline; false returns SERVICE_DISABLED until a separately specified, approved no-visit addendum workflow exists. The original accepted report remains immutable. This is different from complete-corrections, which returns a corrected case to review without a new visit.

### `DecisionCommand`

kind: APPROVE or REJECT; submission_revision_id: current accepted UUID; report_id: matching UUID required for favorable department-review decision; reason: 10..4000; public_reason: 10..4000; review_acknowledged:true. No supplied actor/grant/status/certificate number.

### `RenewalCreate`

service_id: enabled UUID; premises_id: readable UUID; declaration_of_current_details: boolean; delegation_id: optional active UUID. Source certificate comes from route; copied fields remain a new editable draft.

### `CertificateStatusCommand`

action: SUSPEND,REINSTATE,REVOKE or SUPERSEDE; effective_at: UTC allowed by profile; reason/public_reason: 10..4000; evidence_document_id: accepted UUID; successor_certificate_id: required for SUPERSEDE. Only currently permitted actions accepted.

### `ExternalRegistration`

source_system: configured key; source_certificate_id: 1..160; source_issuer_reference: verified identifier; source_artifact_document_id: accepted UUID; verification_evidence: approved structured proof; reason: 10..4000. Requires enabled external-registration profile and source validation.

### `EscalationCreate`

reason: 10..4000; requested_level: approved positive integer; next_action: 10..1000. Recipients derive from the escalation policy/duty roster, not arbitrary email addresses.

### `ReadThrough`

through_created_at: UTC; through_id: UUID boundary. Only current recipient notifications at/before the boundary are changed.

### `ExportRequest`

kind: CASES,REPORT,AUDIT or CERTIFICATES; field_set_key: approved key; filters: validated corresponding query schema; purpose: 10..500; format: CSV or approved PDF; as_of: optional requested cutoff bounded by server support. No arbitrary column/SQL list.

### `StaffInvitation`

contact: verified staff email; display_name: 2..160; access_request_id: APPROVED UUID; proposed_oidc_issuer: configured key; intended_role_keys: approved request subset. No automatic certificate decision power.

### `AccessApproval`

approved_access_request_id: UUID; reason: 10..4000. Existing revoked grants remain revoked unless separately approved anew.

### `GrantProposal`

subject_id: UUID; capability: allowlisted key; scope_kind: GLOBAL,JURISDICTION or SERVICE; jurisdiction_id/service_id: required by scope; category_keys: approved subset; effective_from/until: UTC finite interval; access_request_id: approved UUID; reason: 10..4000. No approver field.

### `Availability`

kind: AVAILABLE or UNAVAILABLE; starts_at/ends_at: UTC valid interval; reason_code: approved key; reason: 10..1000. Server returns affected bookings requiring explicit reassignment.

### `PolicyDraft`

service_id: UUID; base_policy_version_id: optional UUID; schema_version: supported; payload: valid versioned policy data; source_references: nonempty array for live, demo marker for demo; reason: 10..4000. Version number server-assigned.

### `PolicyDraftPatch`

payload: complete candidate under schema; reason: 10..4000; source_references: optional updated list. Only editable state; record current principal as material contributor.

### `PolicyApproval`

candidate_sha256: 64 hex; effective_from: UTC; effective_until: optional UTC/null; reason: 10..4000; reviewed_gate_evidence_ids: required for live UUID array. Approver supplied by current session/grant.

### `PolicyActivation`

approved_candidate_sha256: 64 hex; reason: 10..4000. Activation time and eligible interval rechecked server-side; no bypass of approval or future effective date.

### `RecoveryCommand`

reason: 10..4000; acknowledged_risk: boolean; known_provider_reference: optional verified reference for reconciliation. No arbitrary result payload, status override or reset_attempts flag.

### `IntegrationTest`

test_case_key: allowlisted non-destructive scenario; reason: 10..1000. Target URL/credentials come only from approved configuration.

### `PartnerEvent`

source_event_id: 1..160; source_entity_id: 1..160; source_sequence: positive integer when partner supports it; occurred_at: UTC; schema_version: approved; event_type: approved key; payload: validated partner schema. Authentication covers raw bytes/canonical contract as agreed.

### `IntegrationResolution`

outcome: APPLY_VERIFIED_SOURCE,IGNORE_DUPLICATE,REQUEST_RESEND or KEEP_QUARANTINED; reason: 10..4000; authoritative_source_version: required when applying; verification_evidence_refs: nonempty approved set. No invented final status.

### `TicketCreate`

category: HOW_TO,TECHNICAL,ACCESS,DATA_CORRECTION or OTHER; subject: 5..160; description: 10..4000; application_id: optional readable UUID; document_version_ids: optional accepted UUID array. Urgent support is not emergency dispatch.

### `TicketMessage`

body: 1..4000; audience: REQUESTER or INTERNAL, with INTERNAL staff-only; document_version_ids: optional accepted UUID array. Sender and timestamp server-owned.

### `TicketStatus`

state: permitted support state; reason: 10..1000; next_action: optional <=1000. No embedded regulatory case status.

### `AppealCreate`

challenged_decision_id: readable UUID; appeal_profile_version_id: approved UUID; grounds: 20..8000; evidence_document_ids: accepted UUID array; declarations: profile-required acceptance list. Disabled until legal filing rules are configured.

### `AppealDecision`

outcome: approved appeal-remedy enum; reason: 20..8000; public_reason: 10..4000; instrument_document_id: accepted UUID; reviewed_evidence_ids: nonempty UUID list. Separate statutory authority and original-decision preservation required.

### `DeclarationCreate`

obligation_id: readable active UUID; form_schema_key: approved key; fields: validated declaration payload; document_version_ids: accepted UUID array; declaration_accepted:true. Profile-dependent.

### `DemoScenario`

scenario_key: allowlisted fixture scenario; fake_clock_advance_minutes: optional bounded positive integer; provider_fault: optional approved fault enum; confirmation: required exact reset phrase for reset. No arbitrary code, database name or network destination.

### `ListQuery`

cursor: optional opaque string; limit: integer 1..100 default25; search: optional 0..160; sort: approved enum. The server always applies scope.

### `CursorQuery`

cursor: optional opaque string; limit: integer 1..100 default25. No offset drift for live timelines.

### `CaseListQuery`

ListQuery plus status: canonical state array; service_id/jurisdiction_id: permitted UUIDs; category_key: approved enum; submitted_from/to: UTC half-open interval; assigned_to: permitted UUID; include_drafts: boolean only in appropriate user lists.

### `InspectionListQuery`

ListQuery plus state/purpose: approved enum arrays; officer_id: permitted UUID; due_from/to: UTC; appointment_from/to: UTC.

### `ScheduleQuery`

starts_at/ends_at: UTC interval <=31 days; officer_ids: permitted UUID array; timezone: configured display zone. Queries must remain bounded.

### `CertificateListQuery`

ListQuery plus effective_status: ACTIVE,EXPIRED,SUSPENDED,REVOKED,SUPERSEDED; outcome_kind: enum; valid_until_from/to: UTC; source_mode: enum.

### `ObligationQuery`

ListQuery plus state: ACTIVE,PAUSED,SATISFIED,CANCELLED; urgency: DUE_SOON,OVERDUE,ON_TRACK; owner_queue_id: permitted UUID; as_of: optional UTC cutoff.

### `NotificationQuery`

CursorQuery plus unread_only:boolean; category:approved key; created_from/to:UTC.

### `ReportQuery`

service_id:permitted UUID; jurisdiction_id:permitted UUID; category_key:optional approved enum; from/to:UTC half-open interval; source_mode:optional enum; include_imported:boolean; as_of:optional UTC. Definition version is server-owned.

### `AuditQuery`

ListQuery plus actor_id:permitted UUID; action:allowlisted key; entity_type/id:permitted; from/to:UTC; request_id:optional UUID. Sensitive broad searches require purpose/audit grant.

### `StaffQuery`

ListQuery plus active:boolean; role_key:approved key; jurisdiction_id:permitted UUID. No query for secret fields.

### `PolicyQuery`

ListQuery plus service_id:permitted UUID; state:policy enum; effective_on:UTC.

### `JobQuery`

ListQuery plus state:job enum; kind:approved job kind; provider_key:configured key; due_before:UTC.

### `TicketQuery`

ListQuery plus state:support enum; category:approved key; application_id:readable UUID; owner_queue_id:permitted UUID.


## 7. Cross-field rules

Scheduled end must follow start; scheduling and availability are checked together. Coordinates are all present with accuracy or all absent with a reason. Renewal requires a readable source certificate and enabled renewal policy. A favorable decision requires the same accepted submission/report readiness set checked under the application lock. Information notices are valid in SCRUTINY; deficiency notices are valid in REVIEW_PENDING. A response's document and finding references must belong to its exact case and current notice round.

The frontend may present a friendly summary, but the backend recomputes all these rules from canonical data. An ID contained in an allowed dropdown yesterday may be inactive or out of scope today.

## 8. Validation error examples

`/fields/area_sqm` -> Enter an area greater than zero in square metres.  
`/document_version_ids` -> The fire-safety layout is still waiting for a security scan.  
`/observations/0/note` -> Explain the failed means-of-escape observation.  
`/ends_at` -> The appointment must end after it starts.  
`/responses/1/document_version_ids` -> Attach evidence permitted for this notice item.  
`/reviewed_policy_version_id` -> Requirements changed before submission; review the updated checklist.

Errors do not echo submitted secrets or full sensitive values. Stable machine codes drive localized copy, while JSON Pointers attach errors to the correct controls.

## 9. Schema testing and change management

Each DTO has valid, missing-required, wrong-type, unknown-field, oversized-value, cross-scope-reference and boundary tests. Each conditional profile change has fixtures proving the correct required fields before and after activation. Generate or verify frontend form types against the schema; do not maintain an unreviewed second list of mandatory documents inside JSX. A schema version change that affects pending drafts must provide migration/explanation, never erase data silently.


## 10. Policy simulation input and output

### `PolicySimulation`

Input: candidate_sha256 (64 hex, must equal the current candidate), fixture_suite_key (allowlisted server-owned suite), and reason (10..1000 characters). No executable expressions, URLs, user-provided code or live application mutations are accepted. Output `PolicySimulationResult`: simulation_id, candidate_sha256, fixture_suite_version, engine_version, started_at, completed_at, checks[{key,passed,expected,actual,safe_explanation}], passed, and current_candidate_unchanged. A successful response can contain passed=false; it means the simulation ran, not that policy approval is allowed. A stale candidate returns VERSION_CONFLICT. Store failed checks as well as successes.


## 11. Authentication redirect and public catalogue queries

### `OidcStartQuery`

return_to: optional relative route, maximum512 characters, normalized and matched against the allowed application route set; default is the actor's role landing page. Reject scheme, hostname, protocol-relative //, control characters and encoded redirect tricks. No client-provided issuer or redirect_uri is accepted. The response is a302 redirect to the configured provider with state, nonce and PKCE; server session stores the flow and destination.

### `OidcCallbackQuery`

Success requires code and state as bounded opaque strings (maximum4096 and512 characters respectively). The provider may instead return error/error_description; treat these as untrusted text, redact sensitive detail and return a safe sign-in failure. Validate single-use state, issuer/audience/nonce and tokens through the library; never decode claims without validation. The callback must not accept caller-supplied roles, principal IDs or grants. No automatic retry of a consumed authorization code.

### `ServiceCatalogQuery`

jurisdiction_id: optional public catalogue UUID; category_key: optional allowlisted string<=80; locale: en or hi when approved translations are available. Unknown syntax returns MALFORMED_REQUEST; valid unsupported jurisdiction/category returns a bounded catalogue with an explicit unavailable explanation, not a fabricated applicable policy. No identity or confidential building fields are required.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
