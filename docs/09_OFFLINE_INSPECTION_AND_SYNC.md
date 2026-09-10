# Offline inspection, local persistence and synchronization

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Supported offline scope

Offline capability is restricted to assigned field-inspection packages and local draft observations/evidence. Application submission, policy approval, regulatory decisions, certificate publication, staff grants and public ACTIVE verification are online-only. The browser may show previously downloaded information with a visible timestamp but must not treat it as current authority.

Use IndexedDB through Dexie for explicit versioned data, and Workbox for the static app shell. Background Sync is an optional enhancement because browser availability and execution guarantees vary; foreground `Sync now` is mandatory. Browser storage can be evicted or unavailable, so the product must not promise zero loss for bytes never accepted by the server. The referenced MDN sources document these platform limitations.

## 2. Device and cache policy

Demo defaults: package expires after 24 hours; local unsent work may be retained up to seven days only on an approved managed device, with escalating warnings. Expiry stops automatic acceptance but does not silently delete unsent evidence. After canonical acceptance, remove local evidence after a 24-hour grace period unless a supported operator recovery need is recorded. Live values require agency approval.

Shared-device mode disables case-package caching. Managed devices require operating-system encryption, screen lock, approved browser and device access controls. A web app cannot guarantee remote wiping of a disconnected device or cryptographically hide all same-origin data from an already compromised session. Do not claim WebCrypto alone solves that problem. If the agency requires stronger device-bound offline encryption, qualify a managed platform before enabling live offline evidence.

## 3. Local database stores

| Store | Key and data | Purpose |
| --- | --- | --- |
| device_meta | installation UUID, schema version, last authenticated principal/epoch | Scope local data to installation and identity. |
| packages | inspection ID, policy/checklist IDs, case version, assignment version, expires_at, minimum snapshot | Prepared authorized work. |
| report_drafts | inspection ID + local revision, observations, notes, dirty fields, capture times | Editable local record; never a server report. |
| local_evidence | blob ID, encrypted/OS-protected storage policy metadata, original bytes, hash, size, item reference | Files not yet uploaded; handle quota failure. |
| upload_state | local blob ID, reservation ID, completed byte/object reference, scan status | Resume safely when supported; avoid duplicate accepted file records. |
| operations | operation UUID, immutable manifest hash, base/assignment versions, state, attempts, last error | Durable local intent and deterministic retry. |
| receipts | operation UUID, operation type, canonical report or visit-outcome ID, accepted_at, returned versions | Proof of accepted synchronization. |
| conflicts | operation UUID, safe server conflict snapshot, resolution choice | Reviewed recovery, never automatic last-write-wins. |

Schema upgrades are versioned Dexie migrations. Test upgrade with unsent drafts and blobs. A failed upgrade must not clear all local stores as a shortcut. A service-worker update prompts for a safe reload and leaves old compatible operation manifests readable until migration is complete.

## 4. User state model

Local operations progress through `LOCAL_DRAFT`, `WAITING_FOR_UPLOAD`, `WAITING_FOR_SCAN`, `READY_TO_SUBMIT`, `SUBMITTING`, `ACCEPTED` or `CONFLICT`. A network failure yields retry waiting without removing data. A user sees the exact destination: Saved on this device, Saved on server as draft, or Submitted and received. Only the last has a canonical receipt.

Connectivity is determined by actual API reachability/authentication, not only `navigator.onLine`. A captive portal or expired session can make online transport unusable. Surface these separately: Offline, Server unavailable, Sign-in needed or Synchronization conflict.

## 5. Synchronization algorithm

1. Require an online session for the same principal and refresh `/me` to obtain current epoch/permissions.
2. Fetch current assignment/inspection metadata. Reject automatic submission when the package expired, assignment changed or authority was revoked.
3. Upload each evidence blob under a target-scoped reservation. Verify size/hash/type, complete upload and wait for canonical CLEAN references. Reuse the same accepted upload reference after retry.
4. Freeze the operation manifest with a random operation UUID, payload hash, base case/inspection versions, assignment/checklist versions and evidence references. A later edit creates a new operation; it must not change the payload behind an accepted operation ID.
5. POST `/sync/operations` with the inspection If-Match and stable idempotency key. The body includes `application_version`. Server performs current authorization and domain validation under locks.
6. On accepted/duplicate response, persist canonical receipt locally before marking accepted. Then update local package versions and schedule cleanup.
7. On timeout, query the operation receipt or replay the same manifest/ID. Do not create another report with a new ID solely because the first response was lost.
8. On structured conflict, stop automatic retries and present reviewed resolution. No clock or device timestamp overrides the server's authoritative version.

## 6. Manifest example

