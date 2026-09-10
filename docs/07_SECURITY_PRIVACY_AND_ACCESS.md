# Identity, authorization, security and privacy specification

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Trust boundaries

Untrusted inputs include every browser field, attachment, filename, uploaded PDF, GPS coordinate, client timestamp, local offline record, webhook and user-selected ID. The server session establishes an authenticated identity, not blanket authority. An OIDC provider establishes staff subject identity; Agni Setu's approved grants establish permitted service actions. A scanner establishes a technical file result, not correctness of its contents. A QR code points to a record; it is not a digital signature or evidence that a building is safe.

Database, object store, broker, cache, identity provider and administrative consoles are private network services. Only the reverse proxy's approved HTTPS entry points and explicitly approved partner endpoints are public. Separate development, demonstration and live trust domains.

## 2. Applicant OTP requirements

Use cryptographically secure random six-digit codes in a purpose-bound challenge. Demo defaults: five-minute lifetime, five verification attempts, 60-second resend cooldown, five sends per contact per hour and twenty per source IP per hour, with configurable abuse controls and careful shared-network handling. These are engineering starting values, not legal requirements. Single-use consumption, attempt increment and expiry validation are atomic. Resending supersedes the older challenge for the same purpose.

Store only a keyed MAC over challenge ID, purpose and code using a dedicated server secret/pepper, not a plain or merely unsalted code hash. A six-digit space is small; offline brute force resistance requires protecting the verification secret. Never log codes or include them in ordinary API responses. The local sink is isolated to demo/test and has no actual outbound provider. A rate-limit store outage fails closed for OTP sends and other abuse-sensitive writes; ordinary authenticated case reads may continue if safely authorized.

Successful verification rotates the session ID and CSRF context. A contact is not proof of premises ownership, professional credentials or statutory authority. Account linking and recovery must not rely on a user claiming an existing contact belongs to them. Contact replacement requires current step-up authentication and verification of the new contact; high-risk recovery uses an approved support process with audit and independent evidence.

## 3. Staff OIDC and sessions

Use authorization-code flow with PKCE, state and nonce via a maintained OIDC library. Validate issuer, signature, audience, authorized party where applicable, expiration, nonce and redirect URI. Fetch signing keys from the configured issuer, handle rotation with bounded caching and reject unknown/invalid signatures. Use issuer+subject as the stable identity; email matching alone cannot silently link a privileged account.

Only previously approved staff invitations/identity mappings can obtain staff workspaces. Provider group claims may assist provisioning but do not automatically create decision powers unless an explicitly reviewed mapping permits it. Require the agency's approved MFA/step-up policy for privileged actions. Demo Keycloak accounts must be separate from real identities.

Use Django database sessions and secure HttpOnly cookies. Production cookie: Secure, HttpOnly, SameSite=Lax unless the approved identity flow requires another reviewed setting, narrow path/domain and no broad parent-domain sharing. No access or refresh tokens in localStorage. Store provider tokens only when necessary, encrypted server-side with bounded retention. Never expose them in `/me`.

Engineering session defaults: 30-minute interactive idle window and eight-hour absolute session lifetime; privileged operations require recent authentication within 15 minutes. Actual agency policy may shorten/adjust these. Recheck principal active state and authorization epoch on every command and sensitive read. Disabling a staff account revokes sessions and changes the epoch. Offline cached work cannot bypass a server revocation.

## 4. CSRF, CORS and browser policy

Same-origin SPA/API is the default. Unsafe requests require CSRF and Origin validation, including login/OTP endpoints. Reject wildcard credentialed CORS. Production allowed hosts and trusted origins are explicit. Use CSP with project asset allowlists and no arbitrary inline scripts, frame-ancestors restriction, nosniff, Referrer-Policy and Permissions-Policy appropriate to camera/geolocation features. HSTS is enabled only after HTTPS deployment is correctly configured. Cookies and tokens are never included in analytics URLs.

Use route-level authorization before loading sensitive content, but backend scope is the final enforcement boundary. Clear query caches and offline authorization metadata when identity changes. Do not cache authenticated API responses globally in a service worker. Public verification responses use `Cache-Control: no-store` when asserting current status.

## 5. Permission matrix

Legend: O = own/explicit delegation; A = current assigned attempt; J = permitted jurisdiction/service; G = separately approved governance/operations scope; R = read-only permitted scope; P = minimal public fields; '-' = denied. These are minimum role boundaries, not automatic grants.

| Action | Applicant | Officer | Supervisor | Leadership | Operations admin | Policy approver | Public |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Create/edit draft and submit | O | - | - | - | - | - | - |
| Read application | O | A | J | R | Only incident-specific G | - | - |
| Read applicant documents | O | A minimum | J | Only separately approved R | Only incident-specific G | - | - |
| Schedule/reassign inspection | - | Read A | J | - | - | - | - |
| Submit report | - | A | Only separately assigned actor | - | - | - | - |
| Publish notice / verify finding | - | Recommend A | J plus capability | - | - | - | - |
| Respond to notice | O | - | - | - | - | - | - |
| Decide/authorize issuance | - | - | Effective decision grant | - | - | - | - |
| Certificate status instrument | - | - | Effective status grant | - | - | - | - |
| Read aggregated reports | O limited | A limited | J | R | Operational metrics G | Policy impact R | - |
| Export sensitive reports | O permitted | - | J plus purpose | R plus export grant | Incident-specific G | - | - |
| Prepare policy | - | - | Optional scoped proposal | - | G | Cannot self-approve own edits | - |
| Approve policy | - | - | Only separate approved grant | - | - | G independent | - |
| Provision staff | - | - | Request only | - | G with approved request | - | - |
| Approve statutory grant | - | - | Designated grant authority only | - | - | Only separately designated grant authority | - |
| Recover jobs | - | - | View relevant case job | - | G | - | - |
| View audit | Own public timeline only | A limited | J | R | G redacted | Policy scope R | - |
| Verify certificate | P | P | P | P | P | P | P |

