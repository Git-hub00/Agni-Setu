# Demonstration data, fixtures and end-to-end scenarios

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Purpose and provenance

Use reproducible synthetic data to verify the same product journeys shown in the HTML prototype. This is not a migration of real applications or evidence of official departmental workload. The 28 names, stages, categories, localities and p1 ownership relationships below are derived from the prototype's literal `fixtures` array. All identifiers in this document are demonstration fixtures.

The source HTML is a visual/interaction reference, not an importable production database. Rebuild valid canonical histories through fixture builders/application services; do not deserialize its localStorage into PostgreSQL. In particular, the source's handcrafted due offsets are illustrative and must not override the new obligation engine.

## 2. Deterministic fixture rules

Reference clock: `2026-09-07T05:00:00Z`, displayed as 10:30 Asia/Kolkata. A fresh reset reproduces this clock and baseline. Stable UUIDs use a namespaced UUID derivation from fixture keys; public references remain the AS-2026 values below. Namespace and seed version are checked into tests, not based on random wall-clock execution.

The example policy is effective from `2026-01-01T00:00:00Z`, deliberately earlier than the oldest baseline receipt. This is an engineering fixture date, not a statutory date. Demo working hours are Monday-Friday 09:00-17:00 Asia/Kolkata with an empty explicit holiday list. Existing histories pin this profile. A second version is created only by a named policy scenario.

Every non-draft case has a valid submitted revision, required clean evidence, policy pin and official-demo receipt. Every later stage has the required prior stage events, valid actor/grant, attempt and accepted report where necessary. COMPLETED rows have decisions, issuance records and exactly one certificate; REJECTED rows have published reasoned decisions; WITHDRAWN rows have an authorized pre-decision withdrawal. Generate age-relative events in chronological order and assert chronology. Do not assign an accepted report before its appointment or receipt.

Use safe generated PDF/PNG/JPEG fixture bytes with recorded hashes. Do not copy SVG evidence samples from the browser prototype into accepted uploaded evidence, because SVG is excluded from the upload policy. Passing scanner fixtures run through the real local scanner in integration tests; malware tests use a recognized harmless antivirus test fixture only in an isolated test environment. Do not distribute live malware.

## 3. Personas and access

| Fixture | Display name | Workspace / function | Boundary |
| --- | --- | --- | --- |
| p1 | Rakesh Mehta | Applicant | Only seven owned baseline records; no staff workspace. |
| o1 | Suresh Yadav | Inspection officer | Only currently assigned inspections plus permitted history. |
| o2 | Priya Nair | Inspection officer | Separate eligible assignment actor; tests cross-officer denial. |
| o3 | Dev Malhotra | Inspection officer | Independent actor for booking and scope tests. |
| o4 | Asha Singh | Inspection officer | Independent field actor; no approval power. |
| u-supervisor | Anita Kapoor | Supervisor | Scoped scrutiny/review and explicit decision/status grants. |
| u-leadership | Neha Bansal | Leadership | Read-only aggregate and approved scoped reporting. |
| u-admin | Arjun Rao | Operations administrator | Prepare policy/provision/recover jobs; no statutory decisions. |
| u-approver | Meera Shah | Policy approver | Independent candidate review; cannot approve own contributed version. |
| public | Anonymous visitor | Public verification | Minimal certificate assertion; no login or private case access. |

Use synthetic email addresses ending in `@example.test`, not the authors' real email addresses. Public identity tests use reserved/local sink contacts. Demo identities authenticate through the actual local identity path. A persona selector only chooses the next demo login target; it never grants an arbitrary production role. Demo OTP is obtained from a local sink, not a fixed code in a live API. More p2-p22 applicants exist only as isolated fixture principals.

## 4. Baseline application inventory

Age is the prototype's relative calendar-day age for scenario naming, not an authoritative service deadline. Rebuild due times from event history and the approved demo policy. Draft age does not start a processing clock.

