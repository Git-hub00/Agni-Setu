# Durable jobs, failure modes and recovery contracts

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Core guarantee and its limit

The system must preserve every **accepted business intent** in PostgreSQL and prevent duplicate canonical decisions, notices, threshold actions and issuance identifiers. It must not claim all external messages are physically delivered exactly once. Celery acknowledgement, RabbitMQ persistence and a green UI toast are not substitutes for a committed business record.

## 2. Transactional outbox

A command transaction writes state/revision, audit, event, obligations and outbox intent. After commit a dispatcher publishes the logical job ID. If the broker is down, the command may still succeed because the intent is durable; UI shows queued processing and operations sees outbox lag. If the database commit fails, no receipt is returned. `on_commit` can wake dispatch but the periodic database scan is the recovery mechanism.

The dispatcher publishes with delivery confirmation when supported. If it crashes after publish but before marking dispatch, it may publish again. That is allowed. The worker claims the same logical job and uniqueness constraints prevent duplicate business effects. Do not delete outbox intent solely because a broker accepted a message.

## 3. Job claim and fencing

```text
short transaction:
  select due candidate FOR UPDATE SKIP LOCKED
  verify job not complete and lease absent/expired
  increment lease_token, set RUNNING, lease_owner, lease_until
  create attempt record
commit
reload required authority and business applicability
execute bounded external operation using stable logical_action_id
short transaction:
  lock job and required aggregate
  require matching lease_token and valid current lease
  record known result, unknown result or next retry
  complete canonical business effect only if its guards still pass
commit
```

Default lease is 120 seconds, external connect timeout 5 seconds and request timeout 30 seconds for ordinary message providers. Longer rendering/signing tasks use declared bounded limits and lease heartbeat. Heartbeat renews only the current token. A worker that loses its lease cannot write completion. Fencing does not physically cancel a remote request already executing, which is why external idempotency and reconciliation are separately necessary.

## 4. State and retry policy

| Result | Persisted state | Action |
| --- | --- | --- |
| Known success | COMPLETE | Record provider receipt/artifact then apply guarded business effect. |
| Known transient failure before any irreversible effect | RETRY_WAIT | Backoff and bounded retry with same logical identity. |
| Unknown remote outcome after request may have executed | RECONCILIATION_REQUIRED | Query provider by stable ID or obtain approved manual evidence before retry. |
| Permanent invalid request or unsupported operation | DEAD_LETTER | Assign owner; correct configuration/input through a reviewed new command. |
| Worker crash | RUNNING until lease expiry, then eligible recovery | Reconciler determines safe retry/reconciliation based on attempt phase. |
| Job no longer applicable | COMPLETE with disposition CANCELLED_AS_OBSOLETE | Preserve history; do not execute obsolete reminder or notification. |

Demo transient backoff schedule: 30 seconds, 2 minutes, 10 minutes, 30 minutes and 2 hours, with bounded jitter. Maximum six execution attempts including initial. Honor valid provider Retry-After within configured caps. Authentication/configuration failures do not busy-retry. A new operator retry after DEAD_LETTER requires reason and records an explicit recovery event while retaining attempt history; it does not generate a new logical business action.

## 5. Scheduler and obligation processing

Run a due-obligation scanner every 30 seconds and an outbox/job reconciler every 60 seconds as engineering defaults. Multiple instances may run safely with row locking and unique `(obligation,stage_instance,threshold)` actions. Timers are database facts, not long-lived browser setTimeout calls or months-long Celery ETA messages.

At execution, recheck the obligation state, generation, due calculation and recipient eligibility. An obligation satisfied before a delayed reminder executes suppresses the obsolete reminder. On a long outage, persist all materially required missed threshold history, but coalesce redundant outbound reminders into the latest useful notification according to a documented delivery policy. Do not fabricate historical send times. Escalation creates a duty-owned task even when all external channels fail.

## 6. Failure and recovery matrix

