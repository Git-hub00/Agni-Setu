# Requirements, screens, contracts and build traceability

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Traceability contract

Use requirement IDs in implementation comments only where they clarify a rule, in PR descriptions, test names/markers and release evidence. A feature is not done because a screen exists. It must satisfy its rule, current authorization, persistence, error/recovery, accessibility and operational evidence. Every requirement below maps to at least one API, screen, module, build phase and six specified acceptance checks.

The canonical source of behavior is functional document01 plus workflow document02. Contracts06 and schemas24 define transport/validation. A contradiction is a tracked specification issue to resolve explicitly; agents must not choose whichever rule is easiest to implement.

## 2. Functional traceability

| Requirement | Capability | Module | Screens | API IDs | Build | Acceptance |
| --- | --- | --- | --- | --- | --- | --- |
| FR-01 | Applicant identity and account recovery | identity | UI-02, UI-03 | API-001, API-002, API-003, API-006, API-007, API-009 | B03 | AT-01-01 through AT-01-06 |
| FR-02 | Staff provisioning and account lifecycle | identity | UI-21 | API-004, API-005, API-087, API-088, API-089, API-090, API-091, API-092, API-093 | B03 | AT-02-01 through AT-02-06 |
| FR-03 | Service applicability and premises | policies | UI-04, UI-06 | API-010, API-011, API-013, API-018, API-019 | B04 | AT-03-01 through AT-03-06 |
| FR-04 | Draft creation and editing | cases | UI-05, UI-06 | API-021, API-023 | B05 | AT-04-01 through AT-04-06 |
| FR-05 | Document and evidence intake | documents | UI-06, UI-08, UI-12 | API-033, API-034, API-035, API-036, API-037 | B05 | AT-05-01 through AT-05-06 |
| FR-06 | Atomic application submission | cases | UI-06, UI-07 | API-024, API-026 | B06 | AT-06-01 through AT-06-06 |
| FR-07 | Jurisdiction routing and exceptions | routing | UI-09, UI-15 | API-027, API-028 | B06 | AT-07-01 through AT-07-06 |
| FR-08 | Assignment and reassignment | inspections | UI-10, UI-11, UI-21 | API-041, API-042, API-094 | B07 | AT-08-01 through AT-08-06 |
| FR-09 | Case visibility and timeline | cases | UI-05, UI-07, UI-09 | API-020, API-022, API-025 | B06 | AT-09-01 through AT-09-06 |
| FR-10 | Assisted intake and delegation | identity | UI-03, UI-04, UI-06 | API-012, API-014, API-015, API-016, API-017 | B04 | AT-10-01 through AT-10-06 |
| FR-11 | Appointments and visit outcomes | inspections | UI-10, UI-11, UI-12 | API-029, API-038, API-040, API-043, API-044, API-046 | B07 | AT-11-01 through AT-11-06 |
| FR-12 | Offline drafts and explicit synchronization | offline | UI-12, UI-13 | API-048, API-049, API-050 | B11 | AT-12-01 through AT-12-06 |
| FR-13 | Versioned inspection report and provenance | inspections | UI-12, UI-14 | API-039, API-045, API-047, API-051, API-052, API-063 | B08 | AT-13-01 through AT-13-06 |
| FR-14 | Deterministic checklist evaluation | inspections | UI-12, UI-14 | API-059 | B08 | AT-14-01 through AT-14-06 |
| FR-15 | Information requests and deficiency notices | notices | UI-08, UI-14 | API-053, API-054, API-055 | B09 | AT-15-01 through AT-15-06 |
| FR-16 | Applicant response versions | notices | UI-08 | API-056, API-057 | B09 | AT-16-01 through AT-16-06 |
| FR-17 | Verification, return and reinspection | notices | UI-08, UI-14 | API-058, API-060, API-061, API-062 | B09 | AT-17-01 through AT-17-06 |
| FR-18 | Persistent stage and case clocks | obligations | UI-15 | API-031, API-032, API-074, API-075 | B10 | AT-18-01 through AT-18-06 |
| FR-19 | Reminders and accountable escalation | obligations | UI-15, UI-19, UI-20 | API-076, API-077, API-103, API-105 | B10 | AT-19-01 through AT-19-06 |
| FR-20 | Guarded decisions and authority | decisions | UI-14 | API-064, API-065, API-066 | B12 | AT-20-01 through AT-20-06 |
| FR-21 | Issuance and external registration | certificates | UI-16, UI-17 | API-067, API-069, API-072 | B12 | AT-21-01 through AT-21-06 |
| FR-22 | Privacy-safe public verification | certificates | UI-01, UI-18 | API-073 | B12 | AT-22-01 through AT-22-06 |
| FR-23 | Notifications and delivery visibility | notifications | UI-19, UI-20 | API-008, API-078, API-079, API-080, API-104 | B10 | AT-23-01 through AT-23-06 |
| FR-24 | Certificate lifecycle and continuing obligations | certificates | UI-16, UI-17, UI-15 | API-068, API-070, API-071, API-119 | B13 | AT-24-01 through AT-24-06 |
| FR-25 | Operational dashboards and metrics | reporting | UI-09, UI-15, UI-22 | API-081 | B14 | AT-25-01 through AT-25-06 |
| FR-26 | Controlled exports | reporting | UI-05, UI-22, UI-23 | API-082, API-083, API-084 | B14 | AT-26-01 through AT-26-06 |
| FR-27 | Policy and master-data governance | policies | UI-24 | API-095, API-096, API-097, API-098, API-099, API-100, API-101, API-102, API-123 | B04 | AT-27-01 through AT-27-06 |
| FR-28 | Business and sensitive-access audit | audit | UI-23 | API-085, API-086 | B02 | AT-28-01 through AT-28-06 |
| FR-29 | Integration ownership and reconciliation | integrations | UI-20, UI-25 | API-106, API-107, API-108, API-109, API-110, API-111, API-120, API-121, API-122 | B15 | AT-29-01 through AT-29-06 |
| FR-30 | Support, withdrawal and profile-dependent appeals | support | UI-26, UI-07 | API-030, API-112, API-113, API-114, API-115, API-116, API-117, API-118 | B13 | AT-30-01 through AT-30-06 |

