# Architecture decision records

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## Status and authority

These are recommended implementation decisions for baseline 2.0.0, made in response to the request to select a suitable stack. They are not retrospectively attributed to earlier project documents. B00 records acceptance or a reasoned alternative before coding. A rejected decision must update all dependent documents and tests, not produce a mixed architecture.

## ADR-01 - Django/DRF modular monolith

**Decision:** Replace the prior Flask backend recommendation for this greenfield build.

**Rationale:** Integrated session/security/migration foundation and explicit modules suit the large relational workflow.

**Consequences:** Django conventions and operational skills are required; do not rewrite an existing working repository without first inventorying it.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-02 - PostgreSQL rather than MongoDB

**Decision:** Use one PostgreSQL database for canonical business records; JSONB for variable approved payloads.

**Rationale:** Relations, uniqueness, transactions and booking constraints match the critical invariants.

**Consequences:** A real migration from older MongoDB data would need mapping and reconciliation; no such migration is claimed executed.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-03 - SPA and PWA in one React codebase

**Decision:** Preserve seven role workspaces with shared components and an officer-focused offline feature.

**Rationale:** Avoid duplicated native applications and multiple frontend design systems.

**Consequences:** Offline support must be tested on actual browsers; shared code is not proof of accessibility.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-04 - Server sessions with OIDC/OTP adapters

**Decision:** No browser-managed bearer token in localStorage; use same-origin session cookies and CSRF.

**Rationale:** Reduces token handling in browser code and supports central session revocation.

**Consequences:** Every unsafe endpoint, including unauthenticated OTP commands, needs explicit CSRF and Origin controls.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-05 - Policy and authority are versioned data

**Decision:** Do not infer statutory power from an application role.

**Rationale:** Live service rules and actor powers vary by service and effective date.

**Consequences:** Policy approval and activation are business features; programmers cannot fabricate the missing approvals.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-06 - SQL outbox and persistent obligations

**Decision:** External side effects follow committed intents; scheduler scans canonical obligations.

**Rationale:** Recover accepted work after crashes and message transport loss.

**Consequences:** Delivery is at least once; external uncertainty requires reconciliation, not exactly-once marketing claims.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-07 - RabbitMQ for task transport; Valkey disposable

**Decision:** Separate queue transport from cache/rate-limit duties; database remains recovery authority.

**Rationale:** Makes broker loss and cache loss independent of accepted business facts.

**Consequences:** More local services; provide minimal/full profiles and keep these dependencies off public interfaces.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-08 - Private supported S3 service; local SeaweedFS mini

**Decision:** Avoid depending on an archived MinIO community deployment as the new live default.

**Rationale:** Keep storage provider replaceable and production support separately reviewable.

**Consequences:** SeaweedFS mini is not production storage; choose and qualify the live service before activation.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-09 - Guarded commands instead of generic status PATCH

**Decision:** Each regulatory action has a named DTO, permission, transition guard and event.

**Rationale:** Prevents clients or administrators from jumping directly to completed states.

**Consequences:** More explicit endpoints and tests, but substantially clearer audit and recovery behavior.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-10 - Conflict-aware offline operations

**Decision:** Use base versions, assignment versions and canonical operation receipts.

**Rationale:** Avoid losing evidence or accepting stale authority on reconnect.

**Consequences:** No promise of offline remote wipe; device controls and clear local-risk warnings remain necessary.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-11 - Favorable decision distinct from publication

**Decision:** Keep APPROVED_PENDING_ISSUE until registry/artifact/signing checks succeed.

**Rationale:** Technical failure cannot become an official certificate or rejection.

**Consequences:** Operators need issuance recovery screens and provider-outcome reconciliation.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-12 - Scoped SQL reports first

**Decision:** Use consistent-cutoff queries and targeted caches; no initial warehouse.

**Rationale:** Limits infrastructure while ensuring totals match authoritative cases.

**Consequences:** Large-scale reporting may later need materialized projections after measured contention.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-13 - No autonomous AI in the safety decision loop

**Decision:** Deterministic guards and qualified human decisions are the core.

**Rationale:** No training dataset, validated model or lawful automated decision mandate is established.

**Consequences:** Optional later assistance needs a separate evaluated proposal; it cannot replace mandatory evidence.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-14 - Near-real-time polling baseline

**Decision:** Refresh active queues every 15 seconds with jitter and invalidation after commands.

**Rationale:** Sufficient initial monitoring UX without a separate live-event infrastructure.

**Consequences:** This is not hard real time; measure load/freshness before introducing SSE.

**Status:** recommended; implementation acceptance to be recorded at B00.

## ADR-15 - Demo/live separation enforced in code and deployment

**Decision:** Separate secrets, storage, recipients, registry identifiers and enabled routes.

**Rationale:** Prototype shortcuts must never verify as official actions.

**Consequences:** Extra environment checks and integration tests are required, not merely a watermark.

**Status:** recommended; implementation acceptance to be recorded at B00.

## Change discipline

A replacement ADR records the problem, evaluated alternatives, exact requirements affected, migration/operational cost, security impact and test plan. Do not reselect the stack on each agent session. Major framework changes, multiple databases or a new workflow engine require explicit approval.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
