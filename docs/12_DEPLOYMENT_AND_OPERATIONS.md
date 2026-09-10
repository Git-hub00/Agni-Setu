# Deployment, monitoring, backup and operational runbooks

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Deployment stages

Use isolated LOCAL, TEST, DEMO, STAGING and LIVE environments. Distinct databases, buckets, credentials, signing keys, provider destinations and domains are mandatory. A staging system does not share a live bucket merely because the database differs. Demo recipients and certificates cannot be mistaken for real service outputs.

Initial pilot topology is an HTTPS reverse proxy, stateless API instances, worker/scheduler processes, a supported PostgreSQL deployment, private object service, authenticated broker/cache and approved external identity/providers. A single local Compose host is convenient for development but is not high availability. The live topology and recovery capacity require operations approval based on actual workload.

## 2. Image and process hardening

Build immutable non-root images from pinned supported bases. Use multi-stage builds, minimal runtime packages, read-only filesystem where practical and explicit writable temporary directories. Do not bake secrets or real evidence into images. Run dependency/container scans and attach an SBOM. Separate document rendering/scanning workers from short business jobs, with bounded memory/CPU and restricted egress.

Production uses Gunicorn behind an approved TLS reverse proxy; never Django runserver. Disable DEBUG, unsafe hosts/CORS, demonstration controls, local OTP sink and sample signing. Do not expose PostgreSQL, RabbitMQ management, Valkey, object-store administration or identity-provider administration to the public network. Staff administration is a separate approved access path with MFA.

## 3. Startup and health

`/health/live` means the process event loop/request handler is alive; it must not fail merely because an optional email gateway is down. `/health/ready` checks database connectivity, migrations/schema compatibility and mandatory startup configuration. Readiness is not a complete business-health assertion. Broker, scanner, signer and external source health are separately visible with queue lag and affected capability status.

A broker outage can leave the API accepting durable outbox-backed intents if business safety permits. A database outage cannot return accepted mutations. Public verification refuses an active assertion when its authoritative dependency is unavailable. Health output is minimal and redacted; internal dashboards expose deeper detail only to operators.

## 4. Monitoring and alerts

| Signal | Initial alert condition | Owner / response |
| --- | --- | --- |
| API errors | Sustained unexpected5xx above agreed baseline | On-call engineering; inspect correlation IDs, recent release and dependencies. |
| Database | Connection exhaustion, disk pressure, replication/backup failure | Database operations; preserve write safety and recovery evidence. |
| Outbox dispatch lag | Oldest due pending intent>60 s normal target; escalate after5 min | Worker/broker operator; inspect broker and dispatcher. |
| Scheduler heartbeat | No heartbeat for>2 expected intervals | Operations; restart safely and run due-work reconciliation. |
| Dead-letter / unknown jobs | Any new issuance unknown; growing critical dead letters | Integration/issuing owner; reconcile rather than force success. |
| Evidence scan backlog | Oldest quarantined required file exceeds configured budget | Document operator; scanner health and safe resource capacity. |
| Public verification | Any unsafe stale-active behavior or high unavailable rate | Security/registry owner; fail closed and investigate. |
| Unowned open work | Any submitted active case lacks valid accountable queue | Business supervisor; immediate handoff repair with audit. |
| Backup/restore | Missing scheduled backup or failed restore drill | Operations owner; release/pilot risk escalation. |

Thresholds are engineering starting points and must be tuned with measured workload. Metrics distinguish business overdue work from infrastructure failures. Do not label emails, case numbers or exact premises as metric tags.

## 5. Safe release process

Build/test from a reviewed commit; generate schema and check drift; run security/dependency scans; create immutable image digests; test migrations against representative previous-version data; deploy to staging; execute role/fault smoke tests; verify backups; obtain production approval; deploy compatible migrations before new code where required; roll API/workers safely; confirm health, outbox lag, verification and role smoke tests; record release evidence.

Migrations use expand-contract. Rollback is not automatically a database downgrade. If a migration is destructive or legal/business events have been accepted under new code, restore/rollback requires an explicit recovery decision. Prefer forward-compatible application rollback while retaining schema and immutable events. Never delete accepted cases to make an old version start.

## 6. Backup and restore design