## 3. Workflow transition traceability

| Transition | Command | From | To | Required guard | Event |
| --- | --- | --- | --- | --- | --- |
| TR-01 | submit | DRAFT | SUBMITTED | Editable owner; complete revision; clean required files; active profile; receipt and obligations atomic | application.submitted.v1 |
| TR-02 | start-scrutiny | SUBMITTED | SCRUTINY | Scoped reviewer and accountable review queue | scrutiny.started.v1 |
| TR-03 | request-information | SCRUTINY | INFO_REQUIRED | At least one itemized completeness requirement; due basis; publish permission | notice.published.v1 |
| TR-04 | accept-information | INFO_REQUIRED | SCRUTINY | Every required response verified accepted; current notice round | information.accepted.v1 |
| TR-05 | require-inspection | SCRUTINY | INSPECTION_PENDING | Completeness accepted; service requires visit; route resolved | inspection.requested.v1 |
| TR-06 | accept-report | INSPECTION_PENDING | REVIEW_PENDING | Assigned actor; accepted immutable report; current schema and evidence | inspection.report_accepted.v1 |
| TR-07 | issue-deficiencies | REVIEW_PENDING | COMPLIANCE_PENDING | Itemized findings and notice; owner and response obligation | deficiencies.published.v1 |
| TR-08 | complete-corrections | COMPLIANCE_PENDING | REVIEW_PENDING | All mandatory findings verified closed; no reinspection outstanding | compliance.verified.v1 |
| TR-09 | require-reinspection | COMPLIANCE_PENDING | INSPECTION_PENDING | Reason, linked findings and new attempt; preserve existing case clock | inspection.reinspection_requested.v1 |
| TR-10 | approve | REVIEW_PENDING | APPROVED_PENDING_ISSUE | Effective decision authority; version fence; required evidence and findings cleared | decision.approved.v1 |
| TR-11 | publish-instrument | APPROVED_PENDING_ISSUE | COMPLETED | Required artifact and signature verified; stable issuance ID; registry atomic | certificate.published.v1 |
| TR-12 | reject | SCRUTINY, INFO_REQUIRED, REVIEW_PENDING, COMPLIANCE_PENDING | REJECTED | Profile explicitly permits this stage and reason; effective authority; notice obligations met | decision.rejected.v1 |
| TR-13 | withdraw | DRAFT, SUBMITTED, SCRUTINY, INFO_REQUIRED, INSPECTION_PENDING, COMPLIANCE_PENDING | WITHDRAWN | Profile permits withdrawal stage; authorized request; no active approval; obligation disposition | application.withdrawn.v1 |
| TR-14 | return-for-clarification | REVIEW_PENDING | INSPECTION_PENDING | Supervisor records report clarification request and creates a new permitted attempt/addendum task | inspection.clarification_requested.v1 |
| TR-15 | register-external | SCRUTINY, REVIEW_PENDING | COMPLETED | External-registration profile enabled; issuer authority and source artifact verified; outcome REGISTERED_EXTERNAL | certificate.external_registered.v1 |

