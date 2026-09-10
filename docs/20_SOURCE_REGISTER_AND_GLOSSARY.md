# Source register, provenance, decisions and glossary

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Evidence hierarchy

This pack is a new implementation baseline, not a claim that the older source documents were complete or that prototype simulation established production readiness. User-authorized stack reselection and engineering additions are captured explicitly in ADRs14. Source-derived user journeys and prototype UI patterns are preserved where safe; deliberate behavior differences are listed in document23. Government-specific rules remain approval gates19.

When reading sources, distinguish: (a) observed source content; (b) newly specified engineering behavior; (c) external framework capability; (d) proposed target; and (e) unresolved live policy decision. Do not silently convert an assumption into a legal rule, test result or deployment fact.

## 2. Local project sources and exact SHA-256

Only the HTML is copied into this pack as a read-only visual reference. Other source artifacts remain the user's existing conversation documents; their hashes make the reviewed versions identifiable. No public URL is invented for a private source.

| Source | File | SHA-256 | Use |
| --- | --- | --- | --- |
| S01 | Agni_Setu_Project_Specification.docx | e93de0763753ef961f1811b1739731c93a6a4870cfbce0ef70256e40c291db04 | Latest standalone business/functional/technical baseline, AGNISETU-SP-001 v1.0, 06 September2026. |
| S02 | Agni_Setu_Interactive_Prototype.html | 5928bc6487a9e2af46fd636ac2258cd207bccee0d5ea36d69e8c0a4f6a226180 | Executable visual/interaction reference;28 fixtures,7workspaces,11states,94named actions and 20forms inspected. |
| S03 | Agni_Setu_Critical_Engineering_Review.docx | 49c547485f7296a31959031e715bc2a3ced039bf63fde451fb3586b81ca001df | Design-review context explaining legal, integrity and implementation gaps; not an official approved requirement. |
| S04 | Agni_Setu_IEEE_Conference_Paper.docx | 53da08dce10f1cd8b20e6e2f3510ae8662c23ae59ea37bb5fe570b7708dc229a | Research narrative and prior prototype evaluation context; not evidence of the new backend implementation. |
| S05 | Agni_Setu_SIH1623_Project_Blueprint.docx | e1ffcb6f4e1a18f4b6f9bf99449e94d91a3f1c293bdbe652da232129a59c4e03 | Earlier Flask/MongoDB proposal. Retained as historical source; not the selected baseline stack. |
| S06 | WhatsApp Image 2026-07-13 at 9.10.22 PM.jpeg | 2726e4a06782c72eea63f9c15e24ca3ad5a425f364937f5204a85eb9c969ddea | User-provided SIH PS1623 screenshot specifying application monitoring, inspections, follow-ups and NOC issuance. |

## 3. Primary technical references

Reviewed for the stack/design on 09 September 2026. URLs are implementation references; upstream documentation can change. Resolve current supported patch releases and image digests during B00 and record what actually installed/tested. Stable release family selection is not a promise that all dependencies will remain compatible indefinitely.

| Reference | Title | Official URL | What it supports |
| --- | --- | --- | --- |
| R01 | Django release support | https://www.djangoproject.com/download/ | Django 5.2 LTS remains supported through April2028; the selected line prioritizes stability, not latest feature version. |
| R02 | PostgreSQL support policy | https://www.postgresql.org/support/versioning/ | PostgreSQL 17 is supported through November8,2029. Use supported patched minor releases. |
| R03 | DRF3.16 compatibility | https://www.django-rest-framework.org/community/3.16-announcement/ | DRF3.16 documents support for Django5.2; complete project dependency integration still needs B00 verification. |
| R04 | Node release schedule | https://nodejs.org/en/about/previous-releases | Node24 is an LTS line selected for frontend tooling; freeze patched version during B00. |
| R05 | React 19 release | https://react.dev/blog/2024/12/05/react-19 | React 19 is the selected UI family; this does not imply every optional library combination has been tested. |
| R06 | Vite 8 announcement | https://vite.dev/blog/announcing-vite8 | Vite 8 stable release and supported Node requirements inform the build-tool selection. |
| R07 | Django transactions | https://docs.djangoproject.com/en/5.2/topics/db/transactions/ | Atomic database operations and on_commit behavior; the transactional outbox is this project design, not an automatic Django guarantee. |
| R08 | PostgreSQL range constraints | https://www.postgresql.org/docs/17/rangetypes.html | Range/exclusion mechanisms support conflict-safe appointment design. |
| R09 | Celery task guide | https://docs.celeryq.dev/en/stable/userguide/tasks.html | Task acknowledgment/retry behavior requires idempotent application design; no end-to-end exactly-once promise. |
| R10 | RabbitMQ/Erlang compatibility | https://www.rabbitmq.com/docs/which-erlang | Select a supported matching broker/runtime combination and pin image digest at B00. |
| R11 | Valkey release downloads | https://valkey.io/download/ | Supported release family must be verified and locked; cache is not authoritative case storage. |
| R12 | Keycloak containers | https://www.keycloak.org/server/containers | Development mode is not a production identity deployment. |
| R13 | Authlib Django client | https://docs.authlib.org/en/stable/oauth2/client/web/django.html | Supported OAuth/OIDC integration boundary; issuer/state/nonce/PKCE validation remains required. |
| R14 | OWASP file upload guidance | https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html | Layered extension/content/size/storage/access defenses inform document intake. |
| R15 | RFC9457 | https://www.rfc-editor.org/rfc/rfc9457.html | Problem Details response format; application error codes and retry semantics are project-specific. |
| R16 | WCAG2.2 | https://www.w3.org/TR/WCAG22/ | Accessibility conformance target; a styled component library does not establish conformance by itself. |
| R17 | Background Sync availability | https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API | Background synchronization is not universally supported; explicit foreground sync is mandatory here. |
| R18 | Browser storage limits | https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria | Storage quotas and eviction mean unsynchronized browser bytes are not guaranteed durable. |
| R19 | Community MinIO repository | https://github.com/minio/minio | Repository archive/maintenance status is relevant to not selecting a legacy community binary as the new default deployment. |
| R20 | SeaweedFS overview | https://github.com/seaweedfs/seaweedfs/blob/master/README.md | Local S3-compatible development option; explicit credentials and restricted networking required. |
| R21 | SeaweedFS mini quick start | https://raw.githubusercontent.com/wiki/seaweedfs/seaweedfs/Quick-Start-with-weed-mini.md | Mini is a local development/test choice, not a qualified production storage architecture. |
| R22 | Codex AGENTS instructions | https://developers.openai.com/codex/guides/agents-md/ | Root/nested instructions are discovered by scope. Keep root concise and load task documents deliberately. |
| R23 | Claude Code project memory | https://code.claude.com/docs/en/memory | CLAUDE.md supports importing AGENTS.md; task specifications should be read explicitly, not assumed loaded. |