| Demo reference | Premises | Category | Locality | State | Applicant | Officer | Age days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-2026-1041 | Mehta Family Restaurant | Restaurant | Karol Bagh | INSPECTION_PENDING | p1 | o1 | 8 |
| AS-2026-1042 | Lotus Community Hospital | Hospital | Paharganj | REVIEW_PENDING | p2 | o2 | 14 |
| AS-2026-1043 | Maple Grove School | School | Civil Lines | COMPLIANCE_PENDING | p3 | o1 | 18 |
| AS-2026-1044 | Kaveri Business Centre | Office | Connaught Place | SCRUTINY | p4 | o3 | 4 |
| AS-2026-1045 | Mehta Banquet Studio | Restaurant | Rajendra Nagar | INFO_REQUIRED | p1 | Unassigned | 9 |
| AS-2026-1046 | Bluebird Learning Centre | School | Patel Nagar | INSPECTION_PENDING | p5 | o2 | 6 |
| AS-2026-1047 | Northstar Diagnostics | Hospital | Daryaganj | SUBMITTED | p6 | Unassigned | 1 |
| AS-2026-1048 | Aranya Residency | Residential | Civil Lines | INSPECTION_PENDING | p7 | o3 | 11 |
| AS-2026-1049 | Olive Courtyard Hotel | Hotel | Karol Bagh | REVIEW_PENDING | p8 | o1 | 13 |
| AS-2026-1050 | Mehta Corner Cafe | Restaurant | Patel Nagar | DRAFT | p1 | Unassigned | 0 |
| AS-2026-1051 | Saffron Logistics Hub | Warehouse | Shadipur | SCRUTINY | p9 | o4 | 3 |
| AS-2026-1052 | Cedar Public Library | Office | Daryaganj | COMPLETED | p10 | o4 | 22 |
| AS-2026-1053 | Mehta Market Kitchen | Restaurant | Paharganj | COMPLETED | p1 | o1 | 27 |
| AS-2026-1054 | Aster Care Clinic | Hospital | Rajendra Nagar | INSPECTION_PENDING | p11 | o1 | 7 |
| AS-2026-1055 | Meridian Offices | Office | Connaught Place | APPROVED_PENDING_ISSUE | p12 | o3 | 16 |
| AS-2026-1056 | Brightpath Academy | School | Karol Bagh | SUBMITTED | p13 | Unassigned | 2 |
| AS-2026-1057 | Mehta Events Annex | Restaurant | Shadipur | COMPLIANCE_PENDING | p1 | o2 | 19 |
| AS-2026-1058 | Juniper Suites | Hotel | Paharganj | REVIEW_PENDING | p14 | o4 | 12 |
| AS-2026-1059 | Parkview Apartments | Residential | Patel Nagar | COMPLETED | p15 | o3 | 32 |
| AS-2026-1060 | Horizon Trade Centre | Office | Rajendra Nagar | REJECTED | p16 | o2 | 25 |
| AS-2026-1061 | Mehta Riverside Dining | Restaurant | Daryaganj | COMPLETED | p1 | o1 | 38 |
| AS-2026-1062 | Sunfield Distribution | Warehouse | Shadipur | INSPECTION_PENDING | p17 | o4 | 5 |
| AS-2026-1063 | Veda Learning House | School | Civil Lines | INFO_REQUIRED | p18 | Unassigned | 8 |
| AS-2026-1064 | Mehta New Town Outlet | Restaurant | Rajendra Nagar | SUBMITTED | p1 | Unassigned | 1 |
| AS-2026-1065 | Ashoka Studio Offices | Office | Connaught Place | WITHDRAWN | p19 | o3 | 17 |
| AS-2026-1066 | Willow Health Centre | Hospital | Patel Nagar | SCRUTINY | p20 | o1 | 3 |
| AS-2026-1067 | Silverline Residency | Residential | Karol Bagh | REVIEW_PENDING | p21 | o2 | 15 |
| AS-2026-1068 | Eastgate Meeting House | Office | Paharganj | COMPLETED | p22 | o4 | 42 |

## 5. Count assertions

| State | Expected count |
| --- | --- |
| DRAFT | 1 |
| SUBMITTED | 3 |
| SCRUTINY | 3 |
| INFO_REQUIRED | 2 |
| INSPECTION_PENDING | 5 |
| REVIEW_PENDING | 4 |
| COMPLIANCE_PENDING | 2 |
| APPROVED_PENDING_ISSUE | 1 |
| COMPLETED | 5 |
| REJECTED | 1 |
| WITHDRAWN | 1 |

