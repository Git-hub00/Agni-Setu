# Integration adapters, document processing and certificate lifecycle

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Adapter contract, not assumed integration

Every provider implements a typed interface and has a declared mode: SIMULATED, SANDBOX or LIVE. A provider card saying Connected is not evidence that an end-to-end regulatory integration exists. Configuration names the source of truth, permitted operations, authentication scheme, schema version, idempotency mechanism, timeout, reconciliation endpoint, freshness budget and accountable owner.

A live service requiring an unavailable adapter remains disabled or explicitly blocked at that step. No live failure falls back to a sample signer, fake OTP, local success JSON or assumed payment confirmation.

## 2. Required ports

| Port | Required operations | Required result |
| --- | --- | --- |
| ObjectStore | reserve_upload, inspect_object, read_version, create_derivative, issue_access, delete_if_allowed | Immutable object/version, size and hash; explicit not-found/permission/transient failures. |
| MalwareScanner | scan_object_version | CLEAN, REJECTED or UNKNOWN with engine/version/time; never infer clean from timeout. |
| MessageSender | send, lookup_delivery where supported | Stable logical/provider IDs and known accepted/delivered/failed/unknown result. |
| StaffIdentity | start_auth, validate_callback, logout, metadata/key refresh | Validated issuer+subject and authentication context; no implicit grant of business power. |
| CertificateRenderer | render(template_version, immutable_snapshot) | Artifact bytes/hash with embedded mode and verification link; deterministic business data. |
| CertificateSigner | submit(stable_request_id, artifact_hash), lookup(stable_request_id) | Signed artifact/receipt or explicit unknown outcome; bounded timeout. |
| SignatureVerifier | verify(artifact, expected_issuer, trust_policy) | Verified signature/integrity status and evidence; QR is not used as signature validation. |
| PartnerCaseSource | receive_event, lookup_case, submit_allowed_command | Source ID/version, acknowledgement and ownership-defined fields. |
| ExternalCertificateSource | verify_issuer, lookup_instrument, verify_artifact | Source authority, current status/freshness and retained verification evidence. |
| PaymentAdapter | initiate, verify_callback, reconcile | Conditional; approved charge/reference/status only, no unverified paid flag. |

Provider implementations live in adapters, not API views. Domain/application services depend on typed ports. Every simulator implements the same semantic contract and supports transient failure, permanent failure, duplicate request and unknown outcome fixtures.

## 3. Upload and scanning pipeline

1. Current user requests a target-scoped upload reservation with file metadata and intended requirement/item.
2. Server checks ownership, state, permitted type/size and quota, creates a random private object key and bounded access mechanism.
3. Client uploads bytes without receiving broad bucket credentials. For the initial10 MiB limit, retrying a single-part upload is acceptable; do not claim resumable multipart support unless implemented and tested.
4. Completion command verifies size, object version and hash against trusted storage metadata/read. Bind the file to an immutable version and set QUARANTINED.
5. Durable scan job runs with bounded resources. CLEAN is attached only to the exact version scanned. Unsafe or unreadable files become REJECTED; scanner failure stays unresolved/quarantined.
6. A validated application/response/report command links the clean document version to its immutable evidence snapshot.
7. Preview generation is a separate safe derivative with original retained. Document downloads reauthorize and are audited.

Never scan a path supplied by the browser, use the original filename as a filesystem path or fetch an arbitrary uploaded-document URL. Restrict renderer/scanner egress and parser resources. Strip dangerous active content in derivatives without pretending the original was changed or legally verified.

## 4. Notification pipeline

A business event creates one in-app notification intent per recipient/logical event and optional channel jobs. Template version, locale, safe render context and recipient reference are frozen. Sending may be delayed, but in-app business history remains canonical. Provider callbacks authenticate and deduplicate by provider event ID; transitions from delivered to failed require explicit provider semantics rather than arbitrary arrival order.

Contact corrections never rewrite the historical destination of an earlier attempt. An authorized redelivery references the original notice and a new verified destination/version. Preferences govern optional channels; approved mandatory service notices follow the service policy. A read marker means the UI item was opened, not legally served or substantively accepted unless the agency's approved service rules explicitly establish that effect.

## 5. Certificate issuance transaction boundaries

```mermaid
sequenceDiagram
    participant A as Decision authority
    participant API as Command service
    participant DB as PostgreSQL
    participant W as Worker
    participant S as Signer / demo renderer
    A->>API: Approve + If-Match + Idempotency-Key
    API->>DB: Decision + issuance intent + audit/outbox
    DB-->>API: Commit APPROVED_PENDING_ISSUE
    API-->>A: Accepted; certificate processing
    W->>DB: Claim stable issuance request
    W->>S: Render/sign using stable request ID
    alt Known valid result
        S-->>W: Artifact and verification evidence
        W->>DB: Guarded registry publish + COMPLETED
    else Unknown outcome
        S-->>W: Timeout / uncertain status
        W->>DB: RECONCILIATION_REQUIRED
    end
```

Allocate one certificate number for the unique issuance request and decision. A failed attempt reuses it. Create the public verification token with at least192 bits of cryptographic randomness; store a lookup hash and encrypted recoverable token for authorized artifact rendering/link access. The token is not a substitute for public-data minimization and is never used to authorize private evidence access.