| Failure | What users see | Persisted behavior | Recovery |
| --- | --- | --- | --- |
| API request times out after commit | Outcome not confirmed | Receipt already exists | Retry original command key; return original authorized result. |
| Database unavailable | Service temporarily unavailable | No false accepted receipt | Restore DB and retry under current version; verify uncertain connection outcomes. |
| Broker unavailable | Accepted work queued | Outbox remains pending | Dispatcher/reconciler republishes after recovery. |
| Worker terminated during scan/render | Processing delayed | Job attempt and lease remain | Lease expiry, bounded safe retry; preserve original object/job. |
| Object upload incomplete | Upload incomplete | Reservation not clean evidence | Retry upload or new reservation, never submit placeholder. |
| Scanner unavailable | Awaiting security scan | Quarantine remains | Retry scan when healthy; no admin mark-clean bypass. |
| Email/SMS provider rejects contact | In-app notice remains | Delivery DEAD_LETTER / known failure | Correct verified contact and issue an authorized redelivery. |
| Signer times out after possible signing | Certificate processing - checking provider | RECONCILIATION_REQUIRED | Lookup same request ID; no second certificate reservation. |
| Published artifact but registry transaction fails | Still pending until canonical record commits | Stable artifact stored, issuance request persisted | Reconcile hash/provider receipt and complete same registry transaction. |
| Permission revoked while job waiting | Action no longer permitted / needs authority | Preserve prior valid intent/decision, block new forbidden effect | Obtain required current authorization or cancel applicable work explicitly. |
| Duplicate webhook | No duplicate timeline or outcome | Unique inbox receipt | Return prior acknowledgement after body/hash validation. |
| Reporting cache lost | Refreshing or bounded SQL fallback | Canonical records unaffected | Rebuild scoped cache/projection. |
| Offline device lost | No false server receipt | Only already accepted data is authoritative | Agency device/incident process; cannot recover bytes never transmitted. |

## 7. Error catalogue

These codes are the stable public/internal-safe contract. Lower-level provider errors map to them or to a redacted operational reason. Do not invent a new UI-specific code for the same condition in every module.