Proposed pilot objectives: RPO<=15 minutes and RTO<=4 hours, subject to demonstrated tooling and owner approval. Use encrypted PostgreSQL backups plus WAL/PITR capability, protected key material, immutable/versioned objects and off-host backup custody. Daily logical export alone does not prove a15-minute RPO. Protect backups from the same credential compromise that could alter the primary.

A restore drill selects a documented cutoff, restores database to an isolated target, makes referenced object versions available, verifies schema/version, checks record counts and sampled hashes, compares case/decision/certificate relationships, validates secrets/key access, runs read-only integrity reports and performs a controlled synthetic workflow. Record actual recovery time and unrecoverable interval. Check that public verification cannot temporarily expose stale restored status as current without source reconciliation.

Do not take a database snapshot, ignore file objects and claim full recovery. Preserve object versions at least long enough to support approved database recovery windows. Purge jobs must account for backup/retention/legal-hold requirements and not delete a referenced object still needed for restore.

## 7. Incident runbooks

### Database unavailable or uncertain commit

Stop unsafe mutation acceptance; return structured503. Preserve logs and correlation IDs. Determine whether requests committed before connections broke using command receipts, not assumptions from client errors. Restore connectivity/capacity; verify migrations and replication; safely replay original commands after authorization. Do not reconstruct decisions from browser screenshots.

### Broker/worker outage

Inspect outbox and oldest jobs; restore authenticated broker/network; restart workers with correct queue subscriptions; ensure scheduler and reconciler are active. Reconcile expired leases and unknown external attempts. Watch backlog drain and resource limits. Duplicate queue delivery is expected and must remain harmless to canonical records.

### Issuance stuck or signer unknown

Freeze blind retries for the affected logical request. Gather request ID, artifact hash and safe provider receipts. Query the approved reconciliation endpoint or authorized provider contact. Publish only a verified known artifact through the guarded transaction. If no determination is possible, keep pending with an accountable owner; never allocate a new number as a workaround.

### Document safety incident

Restrict access to affected object versions, preserve evidence, create a security hold where permitted and identify cases referencing those hashes. Do not silently edit historic scan results or remove audit. Security and process owners determine reinspection/review obligations. Release safe unaffected operations where possible without misrepresenting affected case readiness.

### Account compromise or privilege error

Disable affected principal/session, revoke grants under the authorization fence, preserve audit and identify commands since suspected compromise. Do not delete prior decisions automatically; process/legal owners determine corrective instruments. Rotate exposed secrets, check provider access and file/export history, and follow the approved incident-notification procedure.

### Lost field device

Revoke server sessions/assignments as appropriate, invoke managed-device controls and record potentially cached packages. A disconnected browser cannot be guaranteed remotely erased. Recover only already accepted server evidence or agency-approved retained local material; do not claim absent local bytes were synchronized.

## 8. Operations actions versus business actions

Technical operators retry/reconcile jobs, maintain secrets, restore infrastructure and collect safe diagnostics. Business authorities resolve findings, assign inspections, approve outcomes and issue status instruments. Policy approvers activate rules through governance. Do not provide an operational database-edit screen capable of bypassing these roles.

Break-glass access is time-bounded, independently approved, recorded and reviewed. It cannot create a silent exception to legal authority. Direct data correction uses a reviewed script/command with before/after counts and audit, and must not erase original evidence or outcomes.

## 9. Capacity and scaling

Start with measured SQL query/index tuning and bounded worker concurrency. Keep API connection pool plus worker connections within PostgreSQL capacity. Scale API and heavy/short worker queues independently. Avoid a single expensive report blocking ordinary commands; asynchronous exports use bounded batches and scoped snapshots. Introduce read projections, replicas or orchestration only after measuring bottlenecks and documenting consistency consequences.

No fixed CPU/RAM table guarantees support for a claimed number of users. Record concurrent activity, request mix, document size, target latency and resource measurements before sizing a pilot. A student laptop demonstration is not a production load result.

## 10. Operational handover

Provide architecture/source/locks, approved configuration and service policy hashes, operator access and recovery contacts, monitoring dashboards, runbooks, backup evidence, certificate/provider reconciliation instructions, known risks and support escalation. Train both technical operators and business supervisors using happy and failed scenarios. The department must be able to operate the service without relying on one developer's laptop or undocumented credentials.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