The demo renderer produces a conspicuous `DEMONSTRATION - NOT AN OFFICIAL CERTIFICATE` watermark, demo issuer text, sample scope, reference and validity. Real publication requires agency-approved template, authorized signing arrangement, independently verified signature evidence where required, immutable stored artifact and registry commit. A typed image of a signature or QR code is not an approved digital signature.

## 6. Unknown signing outcomes

A timeout after a request may have reached the signer is UNKNOWN. Record provider request ID, artifact hash, request time and attempt state. Lookup by the same stable request ID. If provider confirms completion, verify and publish that artifact. If provider conclusively confirms no action, a safe retry can proceed using the same logical identity. If the provider cannot determine the outcome, assign manual reconciliation with approved evidence; do not repeatedly submit until something looks successful.

A stored signed artifact with failed registry commit is recovered by comparing immutable hash and issuance identity, not by generating another certificate. Publication is a short database transaction that checks the still-valid issuance/outcome conditions and current lease. Business decision history remains intact even if a publishing authorization has expired and a new authorized publication action is required.

## 7. Certificate verification and effective status

The public route accepts a high-entropy token. The demo may also accept an exact certificate number under a `TOKEN_OR_NUMBER` public-lookup profile; live number lookup requires explicit public-data approval and rate-limit assessment. The path parameter in the API catalogue is named `{token}` but validated input can represent the approved exact lookup form; arbitrary fuzzy premises/person search is not supported.

Query the canonical registry or an approved source with a configured freshness budget. Derive current expiry at query time, not only from a nightly job. Return the explicit status and checked-at time. A suspended record remains suspended in administrative history and does not establish valid current service if its validity interval has expired. Public presentation follows the approved status precedence and never silently resurrects a record.

Use no-store for current public assertions. A network failure or stale external source yields VERIFICATION_UNAVAILABLE with no active assertion. An unknown identifier is different from a revoked certificate. Do not expose owner contact, private application IDs, detailed findings or full inspection photos. Private certificate PDF download is a different scoped operation.

## 8. Renewal, status changes and continuing obligations

A renewal creates a new linked DRAFT and selects current applicable rules at submission. Copy reusable premises fields only; explicitly revalidate dates, documents and declarations. Original certificate validity is not extended by draft creation or overdue reminder.

Status actions require current effective authority, reason, legal basis/evidence and an immutable instrument. Reinstatement is not offered for a revoked/expired record unless a separate approved legal process is implemented. A new superseding certificate links its predecessor and preserves historical verification information permitted by policy.

Continuing declarations have their own obligation, received evidence and review outcome. Missing a deadline may create escalation but not automatic revocation. Do not impose annual declarations on every service merely because the platform supports the concept.

## 9. External certification registration

This conditional service is not a shortcut around departmental review. Its approved profile defines eligible issuer, required external artifact, signature/trust verification, applicability, source status, registration authority, evidence and public wording. The stored outcome kind is REGISTERED_EXTERNAL, and the external certificate is preserved, not rewritten as if Agni Setu issued it.

Registration may complete only after the approved verification package is accepted. Missing source evidence, unavailable verification or unknown issuer produces a visible blocker. A source record's later status changes trigger authenticated monitoring/reconciliation and an approved local status reflection, not an unauthorized new legal decision.

## 10. Partner-owned case monitoring

Persist authenticated raw/enveloped inbox data before asynchronous application. Deduplicate by `(integration,source_event_id)` and verify body hash on duplicate IDs. Maintain source sequence per entity where available. A source gap or older event remains quarantined/conflicted until reconciliation; it cannot overwrite a newer terminal outcome. Where no sequence exists, use the partner's documented version/ETag and snapshot comparison instead of trusting clocks alone.

The intake endpoint may return202 once a valid authenticated event has been durably stored even if later processing detects a sequence gap; its receipt exposes PROCESSING/CONFLICT, not applied success. Invalid authentication returns401, invalid structural schema returns422, and reused ID with changed payload returns409. All outcomes preserve safe diagnostic evidence.

Do not claim UPYOG or government-API compatibility from similar field names. Implement against the specific supplied partner contract and verify payload, state, identity and acknowledgement semantics in contract tests.

## 11. Conditional payments and appeals

Fees are disabled in the initial demo service. If an approved live service requires payment, it cannot activate until charge calculation, receipt verification, callback authentication, duplicate handling, reconciliation, refund/failed-payment responsibilities and treasury ownership are specified and tested. Never accept a browser-supplied `paid:true` or screenshot as automatic authoritative payment.

Legally filed appeals are similarly conditional: define filing period, admissibility, jurisdiction, authority, evidence, service of notices, remedies and effect on original outcome. A generic support ticket is not a legal appeal. Until approved, show the referral route and keep the source decision unchanged.

## 12. Integration acceptance checklist

For each live adapter: provider contract approved; credentials held in secret manager; endpoint and egress allowlist set; real sandbox success tested; invalid auth tested; duplicate and delayed callbacks tested; known failure and unknown outcome tested; reconciliation demonstrated; dependency outage visible; public fields approved; recovery owner assigned; no demo fallback. Approval of one adapter does not certify the whole service.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
