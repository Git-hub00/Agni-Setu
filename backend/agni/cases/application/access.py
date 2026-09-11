"""Who may edit a draft (FR-04, FR-10): the applicant who owns it, the acting operator, or a
delegate holding an ACTIVE delegation with `draft.edit` from the applicant for the premises or
service. Anything else is indistinguishable from a missing application."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from agni.identity.application.delegations import active_delegations_for
from agni.identity.models import Principal, PrincipalKind

from ..models import Application


def can_edit_draft(actor: Principal, application: Application, at: datetime) -> bool:
    if actor.kind != PrincipalKind.APPLICANT:
        return False
    if application.applicant_id == actor.pk or application.acting_operator_id == actor.pk:
        return True
    for delegation in active_delegations_for(actor, at):
        if delegation.beneficiary_id != application.applicant_id:
            continue
        if "draft.edit" not in delegation.capabilities:
            continue
        if delegation.premises_id and delegation.premises_id == application.premises_id:
            return True
        if delegation.service_id and delegation.service_id == application.service_id:
            return True
    return False


def can_respond_to_notices(actor: Principal, application: Application, at: datetime) -> bool:
    """FR-16: the applicant who owns the case, the acting operator, or a delegate with the
    `notice.respond` capability for the premises or service."""
    if actor.kind != PrincipalKind.APPLICANT:
        return False
    if application.applicant_id == actor.pk or application.acting_operator_id == actor.pk:
        return True
    for delegation in active_delegations_for(actor, at):
        if delegation.beneficiary_id != application.applicant_id:
            continue
        if "notice.respond" not in delegation.capabilities:
            continue
        if delegation.premises_id and delegation.premises_id == application.premises_id:
            return True
        if delegation.service_id and delegation.service_id == application.service_id:
            return True
    return False


def editable_draft_for_actor(
    actor: Principal, application_id: UUID, at: datetime, *, lock: bool = False
) -> Application | None:
    queryset = Application.objects.select_related(
        "service__owner_queue", "premises", "current_draft_revision"
    )
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    application = queryset.filter(pk=application_id).first()
    if application is None or not can_edit_draft(actor, application, at):
        return None
    return application