| Code | HTTP | Condition | Required user/system response |
| --- | --- | --- | --- |
| MALFORMED_REQUEST | 400 | Invalid JSON, route value or query syntax | Correct request syntax; do not retry unchanged. |
| AUTHENTICATION_REQUIRED | 401 | No valid server session | Sign in and resume; preserve permitted draft data. |
| SESSION_EXPIRED | 401 | Session idle/absolute expiry or revoked session | Reauthenticate; original idempotency key may still resolve accepted work. |
| OTP_INVALID | 422 | Incorrect or consumed challenge | Generic message; bounded retry, never expose expected code. |
| OTP_EXPIRED | 422 | Challenge lifetime elapsed | Request a new challenge after cooldown. |
| OTP_THROTTLED | 429 | Contact/IP/device limit reached | Show Retry-After; do not bypass by creating another account. |
| CSRF_FAILED | 403 | Missing or invalid CSRF/Origin on unsafe request | Rebootstrap same-origin CSRF then retry only with original command key. |
| FORBIDDEN | 403 | Known permitted resource but forbidden action | Explain permitted next route without sensitive guard details. |
| RESOURCE_NOT_FOUND | 404 | Absent or outside readable scope | Same external response for nonexistent and cross-scope IDs. |
| PRECONDITION_REQUIRED | 428 | Missing If-Match on existing resource mutation | Fetch current record and send its ETag. |
| VERSION_CONFLICT | 412 | If-Match does not match current resource | Compare and reapply permitted changes; do not overwrite blindly. |
| IDEMPOTENCY_CONFLICT | 409 | Same scoped key with different request hash | Resolve original operation; corrected command needs a new key. |
| COMMAND_IN_PROGRESS | 409 | Matching command still leased/in progress | Use Retry-After and original key; no duplicate click workaround. |
| INVALID_TRANSITION | 409 | Command not permitted from current state | Reload current allowed actions and explain changed workflow. |
| VALIDATION_FAILED | 422 | Required fields or cross-field constraints fail | Show exact safe JSON-pointer violations and retain inputs. |
| POLICY_UNAVAILABLE | 409 | No approved applicable policy | Keep draft and show service unavailable; route operator alert. |
| POLICY_AMBIGUOUS | 409 | Multiple policies apply | Block receipt and alert policy owner; never choose arbitrarily. |
| POLICY_REVIEW_CONFLICT | 409 | Preparer attempts approval or candidate changed | Use independent approver and current frozen candidate hash. |
| POLICY_INTERVAL_OVERLAP | 409 | Approved activation interval overlaps another | Correct effective interval through reviewed policy flow. |
| SERVICE_DISABLED | 409 | Required service feature not enabled | Display approved referral; no demo fallback in live mode. |
| AUTHORITY_REVOKED | 403 | Current grant/delegation no longer valid | Stop command; authorized reassignment/recovery required. |
| AUTHORITY_SCOPE_MISMATCH | 403 | Service/jurisdiction/category or power not granted | Route to a permitted authority; never broaden grant automatically. |
| SEPARATION_OF_DUTIES | 403 | Same actor would perform incompatible duties | Require a different approved actor. |
| ROUTING_UNRESOLVED | 409 | Case routing has no unique resolved target | Keep accountable exception queue; supervisor must resolve. |
| ASSIGNMENT_CHANGED | 409 | Offline/current assignment version mismatch | Lock stale operation and open reviewed conflict resolution. |
| OFFICER_UNAVAILABLE | 409 | Officer inactive, absent or outside eligibility | Select eligible alternative or retain owned pending assignment. |
| APPOINTMENT_CONFLICT | 409 | Concurrent or overlapping officer booking | Show alternative times after refreshing calendar. |
| FILE_TOO_LARGE | 413 | Upload exceeds configured per-file or request limit | Select smaller allowed file; no silent corruption by compression. |
| FILE_TYPE_UNSUPPORTED | 415 | Extension/sniffed type not allowed | Use permitted format; client MIME alone is not trusted. |
| UPLOAD_INCOMPLETE | 409 | Missing object bytes or checksum/size mismatch | Retry safe upload reservation; do not accept document. |
| UPLOAD_EXPIRED | 410 | Reservation no longer valid | Create new reservation; clean orphan objects later. |
| FILE_QUARANTINED | 409 | Scan pending, failed scanner or unknown scan status | Wait or retry scanning through operations; no bypass. |
| FILE_REJECTED | 422 | Unsafe file or policy-rejected content | Remove draft reference and replace; retain security event. |
| EVIDENCE_INCOMPLETE | 422 | Mandatory evidence not accepted | Show missing item-specific evidence requirements. |
| CHECKLIST_INCOMPLETE | 422 | Mandatory observations absent or NA invalid | Return to specified checklist items. |
| MANDATORY_FINDINGS_OPEN | 409 | Favorable decision has unresolved required findings | Review correction or order reinspection; do not compensate by score. |
| NOTICE_NOT_OPEN | 409 | Response targets closed/superseded notice | Open current permitted notice or request reviewer clarification. |
| RESPONSE_NOT_VERIFIED | 409 | Trying to accept round with unresolved required items | Verify or return each item first. |
| OFFLINE_PACKAGE_EXPIRED | 409 | Local package outside permitted validity | Refresh authorization/package online; review preserved local work. |
| SYNC_SCHEMA_UNSUPPORTED | 422 | Unsupported local operation/checklist schema | Upgrade client safely without deleting unsynchronized data. |
| SYNC_PAYLOAD_CONFLICT | 409 | Operation ID reused with different content | Keep original receipt; create a new reviewed operation ID. |
| ISSUANCE_IN_PROGRESS | 409 | Duplicate issuance already exists | Open the same issuance job and canonical certificate reservation. |
| EXTERNAL_OUTCOME_UNKNOWN | 409 | Provider may have executed irreversible action | Reconcile by stable request ID; no blind repeat. |
| CERTIFICATE_STATUS_CONFLICT | 409 | Forbidden status change or expired authority | Fetch effective status and follow approved instrument workflow. |
| VERIFICATION_UNAVAILABLE | 503 | Registry/authoritative source unavailable or stale | Show cannot currently verify; never assert ACTIVE. |
| EXPORT_EXPIRED | 410 | Export artifact no longer accessible | Regenerate under current permission and cutoff. |
| INTEGRATION_SEQUENCE_GAP | 409 | Source event is out of order or missing predecessors | Persist conflict and reconcile source sequence. |
| INTEGRATION_SIGNATURE_INVALID | 401 | Partner authentication/HMAC/mTLS invalid | Reject without processing; alert with redacted metadata. |
| RATE_LIMITED | 429 | General safe request limit exceeded | Honor Retry-After and backoff. |
| DEPENDENCY_UNAVAILABLE | 503 | Required database, storage or mandatory provider cannot accept work | No false success; retry safely or keep accepted job pending. |
| INTERNAL_ERROR | 500 | Unhandled unexpected defect | Generic reference ID; alert engineering; no sensitive stack trace. |


## 8. Recovery UI permissions

Operations can inspect safe job details, request safe retry, trigger reconciliation and assign intervention. Operations cannot edit case status, mark unsafe evidence clean, replace a decision, forge a signer receipt or delete failed attempts. Business supervisors own domain blockers, while technical operators own dependency recovery. Recovery screens link these ownership domains instead of creating one unrestricted administrator.

## 9. Circuit breakers and bounded work

Use separate provider concurrency limits and circuit breakers so an unavailable SMS service cannot starve PDF scanning or expiry checks. Open circuits leave persisted jobs waiting with visible next probe time. Bound attachment rendering time, bytes and memory; separate CPU-heavy rendering/scanning queues from short notification jobs. Validate total worker DB connections against the database pool budget.

## 10. Required fault proofs

Kill a worker after remote success but before database completion; stop the broker after an application is accepted; restart two schedulers at an overdue threshold; duplicate delivery and partner events; race a decision with grant revocation; fill object storage; fail scanning; force a certificate-provider unknown outcome. For each, verify canonical record count, unchanged valid business state, visible ownership, audit/attempt evidence and eventual correct recovery. Test results must name the injected fault and commit; this document is not proof those tests have already run.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