At baseline: total stored records=28; received applications=27 (exclude unsubmitted DRAFT); open received cases=20; completed=5; rejected=1; withdrawn=1. These sets partition received applications. A withdrawn draft in a separate scenario must remain excluded from received totals. For p1: stored=7, received=6, open received=4, completed=2, draft=1. Queue counts apply current role/scope before pagination. Labels must identify whether "Total" means records or received applications.

Do not seed a dashboard's counts separately. Compute all results from the same canonical dataset/cutoff, and compare against these assertions. Overdue counts require the fixture builder's pinned calendar and reconstructed stage history; never preserve the source HTML's arbitrary deadline offsets as legal SLA data.

## 6. Baseline certificate inventory

| Demo certificate | Case | Effective display at reference clock | Special behavior |
| --- | --- | --- | --- |
| AGNI-DEMO-2026-112 | AS-2026-1052 Cedar Public Library | ACTIVE | Normal active verification |
| AGNI-DEMO-2026-113 | AS-2026-1053 Mehta Market Kitchen | ACTIVE | Expiry 25 days after reference clock; renewal demonstration |
| AGNI-DEMO-2026-119 | AS-2026-1059 Parkview Apartments | ACTIVE | Separate holder/scope test |
| AGNI-DEMO-2026-121 | AS-2026-1061 Mehta Riverside Dining | EXPIRED | Recorded administrative state ACTIVE, interval expired two days before cutoff |
| AGNI-DEMO-2026-128 | AS-2026-1068 Eastgate Meeting House | REVOKED | Explicit revocation instrument, never treated as merely missing |

Use the same issue-time-to-expiry relation required by each pinned fixture profile. The expired sample uses a specifically named historical short-validity demo profile, not arbitrary contradictory dates under the 365-day profile. Use a distinct archived demo service key `demo-historical-restaurant` for this case, with its own short-validity30-day profile effective before the receipt. Its live intake is disabled; other cases use the regular service. The case pins that historical profile and issues32 days before the reference clock, expiring2 days before it. Scope therefore cannot overlap the regular service profile. This isolated historical fixture profile is test data only. Alternatively reconstruct a historically older receipt in an explicit overlay; do not silently mutate the listed relative-age baseline.

Generate a distinct opaque verification token per certificate. Every sample PDF says DEMONSTRATION - NOT A VALID GOVERNMENT CERTIFICATE. The certificate number is a human reference; the public API's lookup token is not a sequential case identifier. Suspension and supersession are scenario overlays on a fresh database, keeping baseline count=5.

## 7. Clock oracle fixtures

`CLOCK-01`: one WORKING obligation starts Friday 2026-09-04 16:00 IST, budget 120 minutes; no holiday or pause. Expected due Monday 2026-09-07 10:00 IST. At Friday17:00 consumed60; Monday09:30 consumed90; Monday10:00 consumed120. A weekend is not charged.

`CLOCK-02`: CALENDAR obligation starts Friday16:00 IST with120 minutes; due Friday18:00 IST regardless of office hours.

`CLOCK-03`: WORKING obligation starts Monday09:00 with120 minutes; permitted pause09:30-10:30 and overlapping pause10:00-11:00 have a union of90 minutes. Expected due12:30 IST, not13:00. At11:00 consumed30. A pause must name an allowed reason and applicable obligation; case-wide age remains visible.

`CLOCK-04`: complete and then re-enter a review stage. New stage instance has new obligation/threshold identities; the case-wide clock and old breach history remain. Reassignment without re-entry creates no new stage cycle.

`CLOCK-05`: advance beyond several thresholds while scanner is down. Recovery produces each required logical action once in order, with scheduled-for time separate from processed-at. Backlog catch-up does not claim on-time delivery.

## 8. Demonstration and end-to-end scenario scripts

Each scenario starts with a fresh isolated seed unless it explicitly continues DS-01. The expected result must be checked in browser, API and canonical data where applicable. Do not call a scenario passed merely because a button is clickable.

