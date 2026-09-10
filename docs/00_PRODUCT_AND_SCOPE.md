# Product, business scope and release boundaries

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Product definition

Agni Setu is the case-management and monitoring system for fire-department applications described by SIH 2024 problem statement 1623. It connects an application to its evidence, responsible queue, inspection attempts, required follow-up, authorized outcome and certification record. The product is not an emergency-dispatch or fire-detection system.

At any point, an open case must answer: **what is pending, who owns it, when it is due, what evidence supports it, and what happens if nobody acts?** Automation performs validation, routing, monitoring, reminders and durable processing. A qualified authorized person remains responsible for physical inspection and regulatory judgement.

The source baseline is the supplied `Agni_Setu_Project_Specification.docx`, sections 01-43, and the supplied interactive HTML prototype. This package elaborates those requirements into a build contract. It deliberately replaces the earlier Flask/MongoDB implementation recommendation with the Django/PostgreSQL architecture in [the architecture decisions](14_ARCHITECTURE_DECISIONS.md). This is a newly recommended engineering decision, not a claim that the previous documents already selected that stack. The original prototype remains a visual and interaction reference, not reusable production security or storage code.

## 2. Business requirements

| ID | Requirement | Observable acceptance |
| --- | --- | --- |
| BR-01 | End-to-end accountability | Every submitted open case has an active duty queue, next action and deadline or explicit policy reason why no deadline applies. |
| BR-02 | Automatic follow-up | Overdue obligations produce persisted reminders and intervention tasks even after scheduler restart. |
| BR-03 | Evidence-bound outcomes | Decisions reference immutable submission, report, finding set, policy and effective authority. |
| BR-04 | Applicant transparency | A permitted applicant sees the receipt, published progress and exactly what response is needed. |
| BR-05 | Accessible and fair service | Core tasks work on mobile and keyboard; assisted intake records both operator and beneficiary. |
| BR-06 | Safe continuity | Duplicate requests, disconnection and worker crashes do not silently lose accepted business work. |
| BR-07 | Reliable evaluation | Reports reconcile at a stated cutoff and separate processing, applicant waiting and technical failure. |
| BR-08 | Sustainable ownership | The operator has documentation, source, exports, recovery evidence and a supported dependency inventory. |

These are required capabilities and acceptance objectives, not measured improvements. No claim of faster approvals, prevented fires or eliminated corruption is warranted without a real baseline and pilot study.

## 3. Seven workspaces and actual authority

| Workspace | Principal purpose | Explicit restriction |
| --- | --- | --- |
| Applicant | Own premises, drafts, submissions, notices, certificates and support | Cannot edit received evidence or other applicants' records. |
| Inspection officer | Assigned visits, observations, evidence, reports and offline work | Cannot self-approve an outcome merely by completing a checklist. |
| Supervisor / decision authority | Scrutiny, routing, assignments, review, decisions and escalation | Every action still requires a service/jurisdiction-specific effective grant. |
| Leadership | Read-only departmental oversight and authorized reports | No hidden mutation or all-data access simply because the user is senior. |
| Operations administrator | Technical health, jobs, staff provisioning and policy preparation | Cannot grant themselves decision power or alter regulatory outcomes. |
| Policy approver | Independently approve or return policy packages | Cannot approve a package they prepared or materially edited. |
| Public verification | Inspect the permitted certificate status subset | No application search, applicant contact details or inspection-file access. |

A representative is a delegation relationship, not an eighth unrestricted role. A helpdesk operator is a scoped capability of an approved staff identity. Workspaces organize navigation; backend capability, scope, assignment and authority checks authorize actions.

## 4. Delivery levels

### Level D: fully functioning demonstration build

Build the complete standalone department-review workflow with real API, PostgreSQL persistence, private object storage, real server authorization, scanning, background jobs, offline handling, reports and automated tests. Use synthetic fixtures and visibly watermarked sample certificates. Local provider simulators are allowed only through named adapters and must expose simulated results. A button that only displays a success toast without changing its intended data is not an implementation.

