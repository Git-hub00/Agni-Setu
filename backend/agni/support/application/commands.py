"""Support tickets (FR-30; API-112..116). Requester = the account that opened the ticket;
support scope = operations administrators (global) and supervisors of the owner queue's
jurisdiction. INTERNAL notes never reach the requester. No command here touches a case,
a certificate, an authority grant or a decision."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Q, QuerySet

from agni.cases.models import Application
from agni.cases.selectors import visible_applications
from agni.documents.models import DocumentVersion, ScanState
from agni.identity.authz import AuthzSnapshot, load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ServiceDisabled,
    ValidationFailed,
    Violation,
)
from agni.routing.models import DutyQueue

from ..models import (
    MessageAudience,
    MessageKind,
    SupportMessage,
    SupportTicket,
    TicketCategory,
    TicketState,
)

STAFF_TRANSITIONS: dict[str, set[str]] = {
    TicketState.OPEN: {TicketState.IN_PROGRESS, TicketState.RESOLVED},
    TicketState.IN_PROGRESS: {TicketState.WAITING_FOR_REQUESTER, TicketState.RESOLVED},
    TicketState.WAITING_FOR_REQUESTER: {TicketState.IN_PROGRESS, TicketState.RESOLVED},
    TicketState.RESOLVED: {TicketState.CLOSED, TicketState.IN_PROGRESS},
    TicketState.CLOSED: {TicketState.IN_PROGRESS},
}
REQUESTER_REOPEN = {TicketState.RESOLVED, TicketState.CLOSED}


# ---- scope ---------------------------------------------------------------------------------------


def support_scope(snapshot: AuthzSnapshot, queue: DutyQueue) -> bool:
    if snapshot.kind != PrincipalKind.STAFF or not snapshot.active:
        return False
    return snapshot.has_role(RoleKey.ADMIN) or snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=queue.jurisdiction_id
    )


def visible_tickets(snapshot: AuthzSnapshot) -> QuerySet[SupportTicket]:
    queryset = SupportTicket.objects.select_related("owner_queue__jurisdiction", "application")
    if not snapshot.active:
        return queryset.none()
    if snapshot.kind == PrincipalKind.APPLICANT:
        return queryset.filter(requester_id=snapshot.principal_id)
    if snapshot.has_role(RoleKey.ADMIN):
        return queryset
    jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
    scope = Q(requester_id=snapshot.principal_id)
    if jurisdictions:
        scope |= Q(owner_queue__jurisdiction_id__in=jurisdictions)
    return queryset.filter(scope)


def _is_requester(actor: Principal, ticket: SupportTicket) -> bool:
    return ticket.requester_id == actor.pk


# ---- projections -------------------------------------------------------------------------------


def message_body(message: SupportMessage) -> dict[str, Any]:
    return {
        "message_id": str(message.pk),
        "kind": message.kind,
        "audience": message.audience,
        "sender_id": str(message.sender_id),
        "body": message.body,
        "document_version_ids": list(message.document_version_ids),
        "state_after": message.state_after or None,
        "created_at": message.created_at.isoformat(),
    }


def ticket_body(ticket: SupportTicket, *, staff: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ticket_id": str(ticket.pk),
        "category": ticket.category,
        "subject": ticket.subject,
        "description": ticket.description,
        "state": ticket.state,
        "priority": ticket.priority,
        "application_id": str(ticket.application_id) if ticket.application_id else None,
        "public_reference": ticket.application.public_reference if ticket.application else None,
        "owner_queue": ticket.owner_queue.queue_key,
        "requester_id": str(ticket.requester_id),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "version": ticket.version,
        "etag": ticket.etag,
        "notice": (
            "Support tickets are not an emergency channel, a regulatory notice or a legal "
            "appeal; they cannot change a case outcome."
        ),
    }
    if staff:
        body["owner_queue_id"] = str(ticket.owner_queue_id)
    return body


def messages_for(ticket: SupportTicket, *, staff: bool) -> list[dict[str, Any]]:
    queryset = ticket.messages.order_by("created_at")
    if not staff:
        queryset = queryset.filter(audience=MessageAudience.REQUESTER)
    return [message_body(m) for m in queryset]


# ---- helpers ----------------------------------------------------------------------------------


def _text(data: dict[str, Any], key: str, violations: list[Violation], lo: int, hi: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not (lo <= len(value.strip()) <= hi):
        violations.append(Violation(f"/{key}", "length", f"{lo} to {hi} characters"))
        return ""
    return value.strip()


def _attachments(
    uow: UnitOfWork,
    snapshot: AuthzSnapshot,
    raw: Any,
    application: Application | None,
    violations: list[Violation],
) -> list[str]:
    """Accepted (CLEAN) files the sender may cite: their own uploads, files of a case they can
    read, or support attachments of this ticket's scope."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(Violation("/document_version_ids", "invalid", "must be a list"))
        return []
    ids: list[UUID] = []
    for j, value in enumerate(raw):
        try:
            ids.append(UUID(str(value)))
        except ValueError:
            violations.append(Violation(f"/document_version_ids/{j}", "invalid", "must be a UUID"))
    if violations or not ids:
        return [str(x) for x in ids]
    scope = Q(uploaded_by=uow.actor)
    scope |= Q(application__in=visible_applications(snapshot, uow.now))
    if application is not None:
        scope |= Q(application=application)
    clean = set(
        DocumentVersion.objects.filter(pk__in=ids, scan_state=ScanState.CLEAN)
        .filter(scope)
        .values_list("pk", flat=True)
    )
    for j, value in enumerate(ids):
        if value not in clean:
            violations.append(
                Violation(
                    f"/document_version_ids/{j}",
                    "not_accepted_file",
                    "must be a CLEAN file you may cite",
                )
            )
    return [str(x) for x in ids]


