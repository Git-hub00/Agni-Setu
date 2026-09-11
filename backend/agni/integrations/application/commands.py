"""Operator commands on integrations (API-108 test, API-111 resolve) and the durable
`integration.test` probe job. A resolution applies a *verified* source record fetched from the
approved endpoint - never the quarantined payload as such and never an invented final status."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from agni.identity.authz import AuthzSnapshot, load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.platform import audit, jobs
from agni.platform.commands import (
    AuditEntry,
    CommandHandler,
    CommandOutcome,
    OutboxIntent,
    UnitOfWork,
)
from agni.platform.errors import (
    DependencyUnavailable,
    ExternalOutcomeUnknown,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)
from agni.platform.jobs import JobResult, register
from agni.platform.models import AttemptOutcome, LogicalJob

from ..adapters import get_partner_source
from ..models import (
    ConflictState,
    HealthStatus,
    InboxState,
    Integration,
    IntegrationConflict,
    IntegrationState,
    PartnerEntityState,
    ResolutionOutcome,
)
from ..ports import PartnerSourceNotFound, PartnerSourceUnavailable, PartnerSourceUnknown
from .inbox import apply_snapshot, release_successors

TEST_JOB_KIND = "integration.test"
TEST_CASES: dict[str, tuple[str, ...]] = {
    "partner_case_source": ("connectivity", "auth", "schema"),
    "external_certificate_source": ("connectivity", "issuer_trust"),
}
DEFAULT_TEST_CASES: tuple[str, ...] = ("connectivity",)


def allowed_tests(integration: Integration) -> tuple[str, ...]:
    return TEST_CASES.get(str(integration.provider_kind), DEFAULT_TEST_CASES)


class TestIntegration(CommandHandler[Integration]):
    """API-108: allowlisted, non-destructive probe through the configured adapter; the target
    and credentials come from approved configuration only (no arbitrary URL)."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN)

    def lock_target(self, uow: UnitOfWork) -> Integration | None:
        integration = (
            Integration.objects.select_for_update().filter(pk=uow.envelope.target_id).first()
        )
        if integration is None:
            raise ResourceNotFound("Integration not found")
        return integration

    def apply(self, uow: UnitOfWork, target: Integration | None) -> CommandOutcome[Integration]:
        if target is None:
            raise ResourceNotFound("Integration not found")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = []
        key = str(data.get("test_case_key") or "")
        if key not in allowed_tests(target):
            violations.append(
                Violation(
                    "/test_case_key",
                    "not_allowlisted",
                    f"approved probes: {', '.join(allowed_tests(target))}",
                )
            )
        reason = str(data.get("reason") or "").strip()
        if not (10 <= len(reason) <= 1000):
            violations.append(Violation("/reason", "length", "10 to 1000 characters"))
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state == IntegrationState.DISABLED:
            raise InvalidTransition("Enable the integration before probing it")
        job = jobs.enqueue_job(
            kind=TEST_JOB_KIND,
            aggregate_ref={"integration_id": str(target.pk), "test_case_key": key},
            run_at=uow.now,
            logical_action_id=uuid4(),
            owner_queue_id=target.owner_queue_id,
        )
        return CommandOutcome(
            status=202,
            body={
                "job_id": str(job.pk),
                "integration_id": str(target.pk),
                "test_case_key": key,
                "state": job.state,
                "notice": "A passing probe is not proof that partner workflows are live.",
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "integration",
                    target.pk,
                    "integration.test_requested",
                    {"test_case_key": key, "reason": reason[:200], "mode": target.mode},
                )
            ],
        )


