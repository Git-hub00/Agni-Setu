"""Guarded withdrawal (TR-13, API-030; FR-30) and authorised holds (API-031/032; FR-18;
workflow s.7). A withdrawal is the applicant's own reasoned action from the stages the pinned
profile permits; it disposes of open obligations, attempts and notices explicitly. A hold is a
separate authorised record - not a twelfth case state - that blocks the listed command scope
and pauses only the listed obligations through the B10 pause table."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils.dateparse import parse_datetime

from agni.documents.models import DocumentVersion, ScanState
from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.inspections.application.commands import _case_event, _intent
from agni.inspections.models import Assignment, AssignmentState, Inspection, InspectionStatus
from agni.notices.models import Notice, NoticeState
from agni.obligations.application.clock_service import add_pause, end_pause
from agni.obligations.models import Obligation, ObligationPause, ObligationState
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)
from agni.policies.models import PolicyVersion

from ..domain.states import TRANSITIONS, transition_for
from ..models import Application, CaseHold, EventAudience, HoldKind, HoldState
from .holds import BLOCK_SCOPES, ensure_not_on_hold, hold_body
from .submission import _lock_case_for_staff, _reason, enter_stage, record_event

HOLD_PAUSE_REASON = (
    "AUTHORIZED_ADMINISTRATIVE_HOLD"  # the only pause reason the demo profile permits
)
BACKDATE_LIMIT = timedelta(hours=24)  # earlier starts need a specific authority (not implemented)
_TERMINAL = ("COMPLETED", "REJECTED", "WITHDRAWN")


def withdrawal_stages(application: Application) -> tuple[str, ...]:
    """Stages the pinned profile permits (`withdraw_from`); the transition table for a draft."""
    default = next(
        tuple(s.value for s in sources)
        for _, command, sources, _, _ in TRANSITIONS
        if command == "withdraw"
    )
    if application.policy_version_id is None:
        return default
    policy = PolicyVersion.objects.filter(pk=application.policy_version_id).first()
    listed = (policy.payload if policy else {}).get("withdraw_from")
    if not isinstance(listed, list):
        return default
    return tuple(str(s) for s in listed if str(s) in default)


def owns_case(actor: Any, application: Application) -> bool:
    return actor.kind == PrincipalKind.APPLICANT and actor.pk in (
        application.applicant_id,
        application.acting_operator_id,
    )


# ---- TR-13 ---------------------------------------------------------------------------------------


class WithdrawApplication(CommandHandler[Application]):
    """API-030: the applicant (or acting operator) withdraws from a permitted stage. Terminal:
    obligations are CANCELLED, open attempts CANCELLED with their assignments REVOKED, published
    notices CANCELLED. Nothing is deleted; the timeline records the disposition."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.APPLICANT:
            raise Forbidden("Only the applicant side withdraws an application")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = (
            Application.objects.select_for_update(of=("self",))
            .select_related("owner_queue", "premises", "service", "current_stage_instance")
            .filter(pk=uow.envelope.target_id)
            .filter(Q(applicant=uow.actor) | Q(acting_operator=uow.actor))
            .first()
        )
        if application is None:
            raise ResourceNotFound("Application not found")
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason"})
        ]
        reason = _reason(data, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        transition = transition_for("withdraw", target.status_enum)
        if transition is None or target.status not in withdrawal_stages(target):
            raise InvalidTransition(
                f"Withdrawal is not permitted from {target.status}",
                extensions={"permitted_from": list(withdrawal_stages(target))},
            )
        ensure_not_on_hold(target, scope="transition")
        _, target_state, event_type = transition
        from_status = target.status
        new_version = target.version + 1
        target.status = target_state.value
        target.closed_at = uow.now
        event = record_event(
            uow,
            target,
            event_type,
            {"reason": reason, "from_status": from_status},
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        enter_stage(target, target.status, event, uow.now, target.policy_version_id)
        target.version = new_version
        target.save(
            update_fields=["status", "closed_at", "current_stage_instance", "version", "updated_at"]
        )
        cancelled_obligations = Obligation.objects.filter(
            application=target, state__in=[ObligationState.ACTIVE, ObligationState.PAUSED]
        ).update(state=ObligationState.CANCELLED, satisfied_event=event)
        cancelled_attempts: list[str] = []
        for inspection in Inspection.objects.select_for_update(of=("self",)).filter(
            application=target,
            status__in=[InspectionStatus.REQUESTED, InspectionStatus.SCHEDULED],
        ):
            inspection.status = InspectionStatus.CANCELLED
            inspection.version += 1
            inspection.save(update_fields=["status", "version", "updated_at"])
            Assignment.objects.filter(inspection=inspection, state=AssignmentState.ACTIVE).update(
                state=AssignmentState.REVOKED, ends_at=uow.now
            )
            cancelled_attempts.append(str(inspection.pk))
        cancelled_notices = Notice.objects.filter(
            application=target, state=NoticeState.PUBLISHED
        ).update(state=NoticeState.CANCELLED, closed_at=uow.now)
        record_event(
            uow,
            target,
            "case.disposition.v1",
            {
                "cancelled_obligations": cancelled_obligations,
                "cancelled_attempts": cancelled_attempts,
                "cancelled_notices": cancelled_notices,
            },
            audience=EventAudience.INTERNAL,
            ordinal=1,
            version=new_version,
        )
        return CommandOutcome(
            status=200,
            body={
                "application_id": str(target.pk),
                "public_reference": target.public_reference,
                "draft_reference": target.draft_reference,
                "status": target.status,
                "from_status": from_status,
                "closed_at": uow.now.isoformat(),
                "disposition": {
                    "cancelled_obligations": cancelled_obligations,
                    "cancelled_attempts": cancelled_attempts,
                    "cancelled_notices": cancelled_notices,
                },
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "application.withdrawn",
                    {
                        "from_status": from_status,
                        "reason": reason[:200],
                        "cancelled_attempts": cancelled_attempts,
                    },
                )
            ],
            intents=[_intent(event, uow)],
        )


# ---- holds --------------------------------------------------------------------------------------


def _timestamp(value: Any, pointer: str, violations: list[Violation]) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = parse_datetime(str(value))
    if parsed is None or parsed.tzinfo is None:
        violations.append(Violation(pointer, "format", "must be an ISO 8601 UTC timestamp"))
        return None
    return parsed


class CreateHold(CommandHandler[Application]):
    """API-031: a supervisor of the case jurisdiction records an authorised hold. Only the
    listed ACTIVE obligations are paused (policy-permitted pause reason), only the listed
    command scope is blocked; a COURT_ORDER hold cites its basis document."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff record holds")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return _lock_case_for_staff(uow)

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "kind",
            "reason",
            "basis_document_id",
            "starts_at",
            "requested_end_at",
            "affected_obligation_ids",
            "command_block_scope",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        kind = str(data.get("kind") or "")
        if kind not in HoldKind.values:
            violations.append(Violation("/kind", "invalid", "ADMINISTRATIVE or COURT_ORDER"))
        reason = _reason(data, violations)
        starts_at = _timestamp(data.get("starts_at"), "/starts_at", violations) or uow.now
        requested_end = _timestamp(data.get("requested_end_at"), "/requested_end_at", violations)
        if starts_at > uow.now:
            violations.append(
                Violation("/starts_at", "future", "a hold cannot start in the future")
            )
        elif uow.now - starts_at > BACKDATE_LIMIT:
            violations.append(
                Violation(
                    "/starts_at",
                    "backdated",
                    "a start more than 24 hours ago requires a specific authority (not enabled)",
                )
            )
        if requested_end is not None and requested_end <= starts_at:
            violations.append(Violation("/requested_end_at", "interval", "must be after starts_at"))
        raw_scope = data.get("command_block_scope", [])
        scope: list[str] = []
        if not isinstance(raw_scope, list):
            violations.append(Violation("/command_block_scope", "invalid", "must be a list"))
        else:
            for j, value in enumerate(raw_scope):
                if str(value) not in BLOCK_SCOPES:
                    violations.append(
                        Violation(
                            f"/command_block_scope/{j}", "invalid", "TRANSITIONS or DECISIONS"
                        )
                    )
                elif str(value) not in scope:
                    scope.append(str(value))
        raw_ids = data.get("affected_obligation_ids", [])
        obligation_ids: list[UUID] = []
        if not isinstance(raw_ids, list):
            violations.append(Violation("/affected_obligation_ids", "invalid", "must be a list"))
        else:
            for j, value in enumerate(raw_ids):
                try:
                    obligation_ids.append(UUID(str(value)))
                except ValueError:
                    violations.append(
                        Violation(f"/affected_obligation_ids/{j}", "invalid", "must be a UUID")
                    )
        basis: DocumentVersion | None = None
        basis_raw = data.get("basis_document_id")
        if basis_raw not in (None, ""):
            try:
                basis = DocumentVersion.objects.filter(
                    pk=UUID(str(basis_raw)), application=target, scan_state=ScanState.CLEAN
                ).first()
            except ValueError:
                basis = None
            if basis is None:
                violations.append(
                    Violation(
                        "/basis_document_id", "not_clean_case_evidence", "a CLEAN file of this case"
                    )
                )
        elif kind == HoldKind.COURT_ORDER:
            violations.append(
                Violation("/basis_document_id", "required", "a court-order hold cites its basis")
            )
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status in _TERMINAL:
            raise InvalidTransition("A closed case cannot be put on hold")
        if CaseHold.objects.filter(application=target, state=HoldState.ACTIVE).exists():
            raise InvalidTransition("An active hold already exists for this case")
        obligations = {
            o.pk: o
            for o in Obligation.objects.select_for_update(of=("self",)).filter(
                application=target, pk__in=obligation_ids, state=ObligationState.ACTIVE
            )
        }
        missing = [str(x) for x in obligation_ids if x not in obligations]
        if missing:
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/affected_obligation_ids",
                        "unknown_obligation",
                        f"not ACTIVE obligations of this case: {', '.join(missing)}",
                    )
                ]
            )
        hold = CaseHold.objects.create(
            application=target,
            kind=kind,
            reason=reason,
            basis_document=basis,
            authorized_by=uow.actor,
            starts_at=starts_at,
            requested_end_at=requested_end,
            affected_obligations=[str(x) for x in obligation_ids],
            command_block_scope=scope,
        )
        for obligation in obligations.values():
            add_pause(
                obligation,
                starts_at=starts_at,
                ends_at=requested_end,
                authorized_by=uow.actor,
                reason_code=HOLD_PAUSE_REASON,
                reason=f"{kind} hold {hold.pk}: {reason}",
                now=uow.now,
                hold_id=hold.pk,
            )
        event = _case_event(
            uow,
            target,
            "case.hold_started.v1",
            {
                "hold_id": str(hold.pk),
                "kind": kind,
                "affected_obligation_ids": [str(x) for x in obligation_ids],
                "command_block_scope": scope,
                "starts_at": starts_at.isoformat(),
            },
            EventAudience.INTERNAL,
        )
        return CommandOutcome(
            status=201,
            body=hold_body(hold),
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "case.hold_started",
                    {"hold_id": str(hold.pk), "kind": kind, "scope": scope, "reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow)],
        )


class ReleaseHold(CommandHandler[CaseHold]):
    """API-032: close the hold interval, end its pauses and recompute the clocks. Elapsed case
    age is never erased; the release is an event."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff release holds")

    def lock_target(self, uow: UnitOfWork) -> CaseHold | None:
        hold = (
            CaseHold.objects.select_for_update(of=("self",))
            .select_related("application__owner_queue__jurisdiction")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if hold is None:
            raise ResourceNotFound("Hold not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        if not snapshot.has_role(
            RoleKey.SUPERVISOR, jurisdiction_id=hold.application.owner_queue.jurisdiction_id
        ):
            raise ResourceNotFound("Hold not found")
        return hold

    def apply(self, uow: UnitOfWork, target: CaseHold | None) -> CommandOutcome[CaseHold]:
        if target is None:
            raise ResourceNotFound("Hold not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason"})
        ]
        reason = _reason(data, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state != HoldState.ACTIVE:
            raise InvalidTransition("This hold is already released")
        ended = 0
        for pause in ObligationPause.objects.select_related("obligation").filter(
            hold_id=target.pk, ends_at__isnull=True
        ):
            end_pause(pause, ends_at=uow.now, now=uow.now)
            ended += 1
        target.state = HoldState.RELEASED
        target.ends_at = uow.now
        target.released_by = uow.actor
        target.release_reason = reason
        target.save(
            update_fields=["state", "ends_at", "released_by", "release_reason", "updated_at"]
        )
        application = Application.objects.select_related("owner_queue").get(
            pk=target.application_id
        )
        event = _case_event(
            uow,
            application,
            "case.hold_released.v1",
            {"hold_id": str(target.pk), "ended_pauses": ended, "reason": reason},
            EventAudience.INTERNAL,
        )
        return CommandOutcome(
            status=200,
            body=hold_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    application.pk,
                    "case.hold_released",
                    {"hold_id": str(target.pk), "ended_pauses": ended, "reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow)],
        )