## 4. Screen traceability

| Screen | Route | Name | Reader scope | Requirements | Module |
| --- | --- | --- | --- | --- | --- |
| UI-01 | / | Public service entry | Public | FR-03, FR-22 | public |
| UI-02 | /sign-in | Applicant OTP / staff sign-in | Public | FR-01, FR-02 | identity |
| UI-03 | /account | Account, contacts and delegations | Authenticated | FR-01, FR-10 | identity |
| UI-04 | /premises | Premises and authorized representatives | Applicant | FR-03, FR-10 | cases |
| UI-05 | /applications | Application list and saved filters | Applicant, Officer, Supervisor, Leadership | FR-04, FR-09, FR-26 | cases |
| UI-06 | /applications/new and /applications/:id/edit | Application wizard | Applicant / representative | FR-03, FR-04, FR-05, FR-06 | cases |
| UI-07 | /applications/:id | Case detail, evidence and timeline | Scoped readers | FR-09, FR-20, FR-30 | cases |
| UI-08 | /applications/:id/notices/:noticeId | Information and deficiency responses | Applicant / scoped reviewer | FR-15, FR-16, FR-17 | notices |
| UI-09 | /overview | Role-specific overview | Applicant, Supervisor, Leadership | FR-07, FR-09, FR-25 | reporting |
| UI-10 | /inspections | Assigned and supervised inspection queue | Officer, Supervisor | FR-08, FR-11 | inspections |
| UI-11 | /schedule | Appointment calendar and assignment dialog | Officer, Supervisor | FR-08, FR-11 | inspections |
| UI-12 | /inspections/:id | Inspection workspace and report | Assigned officer / scoped reader | FR-05, FR-11, FR-12, FR-13, FR-14 | inspections |
| UI-13 | /sync | Offline work and conflict resolution | Officer | FR-12, FR-13 | offline |
| UI-14 | /reviews and /applications/:id/review | Evidence review and decision | Supervisor with authority | FR-14, FR-15, FR-17, FR-20 | decisions |
| UI-15 | /monitoring | Obligations, exceptions and escalation | Supervisor, Leadership | FR-18, FR-19, FR-24, FR-25 | obligations |
| UI-16 | /certificates | Certificate register | Scoped readers | FR-21, FR-24 | certificates |
| UI-17 | /certificates/:id | Certificate details and lifecycle | Holder / authority / scoped reader | FR-21, FR-24 | certificates |
| UI-18 | /verify and /verify/:token | Public verification result | Public | FR-22 | certificates |
| UI-19 | /notifications | Personal notifications and preferences | Authenticated | FR-19, FR-23 | notifications |
| UI-20 | /operations | Jobs, delivery failures and recovery | Operations administrator | FR-19, FR-23, FR-29 | operations |
| UI-21 | /team | Staff, grants and assignment availability | Admin / supervisor scoped view | FR-02, FR-08 | identity |
| UI-22 | /reports | Metrics, reports and export jobs | Supervisor, Leadership | FR-25, FR-26 | reporting |
| UI-23 | /audit | Audit event search and details | Scoped auditor | FR-26, FR-28 | audit |
| UI-24 | /policies and /policies/:id | Policy versions, review and activation | Admin, Policy approver, scoped readers | FR-03, FR-27 | policies |
| UI-25 | /integrations | Provider configuration and reconciliation | Operations administrator | FR-29 | integrations |
| UI-26 | /support and /support/:id | Help, tickets, referrals and permitted appeals | Authenticated; public help only | FR-30 | support |
| UI-27 | /settings | Personal and permitted operational settings | Authenticated | FR-01, FR-23 | identity |
| UI-28 | /demo | Demonstration controls and walkthrough | Demo-only authorized operator | FR-12, FR-19, FR-29 | demo |

## 5. Build dependency traceability