def _default_queue() -> DutyQueue:
    queue = (
        DutyQueue.objects.select_related("jurisdiction")
        .filter(queue_key=settings.SUPPORT_DEFAULT_QUEUE_KEY, active=True)
        .first()
    )
    if queue is None:
        raise ServiceDisabled("The support desk queue is not configured for this deployment")
    return queue


def _lock_visible(uow: UnitOfWork) -> SupportTicket:
    snapshot = load_snapshot(uow.actor, uow.now)
    ticket = (
        visible_tickets(snapshot)
        .select_for_update(of=("self",))
        .filter(pk=uow.envelope.target_id)
        .first()
    )
    if ticket is None:
        raise ResourceNotFound("Ticket not found")
    return ticket


# ---- commands ---------------------------------------------------------------------------------


class CreateTicket(CommandHandler[SupportTicket]):
    """API-113: scoped ticket with an optional readable case link; the first message is the
    description. Owner queue = the case's queue or the configured support desk."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only signed-in accounts open tickets")

    def lock_target(self, uow: UnitOfWork) -> SupportTicket | None:
        return None

    def apply(self, uow: UnitOfWork, target: SupportTicket | None) -> CommandOutcome[SupportTicket]:
        data = dict(uow.envelope.payload)
        allowed = {"category", "subject", "description", "application_id", "document_version_ids"}
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        category = str(data.get("category") or "")
        if category not in TicketCategory.values:
            violations.append(
                Violation(
                    "/category", "invalid", "HOW_TO, TECHNICAL, ACCESS, DATA_CORRECTION or OTHER"
                )
            )
        subject = _text(data, "subject", violations, 5, 160)
        description = _text(data, "description", violations, 10, 4000)
        snapshot = load_snapshot(uow.actor, uow.now)
        application: Application | None = None
        raw_app = data.get("application_id")
        if raw_app not in (None, ""):
            try:
                application = (
                    visible_applications(snapshot, uow.now)
                    .select_related("owner_queue__jurisdiction")
                    .filter(pk=UUID(str(raw_app)))
                    .first()
                )
            except ValueError:
                application = None
            if application is None:
                violations.append(
                    Violation("/application_id", "out_of_scope", "not a case you can read")
                )
        attachments = _attachments(
            uow, snapshot, data.get("document_version_ids"), application, violations
        )
        if violations:
            raise ValidationFailed(violations=violations)
        queue = application.owner_queue if application is not None else _default_queue()
        ticket = SupportTicket.objects.create(
            requester=uow.actor,
            application=application,
            category=category,
            subject=subject,
            description=description,
            owner_queue=queue,
        )
        SupportMessage.objects.create(
            ticket=ticket,
            sender=uow.actor,
            audience=MessageAudience.REQUESTER,
            kind=MessageKind.MESSAGE,
            body=description,
            document_version_ids=attachments,
            state_after=TicketState.OPEN,
        )
        staff = uow.actor.kind == PrincipalKind.STAFF
        return CommandOutcome(
            status=201,
            body={
                **ticket_body(ticket, staff=staff),
                "messages": messages_for(ticket, staff=staff),
            },
            aggregate=ticket,
            created=True,
            audits=[
                AuditEntry(
                    "ticket",
                    ticket.pk,
                    "ticket.created",
                    {
                        "category": category,
                        "application_id": str(application.pk) if application else None,
                        "owner_queue": queue.queue_key,
                        "attachments": len(attachments),
                    },
                )
            ],
        )


class AddTicketMessage(CommandHandler[SupportTicket]):
    """API-115: attributable message. Requesters write to REQUESTER only; support staff may add
    INTERNAL notes. A requester's reply resumes a WAITING_FOR_REQUESTER ticket; a staff reply
    moves an OPEN ticket to IN_PROGRESS. Closed tickets need a reopen first."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only signed-in accounts reply to tickets")

    def lock_target(self, uow: UnitOfWork) -> SupportTicket | None:
        return _lock_visible(uow)

    def apply(self, uow: UnitOfWork, target: SupportTicket | None) -> CommandOutcome[SupportTicket]:
        if target is None:
            raise ResourceNotFound("Ticket not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        requester = _is_requester(uow.actor, target)
        staff_scope = support_scope(snapshot, target.owner_queue)
        if not requester and not staff_scope:
            raise ResourceNotFound("Ticket not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"body", "audience", "document_version_ids"})
        ]
        body = _text(data, "body", violations, 1, 4000)
        audience = str(data.get("audience") or MessageAudience.REQUESTER)
        if audience not in MessageAudience.values:
            violations.append(Violation("/audience", "invalid", "REQUESTER or INTERNAL"))
        if audience == MessageAudience.INTERNAL and not staff_scope:
            raise Forbidden("Internal notes are staff-only")
        attachments = _attachments(
            uow, snapshot, data.get("document_version_ids"), target.application, violations
        )
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state == TicketState.CLOSED:
            raise InvalidTransition("This ticket is closed; reopen it before replying")
        new_state = str(target.state)
        if audience == MessageAudience.REQUESTER:
            if staff_scope and not requester and target.state == TicketState.OPEN:
                new_state = TicketState.IN_PROGRESS
            if requester and target.state == TicketState.WAITING_FOR_REQUESTER:
                new_state = TicketState.IN_PROGRESS
        message = SupportMessage.objects.create(
            ticket=target,
            sender=uow.actor,
            audience=audience,
            kind=MessageKind.MESSAGE,
            body=body,
            document_version_ids=attachments,
            state_after=new_state,
        )
        if new_state != target.state:
            target.state = new_state
            target.save(update_fields=["state", "updated_at"])
        return CommandOutcome(
            status=201,
            body={**message_body(message), "ticket_state": target.state},
            aggregate=target,
            audits=[
                AuditEntry(
                    "ticket",
                    target.pk,
                    "ticket.message_added",
                    {
                        "message_id": str(message.pk),
                        "audience": audience,
                        "attachments": len(attachments),
                        "state_after": new_state,
                    },
                )
            ],
        )


class ChangeTicketStatus(CommandHandler[SupportTicket]):
    """API-116: guarded support lifecycle. Staff move OPEN -> IN_PROGRESS -> WAITING_FOR_REQUESTER
    -> RESOLVED -> CLOSED (and reopen); a requester may only reopen a RESOLVED/CLOSED ticket.
    Every change is a recorded STATUS entry; nothing touches the regulatory case."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind not in (PrincipalKind.APPLICANT, PrincipalKind.STAFF):
            raise Forbidden("Only signed-in accounts change ticket status")

    def lock_target(self, uow: UnitOfWork) -> SupportTicket | None:
        return _lock_visible(uow)

    def apply(self, uow: UnitOfWork, target: SupportTicket | None) -> CommandOutcome[SupportTicket]:
        if target is None:
            raise ResourceNotFound("Ticket not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        requester = _is_requester(uow.actor, target)
        staff_scope = support_scope(snapshot, target.owner_queue)
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"state", "reason", "next_action"})
        ]
        state = str(data.get("state") or "")
        if state not in TicketState.values:
            violations.append(Violation("/state", "invalid", "a support state"))
        reason = _text(data, "reason", violations, 10, 1000)
        next_action = ""
        if data.get("next_action") not in (None, ""):
            next_action = _text(data, "next_action", violations, 1, 1000)
        if violations:
            raise ValidationFailed(violations=violations)
        current = str(target.state)
        if staff_scope:
            if state not in STAFF_TRANSITIONS.get(current, set()):
                raise InvalidTransition(f"{current} -> {state} is not a support transition")
        elif requester:
            if current not in REQUESTER_REOPEN or state != TicketState.IN_PROGRESS:
                raise Forbidden("Requesters may only reopen a resolved or closed ticket")
        else:
            raise ResourceNotFound("Ticket not found")
        target.state = state
        if state == TicketState.RESOLVED:
            target.resolved_at = uow.now
        if state == TicketState.CLOSED:
            target.closed_at = uow.now
        if state == TicketState.IN_PROGRESS and current in REQUESTER_REOPEN:
            target.resolved_at = None
            target.closed_at = None
        target.save(update_fields=["state", "resolved_at", "closed_at", "updated_at"])
        SupportMessage.objects.create(
            ticket=target,
            sender=uow.actor,
            audience=MessageAudience.REQUESTER,
            kind=MessageKind.STATUS,
            body=f"{current} -> {state}: {reason}"
            + (f" Next: {next_action}" if next_action else ""),
            state_after=state,
        )
        staff = uow.actor.kind == PrincipalKind.STAFF
        return CommandOutcome(
            status=200,
            body=ticket_body(target, staff=staff),
            aggregate=target,
            audits=[
                AuditEntry(
                    "ticket",
                    target.pk,
                    "ticket.status_changed",
                    {"from": current, "to": state, "reason": reason[:200]},
                )
            ],
        )