@register(TEST_JOB_KIND)
def run_integration_test(job: LogicalJob) -> JobResult:
    integration = Integration.objects.filter(
        pk=UUID(str(job.aggregate_ref["integration_id"]))
    ).first()
    if integration is None:
        return JobResult(AttemptOutcome.PERMANENT, error_code="RESOURCE_NOT_FOUND")
    key = str(job.aggregate_ref.get("test_case_key") or "connectivity")
    now = jobs.current_clock().now()
    try:
        result = get_partner_source(integration).test(key)
    except PartnerSourceUnavailable as exc:
        return JobResult(
            AttemptOutcome.RETRYABLE,
            error_code="DEPENDENCY_UNAVAILABLE",
            safe_message=str(exc)[:120],
        )
    status = result.status if result.status in HealthStatus.values else HealthStatus.UNKNOWN

    def apply() -> None:
        current = Integration.objects.select_for_update().get(pk=integration.pk)
        current.last_health_status = status
        current.last_health_at = now
        current.last_health_detail = result.detail[:200]
        if status == HealthStatus.FAIL and current.state == IntegrationState.ENABLED:
            current.state = IntegrationState.DEGRADED
        elif status == HealthStatus.OK and current.state == IntegrationState.DEGRADED:
            current.state = IntegrationState.ENABLED
        current.version += 1
        current.save()
        audit.record_audit(
            entity_type="integration",
            entity_id=current.pk,
            action="integration.test_completed",
            actor_id=None,
            request_id=job.logical_action_id,
            at=now,
            summary={
                "test_case_key": key,
                "status": status,
                "detail": result.detail[:200],
                "provider_request_id": result.provider_request_id,
            },
        )

    from django.db import transaction

    def apply_in_transaction() -> None:
        with transaction.atomic():
            apply()

    return JobResult(
        AttemptOutcome.SUCCESS,
        provider_request_id=result.provider_request_id,
        disposition=status,
        apply=apply_in_transaction,
    )


def conflict_scope(snapshot: AuthzSnapshot) -> set[UUID] | None:
    """None = every conflict (administrator); otherwise the supervisor's jurisdictions."""
    if snapshot.has_role(RoleKey.ADMIN):
        return None
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
    if not jurisdictions:
        raise Forbidden("Integration conflicts are owned by operations or the owning desk")
    return jurisdictions


