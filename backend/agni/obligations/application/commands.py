"""Manual escalation and acknowledgement (API-076/077; FR-19). Neither command changes the
obligation's state or the application: they record accountable intervention."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)

from ..models import Escalation, EscalationState, Obligation, ObligationState

_MANUAL_NAMESPACE = UUID("2b8f7f8e-6e0a-4a0c-9f43-8c1f6b7c2a55")


def escalation_body(e: Escalation) -> dict[str, Any]:
    return {
        "escalation_id": str(e.pk),
        "obligation_id": str(e.obligation_id),
        "threshold_action_id": str(e.threshold_action_id) if e.threshold_action_id else None,
        "manual": e.manual_request_id is not None,
        "level": e.level,
        "owner_queue": e.owner_queue.queue_key,
        "state": e.state,
        "reason": e.reason,
        "requested_by": str(e.requested_by_id) if e.requested_by_id else None,
        "acknowledged_by": str(e.acknowledged_by_id) if e.acknowledged_by_id else None,
        "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
        "next_action": e.next_action or None,
        "created_at": e.created_at.isoformat(),
        "version": e.version,
    }


def _supervisor_for_obligation(uow: UnitOfWork, obligation: Obligation) -> None:
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=obligation.owner_queue.jurisdiction_id
    ):
        raise ResourceNotFound("Obligation not found")


class CreateEscalation(CommandHandler[Obligation]):
    """API-076: reasoned manual intervention on an open obligation. The recipients derive from
    the duty roster (supervisors of the owner queue's jurisdiction), never from the request."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff escalate obligations")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Obligation | None:
        obligation = (
            Obligation.objects.select_for_update(of=("self",))
            .select_related("owner_queue__jurisdiction", "application")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if obligation is None:
            raise ResourceNotFound("Obligation not found")
        _supervisor_for_obligation(uow, obligation)
        return obligation

    def apply(self, uow: UnitOfWork, target: Obligation | None) -> CommandOutcome[Obligation]:
        if target is None:
            raise ResourceNotFound("Obligation not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason", "requested_level", "next_action"})
        ]
        reason = data.get("reason")
        if not isinstance(reason, str) or not (10 <= len(reason.strip()) <= 4000):
            violations.append(Violation("/reason", "length", "10 to 4000 characters"))
            reason = ""
        level = data.get("requested_level", 1)
        if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 5):
            violations.append(Violation("/requested_level", "range", "1 to 5"))
            level = 1
        next_action = data.get("next_action")
        if not isinstance(next_action, str) or not (10 <= len(next_action.strip()) <= 1000):
            violations.append(Violation("/next_action", "length", "10 to 1000 characters"))
            next_action = ""
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state not in (ObligationState.ACTIVE, ObligationState.PAUSED):
            raise InvalidTransition("Only an open obligation can be escalated")
        manual_id = uuid5(_MANUAL_NAMESPACE, str(uow.command_id))
        escalation = Escalation.objects.create(
            obligation=target,
            manual_request_id=manual_id,
            level=level,
            owner_queue=target.owner_queue,
            state=EscalationState.OPEN,
            reason=reason.strip(),
            requested_by=uow.actor,
            next_action=next_action.strip(),
        )
        from agni.notifications.application.fanout import notify_manual_escalation

        notify_manual_escalation(escalation, target, uow.actor, now=uow.now)
        return CommandOutcome(
            status=201,
            body={**escalation_body(escalation), "obligation_state": target.state},
            aggregate=target,
            audits=[
                AuditEntry(
                    "obligation",
                    target.pk,
                    "obligation.escalated",
                    {"escalation_id": str(escalation.pk), "level": level, "reason": reason[:200]},
                )
            ],
        )


class AcknowledgeEscalation(CommandHandler[Escalation]):
    """API-077: record who owns the intervention and the next action. The obligation is
    untouched - acknowledged is not resolved and never regulatory completion."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff acknowledge escalations")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Escalation | None:
        escalation = (
            Escalation.objects.select_for_update(of=("self",))
            .select_related("obligation__owner_queue__jurisdiction", "owner_queue")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if escalation is None:
            raise ResourceNotFound("Escalation not found")
        _supervisor_for_obligation(uow, escalation.obligation)
        return escalation

    def apply(self, uow: UnitOfWork, target: Escalation | None) -> CommandOutcome[Escalation]:
        if target is None:
            raise ResourceNotFound("Escalation not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason", "next_action"})
        ]
        reason = data.get("reason")
        if not isinstance(reason, str) or not (10 <= len(reason.strip()) <= 4000):
            violations.append(Violation("/reason", "length", "10 to 4000 characters"))
            reason = ""
        next_action = data.get("next_action", target.next_action)
        if not isinstance(next_action, str) or len(next_action) > 1000:
            violations.append(Violation("/next_action", "length", "at most 1000 characters"))
            next_action = ""
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state != EscalationState.OPEN:
            raise InvalidTransition("Only an open escalation can be acknowledged")
        target.state = EscalationState.ACKNOWLEDGED
        target.acknowledged_by = uow.actor
        target.acknowledged_at = uow.now
        target.next_action = next_action.strip()
        target.save(
            update_fields=[
                "state",
                "acknowledged_by",
                "acknowledged_at",
                "next_action",
                "updated_at",
            ]
        )
        return CommandOutcome(
            status=200,
            body={**escalation_body(target), "obligation_state": target.obligation.state},
            aggregate=target,
            audits=[
                AuditEntry(
                    "escalation",
                    target.pk,
                    "escalation.acknowledged",
                    {"reason": reason[:200], "next_action": next_action[:200]},
                )
            ],
        )
