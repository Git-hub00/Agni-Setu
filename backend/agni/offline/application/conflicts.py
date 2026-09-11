"""Reviewed conflict proposals (API-051/052; docs/09 s.7). A proposal stores what the device
holds and why; a supervisor decides PROPOSE_NEW_REPORT / REINSPECTION_REQUIRED / DECLINE with a
reason. Nothing here rewrites an accepted report or reinstates a superseded assignment."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agni.cases.models import EventAudience
from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.inspections.application.commands import _case_event, _intent, _reason
from agni.inspections.models import Assignment, Inspection
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)

from ..models import ConflictOutcome, ConflictState, ReportConflict, SyncOperation


def conflict_body(c: ReportConflict) -> dict[str, Any]:
    return {
        "conflict_id": str(c.pk),
        "inspection_id": str(c.inspection_id),
        "operation_id": str(c.operation_id),
        "proposer": str(c.proposer_id),
        "application_version_seen": c.application_version_seen,
        "safe_local_summary": c.safe_local_summary,
        "reason": c.reason,
        "local_manifest_sha256": c.local_manifest_sha256,
        "server_snapshot": c.server_snapshot,
        "state": c.state,
        "outcome": c.outcome,
        "resolution_reason": c.resolution_reason or None,
        "selected_evidence_ids": list(c.selected_evidence_ids),
        "resolved_by": str(c.resolved_by_id) if c.resolved_by_id else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat(),
        "version": c.version,
    }


class ProposeConflict(CommandHandler[Inspection]):
    """API-051: an officer who held the package (current or former assignee) records a safe
    conflict proposal. No If-Match: the device's version is stale by definition."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff propose inspection conflicts")

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        return None

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        inspection = (
            Inspection.objects.select_related("application__owner_queue", "current_assignment")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if (
            inspection is None
            or not Assignment.objects.filter(inspection=inspection, officer=uow.actor).exists()
        ):
            raise ResourceNotFound("Inspection not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "operation_id",
            "local_manifest",
            "safe_local_summary",
            "reason",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        seen = data.get("application_version")
        if not isinstance(seen, int) or isinstance(seen, bool) or seen <= 0:
            violations.append(
                Violation("/application_version", "invalid", "positive integer required")
            )
            seen = 0
        try:
            operation_id = UUID(str(data.get("operation_id")))
        except ValueError:
            violations.append(Violation("/operation_id", "invalid", "must be a UUID"))
            operation_id = None
        manifest = data.get("local_manifest")
        if not isinstance(manifest, dict) or not manifest:
            violations.append(
                Violation("/local_manifest", "invalid", "versioned SyncOperation manifest")
            )
            manifest = {}
        summary = data.get("safe_local_summary")
        if not isinstance(summary, str) or not (10 <= len(summary.strip()) <= 4000):
            violations.append(Violation("/safe_local_summary", "length", "10 to 4000 characters"))
            summary = ""
        reason = _reason(data, violations)
        if violations or operation_id is None:
            raise ValidationFailed(violations=violations)
        if ReportConflict.objects.filter(proposer=uow.actor, operation_id=operation_id).exists():
            raise InvalidTransition("A proposal for this operation already exists")
        current = inspection.current_assignment
        conflict = ReportConflict.objects.create(
            inspection=inspection,
            operation_id=operation_id,
            proposer=uow.actor,
            application_version_seen=seen,
            local_manifest=manifest,
            local_manifest_sha256=canonical_sha256(manifest),
            safe_local_summary=summary.strip(),
            reason=reason,
            server_snapshot={
                "inspection_version": inspection.version,
                "inspection_status": inspection.status,
                "application_version": inspection.application.version,
                "assignment_version": current.version if current else None,
                "assigned_to_proposer": bool(
                    current and current.officer_id == uow.actor.pk and current.state == "ACTIVE"
                ),
                "has_accepted_report": inspection.current_report_id is not None,
                "sync_state": (
                    SyncOperation.objects.filter(principal=uow.actor, operation_id=operation_id)
                    .values_list("state", flat=True)
                    .first()
                ),
            },
        )
        event = _case_event(
            uow,
            inspection.application,
            "inspection.conflict_recorded.v1",
            {
                "inspection_id": str(inspection.pk),
                "conflict_id": str(conflict.pk),
                "operation_id": str(operation_id),
            },
            EventAudience.INTERNAL,
        )
        return CommandOutcome(
            status=201,
            body=conflict_body(conflict),
            aggregate=None,
            audits=[
                AuditEntry(
                    "inspection",
                    inspection.pk,
                    "inspection.conflict_recorded",
                    {"conflict_id": str(conflict.pk), "operation_id": str(operation_id)},
                )
            ],
            intents=[_intent(event, uow)],
        )


class ResolveConflict(CommandHandler[ReportConflict]):
    """API-052: a supervisor of the case jurisdiction decides; both versions and the reason are
    preserved. PROPOSE_NEW_REPORT / REINSPECTION_REQUIRED point at the existing commands (a new
    attempt through TR-09 or a supervisor-created attempt); DECLINE closes the proposal."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff resolve inspection conflicts")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> ReportConflict | None:
        conflict = (
            ReportConflict.objects.select_for_update(of=("self",))
            .select_related("inspection__application__owner_queue__jurisdiction")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if conflict is None:
            raise ResourceNotFound("Conflict not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        if not snapshot.has_role(
            RoleKey.SUPERVISOR,
            jurisdiction_id=conflict.inspection.application.owner_queue.jurisdiction_id,
        ):
            raise ResourceNotFound("Conflict not found")
        return conflict

    def apply(
        self, uow: UnitOfWork, target: ReportConflict | None
    ) -> CommandOutcome[ReportConflict]:
        if target is None:
            raise ResourceNotFound("Conflict not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "outcome",
            "reason",
            "selected_evidence_ids",
            "replacement_assignment_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        outcome = str(data.get("outcome") or "")
        if outcome not in ConflictOutcome.values:
            violations.append(
                Violation(
                    "/outcome", "invalid", "PROPOSE_NEW_REPORT, REINSPECTION_REQUIRED or DECLINE"
                )
            )
        reason = _reason(data, violations)
        raw_ids = data.get("selected_evidence_ids", [])
        selected: list[str] = []
        if not isinstance(raw_ids, list):
            violations.append(Violation("/selected_evidence_ids", "invalid", "must be a list"))
        else:
            for j, value in enumerate(raw_ids):
                try:
                    selected.append(str(UUID(str(value))))
                except ValueError:
                    violations.append(
                        Violation(f"/selected_evidence_ids/{j}", "invalid", "must be a UUID")
                    )
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state != ConflictState.OPEN:
            raise InvalidTransition("This conflict is already resolved")
        if selected:
            from agni.documents.models import DocumentVersion, ScanState

            clean = set(
                str(pk)
                for pk in DocumentVersion.objects.filter(
                    pk__in=[UUID(x) for x in selected],
                    application=target.inspection.application,
                    scan_state=ScanState.CLEAN,
                ).values_list("pk", flat=True)
            )
            missing = [x for x in selected if x not in clean]
            if missing:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            f"/selected_evidence_ids/{selected.index(x)}",
                            "not_clean_case_evidence",
                            "must be a CLEAN file of this case",
                        )
                        for x in missing
                    ]
                )
        target.state = ConflictState.RESOLVED
        target.outcome = outcome
        target.resolution_reason = reason
        target.selected_evidence_ids = selected
        target.resolved_by = uow.actor
        target.resolved_at = uow.now
        target.save(
            update_fields=[
                "state",
                "outcome",
                "resolution_reason",
                "selected_evidence_ids",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        event = _case_event(
            uow,
            target.inspection.application,
            "inspection.conflict_resolved.v1",
            {"conflict_id": str(target.pk), "outcome": outcome, "reason": reason},
            EventAudience.INTERNAL,
        )
        next_step = {
            ConflictOutcome.PROPOSE_NEW_REPORT: (
                "Schedule a new attempt for a current assignee; the local manifest is "
                "reference only"
            ),
            ConflictOutcome.REINSPECTION_REQUIRED: (
                "Use require-reinspection (TR-09) or schedule the follow-up attempt"
            ),
            ConflictOutcome.DECLINE: (
                "No further action; the device must discard the local proposal"
            ),
        }[ConflictOutcome(outcome)]
        return CommandOutcome(
            status=200,
            body={**conflict_body(target), "next_step": next_step},
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.inspection_id,
                    "inspection.conflict_resolved",
                    {"conflict_id": str(target.pk), "outcome": outcome, "reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow)],
        )