## 4. What is not established by these sources

No source in this pack establishes a live departmental deployment, approved statutory checklist/fee/validity, government SSO credentials, authorized digital signer, audited production-security conformance or achieved performance/SLA improvement. No government historical dataset is included. The IEEE paper's prior prototype checks do not transfer to the new selected backend stack.

A six-page IEEE formatting template is not a software requirement and is not copied into this implementation pack. The presentation is a communication artifact, not a machine-authoritative API/state contract. Unsupported historical market/backlog claims from older material are not required for building this product and are not used as runtime assumptions.

## 5. Decision provenance

The 11 states and seven workspaces derive from the current specification/prototype. PostgreSQL/Django, server-side sessions, broker/outbox design, stronger immutable command protocol, detailed evidence scanning and explicit operational gates are newly selected engineering decisions. Exact visual metrics, safe file limits, demo OTP/session limits, workload targets and fixture clock are proposed defaults documented for reproducibility, not externally measured findings.

## 6. Glossary

| Term | Meaning in this project |
| --- | --- |
| Application | A tracked request; its state is not the same as certificate status. |
| Premises | The building/site to which one or more applications relate. |
| Receipt | Canonical acknowledgment of accepted submission; a saved draft is not a receipt. |
| Policy version | Approved immutable set of service rules pinned to a case. |
| Authority grant | Effective-dated permission to exercise a specific power within scope; not just a role label. |
| Role | Workspace grouping of capabilities; statutory authority still requires explicit grant. |
| Delegation | Auditable permission for one actor to act for a beneficiary within limited scope. |
| Scrutiny | Document/application completeness review before or alongside inspection planning. |
| Inspection attempt | A separately attributable planned/performed/failed/cancelled visit. |
| Observation | One checklist item result and evidence, not a final decision. |
| Finding | Identified deficiency with a reviewable lifecycle. |
| Notice | Published itemized information or deficiency request. |
| Response revision | Immutable applicant reply/evidence linked to notice items. |
| Mandatory blocker | Unresolved required condition that prevents favorable decision; cannot be offset by a score. |
| Decision | Reasoned authorized approve/reject instrument distinct from rendering/issuing the certificate. |
| Obligation | Owned work with a clock, due basis, calendar, pause rules and threshold actions. |
| Stage instance | One entry into a workflow state; repeated entry is a new cycle. |
| SLA | Configured service target; example target is not a verified statutory deadline. |
| Idempotency | Retrying the same identified command does not duplicate its canonical effect. |
| ETag / If-Match | Version precondition preventing a stale update from overwriting newer state. |
| Outbox | Database-persisted intent to execute external work after the business transaction commits. |
| Inbox | Durable authenticated incoming event record used for duplicate and ordering control. |
| Lease / fencing | Bounded worker ownership and token checks preventing stale workers from committing newer work. |
| Unknown outcome | Provider may have executed an action but acknowledgment was lost; reconcile before repeating. |
| Reconciliation | Evidence-based comparison of local and external outcomes, not a fabricated success flag. |
| PWA | Installable web application with bounded offline capability; not a guarantee of native-device control. |
| Quarantine | File stored pending safe acceptance, not usable approved evidence. |
| Effective status | Current certificate assertion derived from administrative state, validity and trustworthy source freshness. |
| Modular monolith | One backend deployment with clear domain modules and explicit dependency boundaries. |
| SOLID | Single responsibility, open/closed design, substitutable interfaces, small interfaces and dependency inversion. |
| Port/adapter | Domain-defined boundary for external services and its replaceable implementation. |
| RBAC + scope | Role permissions combined with ownership/jurisdiction/assignment and current authority checks. |
| SLO | Engineering service reliability target; distinct from an applicant service deadline. |
| RPO / RTO | Target tolerated data-loss interval / restoration time, proven by recovery drills. |
| SBOM | Inventory of shipped software components for supply-chain review. |
| Demo mode | Isolated synthetic environment; never permitted to issue valid government certificates. |

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