The initial default is one synthetic jurisdiction and a department-review service. Preserve the seven workspaces and core prototype journeys. The demonstration includes all eleven application states, failure recovery, policy approval and certificate status examples. The development target is functional completeness of this defined scope, not public deployment permission.

### Level P: agency-approved pilot

Requires the completed demonstration capabilities plus approved live service profile, real authoritative identity and integrations, signed certificate mechanism or approved external registration, validated records schedule, device policy, accessibility review, security review, recoverability evidence and named operators. A required legal step cannot be bypassed just because the provider is not ready.

### Level E: conditional service extensions

Externally issued certification registration, legally filed appeals, statutory payments, continuing declarations and partner-owned case monitoring are disabled until their complete contracts and applicable policy are approved. The code must contain well-defined interfaces and disabled-state UX. They become mandatory end-to-end capabilities for any live service that depends on them. Disabled means unavailable with an explanation, not apparently working against a fake provider.

## 5. Source ownership and service mode

Each service configuration has a mode: `DEMO`, `STANDALONE` or `INTEGRATED_MONITORING`. `DEMO` cannot publish official instruments. `STANDALONE` accepts original cases only when authorized. `INTEGRATED_MONITORING` stores approved projections of partner-owned cases and sends only explicitly permitted commands. It must never allocate a competing official source reference or manufacture a partner acknowledgement.

Ownership is field-level in an integration mapping. For example, an external source may own submission and final status while Agni Setu owns local follow-up tasks. Source sequence and evidence provenance must be preserved. Screen copy states which system owns an outcome.

## 6. What is not part of the first build

Do not implement AI/LLM approval, predictive safety scores, CCTV detection, IoT alarms, emergency dispatch, building-plan approval, treasury settlement, native apps, multi-state billing or a generic visual workflow-builder. Do not introduce Kubernetes, Kafka, a data warehouse or multiple business databases without a measured requirement and a reviewed architecture decision.

No Aadhaar number or compulsory Aadhaar-linked identity is required by this engineering baseline. Do not invent a legal requirement for it. Do not reproduce an official government emblem, official signature or live agency branding without permission.

## 7. Fixed engineering defaults versus policy

Engineering defaults such as a 10 MiB file limit, 24-hour offline package lifetime and 15-second dashboard refresh are defined in this pack and may be tuned through a reviewed engineering configuration. Regulatory thresholds, certificate validity, statutory fees, mandatory forms and legal clock rules must come from an approved policy package. Demonstration examples are not Delhi Fire Service rules.

The software must be buildable without waiting for agency credentials: use local providers and demo policy. The software must not become a live official service until the activation gates are met. This distinction resolves uncertainty without allowing the coding agent to invent law.

## 8. Definition of a complete feature

A feature is complete only when its permitted roles, input schema, API contract, atomic persistence, audit, success result, negative result, recovery behavior, responsive screen, accessibility checks and automated tests are implemented. Disabled or pending provider behavior must be explicit. Every list action and deep link must work under direct navigation and expired-session conditions. Test evidence must identify the commit and environment.

## 9. Product acceptance scenario

Rakesh creates a restaurant application, uploads clean required documents and submits once. Anita starts scrutiny, asks for an omitted clarification, accepts Rakesh's response and schedules Suresh. Suresh records a failed visit, then a second visit with one mandatory finding. Rakesh responds; Anita orders reinspection and verifies closure. Anita records a permitted favorable decision. A simulated signer outage leaves issuance pending; recovery publishes exactly one sample instrument. Public verification shows its status. Leadership totals reconcile; audit shows the actors, policy and attempts. A second attempt to submit the same approval must not create another outcome.

## 10. Document ownership and change control

Maintain a versioned change log with affected FR, TR, API, UI and test IDs. Product behavior changes require product-owner review. Security changes require security review. Live policy changes require their appointed approver. Coding agents may clarify technical implementation inside these contracts; they must not silently rename workflow states, weaken safety guards, reduce scope or mark tests passed without running them.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