| Phase | Purpose | Depends on | Deliverable |
| --- | --- | --- | --- |
| B00 | Baseline and dependency lock | None | Inspect repository, preserve user work, approve stack ADRs, record exact package/image versions and local environment. |
| B01 | Repository and runnable skeleton | B00 | Create Django/React workspaces, Compose infrastructure, health probes and reproducible task commands. |
| B02 | Domain persistence and command kernel | B01 | Create foundational migrations, authorization fences, command receipts, audit, outbox and deterministic clock tests. |
| B03 | Identity, sessions and scoped permissions | B02 | Implement applicant OTP, staff OIDC, approved grants, anti-abuse, CSRF and cross-user access tests. |
| B04 | Service policy and master data | B03 | Build immutable policy packages, independent approval, applicability, routing versions and premises delegation. |
| B05 | Drafts, files and application wizard | B04 | Build real server drafts, versioned documents, quarantined uploads, scan jobs and accessible wizard. |
| B06 | Submission, routing and case visibility | B05 | Commit atomic submission and receipt, route exceptions, case lists and audience-filtered timeline. |
| B07 | Assignment and appointment management | B06 | Create inspection attempts, availability checks, conflict-safe booking, cancellation and failed-visit flows. |
| B08 | Inspection reports and checklist evaluation | B07 | Implement observations, evidence, immutable report revisions and deterministic mandatory blockers. |
| B09 | Notices, responses and correction cycles | B08 | Build itemized information and deficiencies, response versions, verification and reinspection. |
| B10 | Clocks, outbox dispatch and notifications | B09 | Deliver persistent obligation calculations, unique escalation actions, retry-safe jobs and delivery tracking. |
| B11 | Offline field application | B10 | Installable PWA, minimum local packages, explicit synchronization and version/authority conflict workflows. |
| B12 | Decisions, issuance and verification | B11 | Implement guarded decisions, durable sample issuance, registry, status-safe verification and signer adapter boundary. |
| B13 | Lifecycle, support and conditional routes | B12 | Build renewal and status instruments, support, withdrawal, hold controls and disabled/referral appeal pathways. |
| B14 | Reporting, audit and operational UI | B13 | Build reconciled metrics, scoped exports, read auditing, job recovery and responsive role workspaces. |
| B15 | Integration contracts and reconciliation | B14 | Implement local simulators, signed partner inbox, ownership rules, ordered processing and controlled reconciliation. |
| B16 | Security and accessibility hardening | B15 | Validate threat scenarios, accessible journeys, browser matrix, uploads, identity revocation and secrets scans. |
| B17 | Reliability, performance and recovery proof | B16 | Run concurrency/fault/load suites, object/database recovery drill and measurement reports. |
| B18 | Production packaging and release evidence | B17 | Create hardened images, CI/CD approvals, upgrade/rollback runbooks, SBOM and release evidence. |
| B19 | Full demonstration acceptance | B18 | Validate all role journeys and mapped prototype controls with deterministic fixtures; fix and retest defects. |
| B20 | Agency pilot activation | B19 | Complete legal/policy/integration/security/operations approvals before any official live case or certificate. |

## 6. Release-level nonfunctional gates

| Gate | Required proof | Primary documents | Build phase |
| --- | --- | --- | --- |
| Integrity | Real PostgreSQL constraint, transaction, concurrency and replay tests | 02,04,05,06,08,11 | B02-B12,B17 |
| Access/privacy | Actor/scope/state/grant checks on APIs, artifacts and exports; revoked-session tests | 07,11,19 | B03,B16 |
| Offline reliability | Supported device/browser and explicit queue tests, including failed visits/conflicts | 09,11,23 | B11,B16 |
| Accessibility | Keyboard, screen-reader, contrast and responsive manual plus automated checks | 03,11 | B16,B19 |
| Performance | Measured target workload, cutoff, hardware, latency and error-rate report | 04,11,12 | B17 |
| Recovery | Broker/worker outage and database/object restore evidence | 08,11,12 | B17 |
| Supply chain | Reviewed locks, image digests, SBOM, dependency scan, secrets scan | 10,18 | B00,B18 |
| Live service authorization | Signed off applicability, fees, checklists, authority and certificate/signing/records requirements | 16,19 | B20 |

## 7. Definition of coverage complete

No functional row lacks an API, screen, task or acceptance suite. No source action in document23 is unclassified. No new API has an undeclared input schema, capability or failure behavior. Tests with BLOCKED/NOT_RUN remain visible and prevent a release claim for affected mandatory scope. Approved deferred conditional capabilities must remain explicitly disabled, with safe user guidance, until their release gate is satisfied.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
