# Engineering standards, SOLID application and code review

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. Practical design rules

Use explicit modules, small typed interfaces and testable functions. Apply SOLID to actual change boundaries; do not create an interface, factory and abstract repository for every trivial model. The goal is understandable and reliable code, not maximum class count.

| Principle | Agni Setu application | Reject in review |
| --- | --- | --- |
| Single responsibility | `SubmitApplication` coordinates submission; calendar functions calculate time; renderer generates bytes | One view that uploads, scans, changes state, sends SMS and formats HTML |
| Open/closed | Add a new notification provider behind a stable port and contract tests | Provider-specific branches scattered through case commands |
| Liskov substitution | Every ObjectStore adapter enforces equivalent private access and immutable version semantics | Demo adapter reports success without preserving the interface's required evidence |
| Interface segregation | Separate `Signer.submit`, `Signer.lookup` and `SignatureVerifier.verify` needs | One universal gateway object with dozens of unused methods |
| Dependency inversion | Decisions depend on typed authorization/time/evidence services, not HTTP transport | Domain code directly importing DRF Request or calling external gateways |
| DRY | One state/permission/schema registry with generated API types | Two conflicting handwritten enums in client and backend |
| KISS / YAGNI | Modular monolith, SQL reporting and foreground polling first | Microservices, generic workflow scripting or AI for deterministic checklist rules |
| Least privilege | Explicit scope in reads, mutations, downloads and workers | `is_staff` interpreted as universal access |
| Fail safely | Unknown signing or verification outcome remains pending/unverifiable | Catch-all exception returns success or approved status |

## 2. Backend code contracts

Use Python type annotations on public functions, DTOs as frozen dataclasses where appropriate, enums for state, timezone-aware datetime values and Decimal for decimal quantities. Return a typed command result or raise a typed domain error mapped at one HTTP boundary. Do not raise raw database exceptions to users.

Every command receives an explicit actor context, resource ID, expected version, idempotency key and injected clock. Do not let a request body supply the effective actor, approved role, current date or certificate status. An application service may use ORM repositories directly if this keeps the code clear; introduce a repository interface when there is a real isolation/testability boundary, not to hide arbitrary unbounded queries.

Do not put business workflow in Django signals, model `save()` side effects or Celery decorators. Signals may support instrumentation without changing business outcomes. Avoid `ATOMIC_REQUESTS` as the substitute for intentional transactions; commands explicitly define their boundaries. Handle uniqueness races inside a nested transaction/savepoint where required so the outer transaction remains usable after an IntegrityError.

## 3. Frontend code contracts

TypeScript strict mode is required. Avoid `any`, unsafe type assertions and manually duplicated wire types; documented narrow exceptions require tests. Generate API DTOs from the committed schema. Use feature-based modules with shared accessible primitives. Query keys include user/scope identity; clear sensitive query caches on logout and identity changes.

Keep server state in TanStack Query, ephemeral UI state in component/context, and explicit offline operations in Dexie. Do not mirror the whole database into a global Zustand/Redux store. Forms use schema validation and field-array abstractions for notices/checklists; never serialize DOM HTML as business data. Do not optimistically mark approval, submission, finding closure or certificate publication successful.

Render notes as escaped plain text or a tightly constrained sanitized format. Do not use `dangerouslySetInnerHTML` for applicant content. All visible strings go through locale keys; English copy is required, Hindi translations are reviewed before enabling that locale. Locale switching cannot change identifiers, dates' stored values or policy semantics.

## 4. Error handling and observability

Catch expected domain errors at the API boundary, translate to documented error codes and log safe correlation metadata. Unexpected exceptions produce INTERNAL_ERROR and an alert. Never swallow errors to satisfy a UI test. Never log request bodies containing OTPs, credentials, complete building plans or personal identity evidence.

The request ID propagates through command receipt, event, job, provider attempt and audit. A log entry describes component, operation, outcome, duration and safe IDs. Metrics labels must remain low-cardinality: module, operation family, provider type, outcome code. Case numbers and emails do not belong in metric labels.

## 5. Tests and fixtures

Pure domain tests use fake clocks and explicit snapshots. Integration tests use real PostgreSQL for transaction, constraint and locking behavior; SQLite or a mocked ORM cannot prove those behaviors. External provider contracts run against named simulators with success, failure and unknown outcomes. Browser tests assert server results and reload pages before declaring a workflow complete.

Fixtures use synthetic contacts and accepted event sequences. Do not insert unrealistic COMPLETED cases with no decisions simply to produce dashboard counts. Tests must be independent and leave the shared developer environment untouched. Fault tests use dedicated isolated services; never kill a user-owned production database.

## 6. Review checklist for each change

Check requirement IDs and scope; allowed/forbidden actors; expected-version and idempotency behavior; transaction/audit/outbox boundary; cross-record scope; retry/timeout semantics; UI loading/empty/error/conflict states; keyboard/mobile behavior; tests and migration safety; logs/secrets; dependency lock changes; documents and evidence updated. A feature lacking its sad-path tests remains incomplete.

Do not suppress a failing test, widen permission filters, disable CSRF, accept unscanned files or remove a database constraint to make a demo work. Fix the underlying issue. Any intentionally skipped test has a reason, owner and release impact, not just a skipped marker.

## 7. Git and multi-agent collaboration

Inspect `git status` before edits. Preserve existing uncommitted user changes. Use a scoped branch or worktree. One agent owns a migration series and shared schema at a time. Parallel work is acceptable for isolated UI/read-only modules after contracts are fixed; do not have Codex and Claude simultaneously rewrite auth, migrations or common DTOs in the same working tree.

Commits contain one coherent change and its tests. PR descriptions list FR/TR/API/UI/AT identifiers, behavior changed, migration/rollback considerations and actual commands run. Do not claim tests passed when a tool was unavailable. Never commit local secrets, real case evidence, generated dependency directories or large unreviewed logs.

## 8. Definition of done

The build compiles and runs; formatting, type checks and relevant tests pass; permission and concurrency negatives are covered; no unexplained console errors; required migrations are repeatable; all feature UI actions have real server effects; asynchronous status is truthful; operation/audit evidence is available; documentation matches the implementation; release gates are not bypassed. Remove unused implementation code only after reference search and tests, never delete the user's source documents or evidence to make the repository look clean.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
