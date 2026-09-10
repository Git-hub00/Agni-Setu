# Policy decisions, open questions and live-activation gates

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Why this register exists

Engineering can build the demonstrated product now, using synthetic policy and adapters. It cannot authorize an official service, invent agency powers or resolve legal conflicts by choosing convenient constants. This register distinguishes missing business approvals from implementable engineering decisions. Unanswered live questions block the affected live service, not the entire demo build.

## 2. Required owner decisions

| Gate | Decision / evidence required | Accountable owner | Safe development behavior |
| --- | --- | --- | --- |
| LIVE-01 | Service mandate and original system of record: standalone or monitoring partner | Business/process owner | DEMO only; no official case numbers. |
| LIVE-02 | Consolidated current service eligibility, exclusions, forms and effective-date transition rules | Policy/legal owner | Synthetic categories and unmistakable sample policy. |
| LIVE-03 | Exact authority posts, jurisdiction, category limits, delegation and separation requirements | Process owner | Synthetic effective grants; no real staff powers inferred. |
| LIVE-04 | Document checklist, inspection criteria, NA rules and reinspection obligations | Inspection/policy owner | Eight-item educational demo checklist, not legal standard. |
| LIVE-05 | Statutory and internal clocks, working calendars, holidays, pause/hold treatment and escalation ladder | Process/policy owner | Documented demo targets, never labelled statutory. |
| LIVE-06 | Notice wording, service of notices, response periods and fairness requirements | Policy/legal owner | Plain-language sample notices with demo marker. |
| LIVE-07 | Certificate template, validity model, signing method, issuer and correction/revocation powers | Issuing authority | Watermarked sample artifact; no copied official seal/signature. |
| LIVE-08 | Public verification fields, number lookup, freshness and status semantics | Data/privacy owner | Minimal synthetic fields; no private applicant data. |
| LIVE-09 | Identity provider, applicant recovery, staff MFA and professional identity validation | Identity/security owner | Local OTP sink and isolated Keycloak fixtures. |
| LIVE-10 | Hosting, data residency, storage support, backup and key ownership | IT/security/procurement | Local infrastructure; no claim of government hosting approval. |
| LIVE-11 | Records retention, legal hold, destruction and subject-request handling | Records/privacy/legal owner | No automatic purge of accepted demo business history. |
| LIVE-12 | Managed-device rules, offline data permission, local retention and recovery of lost devices | Security/field operations | Offline demo only on approved test devices; shared cache off. |
| LIVE-13 | Real gateway contracts, credentials, idempotency and reconciliation routes | Integration owner | Named simulators; clear provider-mode labels. |
| LIVE-14 | Fees, treasury/payment responsibilities and verified receipts if applicable | Finance/process owner | Fees disabled; dependent live profile disabled. |
| LIVE-15 | Appeal/admissibility/remedy process if applicable | Legal/process owner | Referral, not fake legal filing. |
| LIVE-16 | External issuer qualification and certificate registration process if applicable | Policy/registration owner | Conditional capability disabled. |
| LIVE-17 | Accessibility, languages and assisted-service operating process | Product/service owner | Accessible English baseline; reviewed Hindi before enablement. |
| LIVE-18 | Security acceptance, vulnerability treatment and incident notification process | Security owner | Isolated synthetic environment only. |
| LIVE-19 | Recovery objectives, on-call roster, escalation and measured restore evidence | Operations owner | Rehearsal targets, not achieved production guarantees. |
| LIVE-20 | UAT, pilot population, measurement baseline, training and release approval | Sponsor/product/QA | Demo acceptance report; no claim of real agency pilot. |

## 3. Configuration gate enforcement

`ServiceActivationValidator` evaluates required gates for the selected mode/profile. Store evidence references, approvers, approval date, expiry and scope. A LIVE provider reference is not sufficient evidence by itself. A live profile with required fee/signature/appeal capability disabled is rejected. A deployment that contains demo reset routes, default secrets or sample signer configuration fails its live startup/activation checks.

Once approved, a policy package is immutable. Revoking gate evidence can disable new submissions and affected high-risk actions while preserving accepted records and creating an owned operational incident. Do not delete existing cases because a profile becomes unavailable. Define safe treatment of in-flight cases through process-owner decisions.

## 4. Decisions already made by this engineering baseline

The initial implementation uses one React/PWA codebase, Django/DRF, PostgreSQL, persisted commands/outbox/obligations, explicit errors, private object storage and typed provider adapters. Application states and core role journeys are fixed in the workflow/UI specifications. Coding agents should not repeatedly ask the user to pick a framework. B00 confirms this recommended baseline and records actual dependency versions; it does not reopen every design choice without cause.

## 5. What the agent should do when information is missing

Continue all independent demonstration work using explicitly named synthetic fixtures. Record a BLOCKED task only for the actual missing dependency. State the missing item, why it matters, owner, safe current behavior and the exact test that cannot be executed. Never invent a provider token, legal threshold, passed test or government approval. Ask for secrets through environment/secret-manager instructions, not by copying them into Markdown or chat logs.

## 6. Release evidence required

Evidence includes commit/release IDs; exact dependency lock and container digests; migration plan; database/object restore result; automated and manual test reports; role/authority matrix sign-off; approved policy hash; public schema approval; provider sandbox/live acceptance; security findings and treatment; accessibility review; operator runbooks and contact roster; rollback decision; pilot monitoring dashboard; explicit go/no-go decision.

The paper, presentation and prototype are explanatory project artifacts, not substitute evidence of a production security audit, legally authorized certificate or live integration test.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