| Scenario | Story | Actions | Expected canonical result | Trace |
| --- | --- | --- | --- | --- |
| DS-01 | Clean end-to-end approval | Create a new Restaurant draft as Rakesh; finish required accepted documents; submit; Anita starts scrutiny and schedules Suresh; Suresh records all required observations/evidence; Anita reviews and approves; worker publishes sample PDF; public verifies token. | One receipt, one decision, one demo certificate and consistent cross-role timeline. Refresh each workspace and query the database, not only toast messages. | FR-04, FR-06, FR-13, FR-20, FR-21, FR-22 |
| DS-02 | Missing and unsafe evidence | Use Mehta Corner Cafe DRAFT. Try submit with missing required file, oversized file, false MIME and scanner-pending file. Then replace with safe files. | No official receipt until complete. Rejected bytes never become evidence; corrected draft can submit once. | FR-04, FR-05, FR-06 |
| DS-03 | Information request and returned response | Open Mehta Banquet Studio as applicant. Read the published items; upload a response. Reviewer returns one item with reason; applicant replaces only that response; reviewer accepts every required item. | History includes each response revision; same case resumes SCRUTINY. Applicant cannot accept their own response. | FR-15, FR-16 |
| DS-04 | Deficiencies and verified closure | Use Mehta Events Annex. Try favorable decision while mandatory finding open. Applicant supplies corrections; supervisor verifies per item and selects Return to review. | Approval stays blocked until actual verified closure; return-review maps complete-corrections, not report editing. | FR-14, FR-17, FR-20 |
| DS-05 | Physical reinspection | Use Maple Grove School. Reviewer determines corrective evidence requires a new site visit, creates new attempt and schedules a different eligible officer. | Earlier report/failed items remain immutable; new attempt linked to findings; elapsed case age is preserved. | FR-11, FR-13, FR-17 |
| DS-06 | Inaccessible site online | Open Aster Care Clinic assigned visit; record SITE_INACCESSIBLE with narrative. | FAILED attempt plus owned next-action task; no rejection or successful checklist; a new attempt can be scheduled. | FR-11 |
| DS-07 | Offline report with lost acknowledgment | Prepare Mehta Family Restaurant package; disconnect; complete local observations; reconnect, upload and wait for scanning; drop first accepted HTTP response; sync same operation again. | One accepted immutable report and one canonical receipt. Browser distinguishes local saved, waiting and accepted. | FR-12, FR-13 |
| DS-08 | Offline failed visit | Prepare Bluebird Learning Centre package; disconnect and record failed visit; reconnect and repeat sync. | One VISIT_OUTCOME receipt and rescheduling task, not a fabricated report; current case remains INSPECTION_PENDING. | FR-11, FR-12 |
| DS-09 | Reassignment conflict | Download a package as Suresh; supervisor reassigns it to Priya; Suresh reconnects with local work. | Old operation cannot submit. Safe conflict recovery preserves attribution and does not restore old authority. | FR-08, FR-12, FR-13 |
| DS-10 | Scheduling race | Two supervisors concurrently book same eligible officer for overlapping ranges on different cases. | One database booking succeeds; other gets APPOINTMENT_CONFLICT. Calendar refresh offers alternatives. | FR-08, FR-11 |
| DS-11 | Routing exception | Use Brightpath Academy routing exception; open queue and attempt decision or random assignment before resolution. Resolve with reviewed mapping. | Visible accountable exception; no arbitrary routing; clock continues while correct mapping is chosen. | FR-07 |
| DS-12 | Reminder and escalation under restarts | Use focused CLOCK-01 fixture. Advance demo clock across reminder then breach while restarting scanner/worker and replaying messages. | One logical threshold action per cycle. Repeated provider attempts are recorded but do not duplicate business escalation. | FR-18, FR-19, FR-23 |
| DS-13 | Notification outage | Disable local notification provider, submit eligible command, then restore provider and recover job. | Case transaction remains accepted; notification is PENDING/FAILED until actual delivery result, not falsely sent. | FR-19, FR-23 |
| DS-14 | Renderer failure and recovery | Use Meridian Offices APPROVED_PENDING_ISSUE. Fail isolated rendering, inspect logical job, restore and retry. | Same decision, issuance reservation and verification token; one final artifact/certificate after recovery. | FR-21, FR-29 |
| DS-15 | Unknown external signing outcome | Sandbox signer accepts stable request then connection drops. Attempt blind retry, reconcile by provider reference. | Unknown outcome remains blocked for blind repeat; reconcile retrieves exactly one matching signed artifact. No claim of live legal signing. | FR-21, FR-29 |
| DS-16 | Verification status matrix | Verify three active baseline certificates, Mehta Riverside expired and Eastgate revoked. Overlay suspend/supersede fixtures separately; stop source and mark data stale. | ACTIVE only with current authoritative basis; expired, revoked, suspended, superseded, unknown and unavailable are visibly different. | FR-22, FR-24 |
| DS-17 | Renewal without extension | Start renewal for Mehta Market Kitchen. Leave DRAFT; then finish new application under current profile. | Original validity does not extend on draft/submission; linked new record preserves source certificate and current policy. | FR-24 |
| DS-18 | Independent policy governance | Arjun drafts changed policy, runs simulation and submits. Try self-approval; Meera reviews and approves. Attempt activation overlap and stale candidate approval. | Self/stale/overlap blocked. New submissions use new active version; existing case pins remain unchanged. | FR-03, FR-27 |
| DS-19 | Revocation race | Race a staff deactivation or grant revocation with report/decision command in a real PostgreSQL concurrency test. | Serialized before/after authority boundary; no stale-session acceptance after revocation wins. Pending work remains owned. | FR-02, FR-08, FR-20 |
| DS-20 | Metrics and safe exports | Run full-scope and p1 filters at fixed cutoff; request reports and export with purpose; revoke access before download. | Counts reconcile; filters/purpose/cutoff recorded; unauthorized download denied even if artifact was already generated. | FR-25, FR-26, FR-28 |
| DS-21 | Support and withdrawal | Applicant opens support ticket, receives attributed response; withdraw an allowed-stage case. Try withdraw after approval. | Support reply does not overturn decision; allowed withdrawal closes work explicitly; disallowed state returns INVALID_TRANSITION. | FR-30 |
| DS-22 | Unexpected error and safe recovery | Inject exception before commit, after commit, during outbox dispatch and during artifact promotion. | Before commit rolls back; after commit resolves same receipt; user gets safe reference ID; no manual SQL status patch. | FR-06, FR-21, FR-29 |
| DS-23 | Mobile and accessibility | Navigate applicant wizard, officer report and supervisor review at 360px and keyboard-only; deny camera/GPS; use screen reader on validation errors. | Accessible alternative controls, error summary and meaningful save states; no hidden required action or invented coordinates. | FR-05, FR-12, FR-13 |
| DS-24 | Conditional and disconnected integrations | Open external ownership preview and disabled appeal/payment/declaration route. Replay signed duplicate and out-of-order sandbox source events. | Unsupported live service stays disabled/referral-only; inbox deduplicates and sequence gaps need owned reconciliation. | FR-24, FR-29, FR-30 |

## 9. Seed and reset implementation contract

Implement `python manage.py seed_demo --scenario baseline --require-demo --clock 2026-09-07T05:00:00Z` at B06, extending through later phases. Before B06 it is a planned command, not an existing runnable utility. It refuses non-demo settings/database, requires an empty namespaced seed or idempotent fixture reconciliation, and never deletes arbitrary user data. `--reset` requires explicit confirmation of database identity and backs up permitted demo changes when requested. Tests use a separate randomly named Compose project/database.

An admin-only demo API accepts allowlisted scenario names, clock offsets and recovery toggles; it is not registered at all in live mode. No arbitrary SQL, shell command, remote URL or raw status value is accepted. Full sample-state export is demo-only and redacts contacts, secrets and raw upload bytes. A test-only mutable clock is injected through ClockPort; live processes use authoritative server time.

Acceptance: running seed twice without reset creates no duplicate users, receipt numbers, evidence, certificates or jobs. Reset plus rebuild restores the exact 28/27/20/5/1/1 oracles. A seeding error rolls back the affected fixture graph, records the failed key and exits nonzero rather than leaving an apparently complete dashboard.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
