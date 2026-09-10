# Agni Setu - agent working agreement

This repository uses implementation baseline 2.0.0. Read README.md and
`docs/21_IMPLEMENTATION_STATUS.md` before planning changes. Inspect current code,
branch and worktree first; do not overwrite unrelated user work or existing instructions.

## Required behavior

- Build the next approved B00-B20 phase from `docs/17_AGENT_TASK_CARDS.md` and the
  detailed `docs/10_BUILD_GUIDE.md`. Read its linked functional/workflow/UI/API/data/
  security/test sections. Work in reviewable vertical slices, not a one-shot rewrite.
- Selected greenfield stack: Django 5.2 LTS/DRF/PostgreSQL 17; React 19/TypeScript/Vite 8;
  Celery/RabbitMQ; Valkey cache; private S3 storage. Exact patches/digests are B00
  evidence, not guesses. Do not switch frameworks silently or auto-migrate existing data.
- Keep source prototype under references read-only. Preserve user-facing journeys and
  seven workspaces; use document23 for all 94 source controls and 20 forms. Production
  authorization and persistence must be server-side, not copied from browser mock code.
- Preserve eleven application states. Certificate/job/inspection states are separate.
  Never automatically approve/reject for elapsed time or compensate a mandatory failure
  with a score. Decisions require current authority, evidence and immutable rationale.
- Use domain services with small ports/adapters, typed boundaries and explicit errors.
  SOLID is for maintainability, not an excuse to add unused frameworks/abstractions.
- Scope reads and writes by current actor/ownership/jurisdiction/assignment/grant. Never
  trust a client role, owner, state, signature, scanner status or approved-policy flag.
- Critical commands need version preconditions, stable idempotency, transactional
  events/audit/outbox and current-authority fences. Never call irreversible providers
  inside the database transaction. Reconcile unknown outcomes before blind retries.
- Offline saved work is not a server receipt. Preserve immutable operation identity,
  accepted evidence and explicit report/failed-visit conflict resolution; no last-write-wins.
- Use approved demo fixtures and local provider sinks. Never invent law, authority,
  credentials, test results, government integration or real digital-signing validity.
  Live gates are in document19. Demo-only routes must not exist in live mode.
- Do not send real messages, mutate live data, reset databases, delete unrelated files,
  publish/deploy, purchase services or expose secrets without explicit authorization.
  Use dedicated test databases/Compose projects; never reset the user's default database.
- Run relevant unit/integration/API/UI/error/recovery tests against real components when
  those components are the subject of the test. Restart affected processes and smoke-check.
  Report exact commands/results. Distinguish PASS, FAIL, BLOCKED and NOT_RUN.
- Update status21 and task evidence with files changed, migration impact, actual tests,
  limitations and next safe step. Do not mark a phase complete from code inspection alone.
- When specifications conflict or an essential live rule is absent, record the blocker
  and ask a focused question. Continue independent safe local work; never guess a power.

## Task-specific references

UI:03 and23. Workflow:01/02. Storage:05. HTTP/events:06 and24. Security:07.
Jobs:08. Offline:09. Tests:11/13/15. Operations:12. Integrations:16.
Decisions:14. Engineering:18. Sources:20. Read only relevant detail after this entrypoint.