Do not equate `is_superuser` or database-owner credentials with routine application privileges. Production Django admin is disabled or restricted to a audited break-glass route without business-state edit forms. The app's normal database role is not a schema owner and cannot update/delete append-only audit tables.

## 6. Authorization algorithm and revocation races

The authorization decision considers identity active state, role capability, effective interval, jurisdiction, service, category, delegation/assignment and conflict-of-interest/separation rules. Deny by default. Read selectors apply these constraints before searching, counting or exporting. Mutations re-evaluate them in the transaction under the subject authorization fence and resource lock. Grant approval/revocation uses the same fence. This supplies a well-defined serialization order rather than an unsafe check-then-write gap.

Admin-prepared grants require approval by an independently designated grant authority. Initial live administrators and grant approvers are bootstrapped through a controlled documented ceremony with two responsible people, signed approval evidence, short-lived bootstrap access and revocation after setup. Do not solve bootstrap by allowing every new admin to authorize themselves. Demo seeds may create synthetic grants but only in a demo database and must still exercise separation checks in normal commands.

## 7. Attachment and rendering safety

Require authorization before reserving an upload and before every preview/download. Allowlist extensions and sniffed types, enforce file count/byte/page/pixel limits, verify checksum, and scan in quarantine. Reject executable formats and active HTML/SVG for ordinary evidence. Demo default permits PDF, JPEG and PNG, maximum 10 MiB per file and 50 MiB per application upload batch. Limit PDF page count and decompression/pixel expansion to protect workers. Do not treat the browser-supplied MIME as authoritative.

Objects are private, immutable-versioned and addressed by server-generated keys. A scan result binds the exact object version and checksum to avoid scan-then-replace attacks. Rendering uses isolated processes with restricted filesystem/network, memory/time limits and no external URL fetches. PDF/QR templates are project-controlled and escaped. Preserve original evidence while generating sanitized preview derivatives separately.

Prefer authenticated proxy download for sensitive evidence; short-lived signed URLs are bearer capabilities and may remain usable until expiration even after session revocation. When signed URLs are approved, use a maximum demo lifetime of 60 seconds, single object/version, least method scope, restrictive content disposition and documented residual risk. Public storage buckets and permanent evidence URLs are forbidden.

## 8. Data minimization and privacy

Collect only fields required by the enabled service. Public verification exposes a separately approved small schema. Full owner identity, contact data, drawings, inspection photos, exact internal notes and officer personal data are not public by default. Audit and operational payloads store safe summaries and references, not full copies of all personal fields.

Record the data owner, purpose, sharing basis, records schedule, approved hosting and incident route for every live dataset. No blanket claim of DPDP or other legal compliance is made by choosing these controls. Applicable legal obligations, commencement, consent/notice grounds and retention must be reviewed by the agency. A technical erase request cannot destroy records that the approved legal hold or records policy requires retaining.

## 9. Threat scenarios and controls

| Threat | Required control and test |
| --- | --- |
| Cross-applicant case or file access | Scoped selectors and download checks; substitute another valid UUID in every sensitive endpoint. |
| Privilege escalation | No role in registration; approved grant lifecycle; direct admin decision attempts denied. |
| CSRF/login CSRF | CSRF and Origin tests on every unsafe browser endpoint, including OTP. |
| Session theft/fixation | Secure cookies, session rotation, MFA for staff and recent-auth controls. |
| Malicious file or parser exploit | Quarantine, scanner, sandboxed preview/render, resource limits and no network fetch. |
| SQL injection | Parameterized ORM/SQL and allowlisted search/sort fields. |
| Stored XSS | Escaped plain-text rendering; no user HTML inserted into page or PDF template. |
| Forged/out-of-order webhook | Provider authentication, signed raw bytes, replay window, unique source IDs and sequence handling. |
| Duplicate irreversible effect | Stable logical IDs, DB uniqueness, provider idempotency and reconcile-before-retry. |
| Sensitive export leakage | Current reauthorization, minimized fields, expiry, audit and formula neutralization. |
| Insider audit alteration | Restricted DB role, separately stored signed/checksummed checkpoints, monitored access. |
| Lost/shared offline device | Bounded minimum cache, managed-device control, app lock; shared-device caching disabled. |
| Resource exhaustion | Request limits, rate limits, pagination, bounded job concurrency and circuit breakers. |

## 10. Security release gates

Run dependency, secret, container and configuration scans; test authorization boundaries and dangerous uploads; review the threat model; validate response headers; demonstrate session and grant revocation; inspect logs for sensitive data; independently review live signing and public verification. Record unresolved findings by severity, owner and expiry. No critical/high unresolved issue affecting identity, authority, data exposure or outcomes is accepted for live activation without the designated accountable security decision.


## 12. Simulation permission

`policy.simulate` belongs to Operations administrator and Policy approver only within their existing policy-read scope. It runs fixed server-owned tests and writes an attributed result; it does not grant preparation, approval or activation authority. Candidate read checks, CSRF, ETag and resource limits still apply. A simulation result cannot be submitted by the browser as proof that a test passed.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