class ResolveConflict(CommandHandler[IntegrationConflict]):
    """API-111: evidence-based resolution by the accountable owner."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        conflict_scope(snapshot)  # raises when neither administrator nor supervisor
        self._snapshot = snapshot

    def lock_target(self, uow: UnitOfWork) -> IntegrationConflict | None:
        conflict = (
            IntegrationConflict.objects.select_for_update(of=("self",))
            .select_related("integration", "inbox", "owner_queue")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if conflict is None:
            raise ResourceNotFound("Conflict not found")
        scope = conflict_scope(self._snapshot)
        if scope is not None and (
            conflict.owner_queue is None or conflict.owner_queue.jurisdiction_id not in scope
        ):
            raise ResourceNotFound("Conflict not found")
        return conflict

    def apply(
        self, uow: UnitOfWork, target: IntegrationConflict | None
    ) -> CommandOutcome[IntegrationConflict]:
        if target is None:
            raise ResourceNotFound("Conflict not found")
        if target.state != ConflictState.OPEN:
            raise InvalidTransition("This conflict is already resolved")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = []
        outcome = str(data.get("outcome") or "")
        if outcome not in {
            ResolutionOutcome.APPLY_VERIFIED_SOURCE,
            ResolutionOutcome.IGNORE_DUPLICATE,
            ResolutionOutcome.REQUEST_RESEND,
            ResolutionOutcome.KEEP_QUARANTINED,
        }:
            violations.append(
                Violation(
                    "/outcome",
                    "invalid",
                    "APPLY_VERIFIED_SOURCE, IGNORE_DUPLICATE, REQUEST_RESEND or KEEP_QUARANTINED",
                )
            )
        reason = str(data.get("reason") or "").strip()
        if not (10 <= len(reason) <= 4000):
            violations.append(Violation("/reason", "length", "10 to 4000 characters"))
        refs = data.get("verification_evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or len(refs) > 10
            or any(not isinstance(r, str) or not (1 <= len(r) <= 200) for r in refs)
        ):
            violations.append(
                Violation("/verification_evidence_refs", "required", "1 to 10 evidence references")
            )
            refs = []
        version = data.get("authoritative_source_version")
        if outcome == ResolutionOutcome.APPLY_VERIFIED_SOURCE and (
            not isinstance(version, str) or not version
        ):
            violations.append(
                Violation(
                    "/authoritative_source_version", "required", "required when applying a source"
                )
            )
        if violations:
            raise ValidationFailed(violations=violations)
        integration = target.integration
        inbox = target.inbox
        basis: dict[str, Any] = {
            "outcome": outcome,
            "reason": reason,
            "verification_evidence_refs": list(refs),
            "authoritative_source_version": version,
        }
        intents: list[OutboxIntent] = []
        applied_sequence: int | None = None
        if outcome == ResolutionOutcome.APPLY_VERIFIED_SOURCE:
            try:
                record = get_partner_source(integration).lookup_case(target.source_entity_id)
            except PartnerSourceUnavailable as exc:
                raise DependencyUnavailable(
                    "The approved source endpoint is unavailable; nothing was applied"
                ) from exc
            except PartnerSourceUnknown as exc:
                raise ExternalOutcomeUnknown(
                    "The source answered ambiguously; keep the conflict open"
                ) from exc
            except PartnerSourceNotFound as exc:
                raise InvalidTransition(
                    "The source has no such record; no outcome may be invented"
                ) from exc
            if record.source_version != version:
                raise InvalidTransition(
                    "The verified source version differs from the one you cited",
                    extensions={"source_version": record.source_version},
                )
            state, _ = PartnerEntityState.objects.select_for_update().get_or_create(
                integration=integration, source_entity_id=target.source_entity_id
            )
            if (
                record.sequence is not None
                and state.applied_sequence is not None
                and record.sequence < state.applied_sequence
            ):
                raise InvalidTransition(
                    "The source record is older than the reflection already applied"
                )
            apply_snapshot(
                state,
                integration,
                sequence=record.sequence,
                source_version=record.source_version,
                occurred_at=record.fetched_at,
                event_id=f"lookup:{record.provider_request_id}",
                payload=record.payload,
            )
            applied_sequence = state.applied_sequence
            basis["lookup"] = {
                "provider_request_id": record.provider_request_id,
                "source_version": record.source_version,
                "sequence": record.sequence,
                "fetched_at": record.fetched_at.isoformat() if record.fetched_at else None,
            }
            if inbox is not None and inbox.state in (InboxState.CONFLICT, InboxState.QUARANTINED):
                inbox.state = InboxState.PROCESSED
                inbox.disposition = "SUPERSEDED_BY_VERIFIED_SOURCE"
                inbox.processed_at = uow.now
                inbox.save(update_fields=["state", "disposition", "processed_at"])
            release_successors(integration, state, uow.now)
            intents.append(
                OutboxIntent(
                    event_type="integration.source_applied.v1",
                    aggregate_type="partner_entity",
                    aggregate_id=state.pk,
                    payload={
                        "integration": integration.key,
                        "source_entity_id": target.source_entity_id,
                        "sequence": record.sequence,
                        "source_version": record.source_version,
                        "via": "reconciliation",
                    },
                )
            )
        elif inbox is not None:
            if outcome == ResolutionOutcome.IGNORE_DUPLICATE:
                inbox.state = InboxState.PROCESSED
                inbox.disposition = "IGNORED_DUPLICATE"
                inbox.processed_at = uow.now
            else:  # REQUEST_RESEND / KEEP_QUARANTINED keep the data out of the reflection
                inbox.state = InboxState.QUARANTINED
                inbox.disposition = outcome
            inbox.save(update_fields=["state", "disposition", "processed_at"])
        target.state = ConflictState.RESOLVED
        target.outcome = outcome
        target.resolution_basis = basis
        target.resolved_by = uow.actor
        target.resolved_at = uow.now
        target.save(
            update_fields=[
                "state",
                "outcome",
                "resolution_basis",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        from .projections import conflict_body

        return CommandOutcome(
            status=200,
            body={**conflict_body(target), "applied_sequence": applied_sequence},
            aggregate=target,
            audits=[
                AuditEntry(
                    "integration_conflict",
                    target.pk,
                    "integration.conflict_resolved",
                    {
                        "outcome": outcome,
                        "reason": reason[:200],
                        "evidence_refs": list(refs)[:10],
                        "authoritative_source_version": version,
                        "applied_sequence": applied_sequence,
                    },
                )
            ],
            intents=intents,
        )