```json
{
  "operation_id": "6b68b2c9-aa55-4751-91d1-b6648ece5db0",
  "operation_type": "SUBMIT_INSPECTION_REPORT",
  "inspection_id": "e9b01786-e111-467a-970b-ef78d9cfc270",
  "application_version": 18,
  "base_inspection_version": 4,
  "assignment_version": 2,
  "checklist_version": "demo-checklist-v1",
  "schema_version": "1.0",
  "captured_at": "2026-09-09T05:20:00Z",
  "observations": [{"item_code": "C01", "result": "PASS", "note": "Demonstration observation", "document_version_ids": ["c44f6dbe-d1b1-481b-bde8-c1a68d0bd1d2"]}],
  "summary": "Partial example manifest; all required checklist items must be present in a real submission."
}
```

This deliberately partial example is not a valid complete eight-item demo report. The server validates the entire required checklist and evidence set, not just the JSON shape.

## 7. Conflict resolution matrix

| Conflict | Automatic action | Permitted human resolution |
| --- | --- | --- |
| Only unrelated case metadata changed | No blind merge | Refresh and explicitly rebase after server verifies fields do not affect report applicability. |
| Accepted report already exists | Never overwrite | Supervisor reviews local proposal and creates permitted addendum/reinspection or declines it. |
| Assignment superseded | Stop active submission | Current supervisor reviews attributable recovered evidence; old actor does not regain assignment. |
| Authority revoked/account disabled | Lock local submission | Agency-approved evidence recovery through a currently authorized actor; no identity spoofing. |
| Checklist/policy mismatch | Stop automatic submit | Apply pinned service rules; new observations may be required, with documented reason. |
| Same operation ID, different hash | Reject | Preserve original operation; create a new explicitly reviewed operation ID. |
| Evidence rejected by scan | Keep report unsubmitted | Replace evidence through a new accepted upload; preserve rejection history. |
| Client schema unsupported | Pause queue | Upgrade using tested migration and confirm preserved data. |

Conflict resolution references both local and server versions and records reviewer, reason and selected outcome. Never simply change `base_version` on an old manifest to trick the server into accepting it. A new valid manifest has a new identity and retains a link to the rejected/conflicting operation.

## 8. Evidence capture limitations

GPS includes latitude, longitude, accuracy, captured_at and permission/unavailability reason. Do not synthesize coordinates when permission fails. Camera images preserve original hashes and relevant metadata; derivative previews are separate. Capture time can be wrong due to device clock settings and is not a legal server receipt. Observations and image metadata are corroborating information, not proof that a qualified physical inspection occurred.

## 9. Logout, user switching and storage errors

When unsent work exists, logout shows number of drafts/files and options to cancel and synchronize, or confirm the approved lock/purge policy. Switching identity never exposes the previous user's cache. If storage writes fail, show Not saved locally and retain the in-memory draft where possible; advise immediate online save instead of falsely claiming success. Browser eviction detection compares expected local manifests to available data and reports missing local evidence honestly.

## 10. Offline acceptance suite

Test device offline through a complete checklist; partial file upload; file scanned after reconnect; session expired; assignment reassigned; permission revoked; duplicate manifest; lost response after commit; local schema upgrade; browser quota failure; two tabs editing; service-worker update with unsent work; denied camera/GPS; shared-device mode. Test on the approved real browser/device matrix, not only a desktop browser's offline checkbox.


## 11. Offline failed visits are first-class operations

A field officer can record a failed visit while disconnected. Save a local `RECORD_FAILED_VISIT` operation with the same assignment, inspection, case and package versions used for a report. Require a supported failure reason and useful narrative; optional evidence must finish uploading and scanning before it is referenced. No checklist or favorable recommendation is required or allowed for this operation type. The local queue says "Failed visit saved on this device - not yet received" until acceptance.

On synchronization, reuse the online fail-visit application service inside the same fenced transaction. Persist one FAILED attempt outcome, one next-action/rescheduling obligation, audit/event/outbox and one canonical sync receipt. The application remains INSPECTION_PENDING. Do not reset case-wide age, auto-book an unavailable officer or accept an offline report after a failure already closed that attempt. An accepted report/failure race admits only the first valid outcome; the second becomes a version/domain conflict with preserved local data. The source prototype's failed-visit queue is therefore retained, not dropped during the production rewrite.

Receipt fields are discriminated: `operation_type`, `accepted_entity_kind` (REPORT or VISIT_OUTCOME), `accepted_entity_id`, accepted_at, returned_application_version and returned_inspection_version. The receipts store must not assume every acceptance has report_id. Add explicit tests for offline failed visit, missing optional evidence bytes, lost failure receipt and report-versus-failure race.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
