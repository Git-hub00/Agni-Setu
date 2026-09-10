"""Identity governance commands on the kernel (FR-02, security s.6):

- ProvisionStaff: bind an approved access request to an OIDC issuer+subject, creating the
  staff principal and its role binding. Requires `staff.provision` capability; never self.
- ApproveAuthorityGrant: an independent grant authority approves a PROPOSED grant. Approver
  must differ from preparer and subject (separation of duties); locks the subject's fence and
  bumps the subject's epoch.
- RevokeAuthorityGrant / RevokeRoleBinding: revoke under the subject fence; epoch bump.
- DisablePrincipal: deactivate; epoch bump revokes every session on its next request.

All commands lock fences in sorted principal order (actor first via the kernel, then the
subject) and write audit rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    InvalidTransition,
    ResourceNotFound,
    SeparationOfDuties,
    ValidationFailed,
    Violation,
)
from agni.platform.locks import lock_principal_fences

from ..authz import load_snapshot, require_capability, require_role
from ..domain.roles import Capability, RoleKey
from ..models import (
    AccessRequest,
    AccessRequestStatus,
    AuthorityGrant,
    GrantState,
    Principal,
    PrincipalKind,
    RoleBinding,
)


def _uuid(value: Any, pointer: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationFailed(
            violations=[Violation(pointer, "invalid", "must be a UUID")]
        ) from None


class ProvisionStaff(CommandHandler[Principal]):
    """Target: the approved AccessRequest id (payload.access_request_id). Creates the staff
    principal bound to the request's issuer/subject and a role binding for the requested role."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_role(snapshot, RoleKey.ADMIN)
        require_capability(snapshot, Capability.STAFF_PROVISION)

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        return None

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        request_id = _uuid(uow.envelope.payload.get("access_request_id"), "/access_request_id")
        access_request = AccessRequest.objects.select_for_update().filter(pk=request_id).first()
        if access_request is None:
            raise ResourceNotFound("Access request not found")
        if (
            access_request.status != AccessRequestStatus.APPROVED
            or access_request.consumed_at is not None
        ):
            raise InvalidTransition(
                "Only an approved, unconsumed access request can be provisioned"
            )
        if (
            access_request.approver_id == uow.actor.pk
            or access_request.requester_id == uow.actor.pk
        ):
            raise SeparationOfDuties("Requester or approver cannot also provision")
        if not access_request.intended_issuer or not access_request.intended_subject:
            raise ValidationFailed(
                violations=[
                    Violation("/access_request_id", "incomplete", "request lacks an OIDC identity")
                ]
            )
        if access_request.requested_role not in RoleKey.__members__:
            raise ValidationFailed(
                violations=[Violation("/access_request_id", "invalid_role", "unknown role")]
            )
        approver = access_request.approver
        if approver is None:
            raise InvalidTransition("Approved request has no recorded approver")

        try:
            with transaction.atomic():
                principal = Principal.objects.create_principal(
                    kind=PrincipalKind.STAFF,
                    display_name=access_request.intended_display_name
                    or access_request.intended_subject,
                    external_issuer=access_request.intended_issuer,
                    external_subject=access_request.intended_subject,
                )
        except IntegrityError:
            raise InvalidTransition("This staff identity is already provisioned") from None

        binding = RoleBinding.objects.create(
            principal=principal,
            role_key=access_request.requested_role,
            jurisdiction=access_request.jurisdiction,
            service=access_request.service,
            effective_from=uow.now,
            approved_request=access_request,
            approved_by=approver,
        )
        access_request.consumed_at = uow.now
        access_request.beneficiary = principal
        access_request.version += 1
        access_request.save(update_fields=["consumed_at", "beneficiary", "version", "updated_at"])

        return CommandOutcome(
            status=201,
            body={
                "principal_id": str(principal.pk),
                "display_name": principal.display_name,
                "role_key": binding.role_key,
                "workspaces": [w.value for w in load_snapshot(principal, uow.now).workspaces],
            },
            aggregate=principal,
            created=True,
            audits=[
                AuditEntry(
                    "principal",
                    principal.pk,
                    "staff.provisioned",
                    {
                        "access_request_id": str(access_request.pk),
                        "role_key": binding.role_key,
                        "issuer": access_request.intended_issuer,
                    },
                )
            ],
        )


class ApproveAuthorityGrant(CommandHandler[AuthorityGrant]):
    """Target: the PROPOSED grant. Requires the `grant.approve` capability; approver must not be
    the preparer or the subject."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_capability(snapshot, Capability.GRANT_APPROVE)

    def lock_target(self, uow: UnitOfWork) -> AuthorityGrant | None:
        grant = AuthorityGrant.objects.select_for_update().filter(pk=uow.envelope.target_id).first()
        if grant is None:
            raise ResourceNotFound("Grant not found")
        # Subject fence after the actor fence (kernel) - sorted ordering is preserved because
        # the kernel already holds the actor; a second principal is locked here.
        lock_principal_fences([grant.subject_id])
        return grant

    def apply(
        self, uow: UnitOfWork, target: AuthorityGrant | None
    ) -> CommandOutcome[AuthorityGrant]:
        if target is None:
            raise ResourceNotFound("Grant not found")
        if target.state != GrantState.PROPOSED:
            raise InvalidTransition(f"Grant is {target.state}, not PROPOSED")
        if uow.actor.pk in (target.preparer_id, target.subject_id):
            raise SeparationOfDuties("Preparer or beneficiary cannot approve this grant")
        basis = str(uow.envelope.payload.get("approval_basis", "")).strip()
        if len(basis) < 10:
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/approval_basis", "min_length", "state the approval basis (10+ characters)"
                    )
                ]
            )
        target.state = GrantState.APPROVED
        target.approver = uow.actor
        target.approval_basis = basis
        target.approved_at = uow.now
        target.save(
            update_fields=["state", "approver", "approval_basis", "approved_at", "updated_at"]
        )
        _bump_subject_epoch(target.subject_id)
        return CommandOutcome(
            status=200,
            body={
                "grant_id": str(target.pk),
                "state": target.state,
                "capability": target.capability,
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "authority_grant",
                    target.pk,
                    "grant.approved",
                    {
                        "subject_id": str(target.subject_id),
                        "capability": target.capability,
                        "scope": target.scope_kind,
                    },
                    authority_grant_id=target.pk,
                )
            ],
        )


class RevokeAuthorityGrant(CommandHandler[AuthorityGrant]):
    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_capability(snapshot, Capability.GRANT_APPROVE)

    def lock_target(self, uow: UnitOfWork) -> AuthorityGrant | None:
        grant = AuthorityGrant.objects.select_for_update().filter(pk=uow.envelope.target_id).first()
        if grant is None:
            raise ResourceNotFound("Grant not found")
        lock_principal_fences([grant.subject_id])
        return grant

    def apply(
        self, uow: UnitOfWork, target: AuthorityGrant | None
    ) -> CommandOutcome[AuthorityGrant]:
        if target is None:
            raise ResourceNotFound("Grant not found")
        if target.state not in (GrantState.PROPOSED, GrantState.APPROVED):
            raise InvalidTransition(f"Grant is already {target.state}")
        reason = str(uow.envelope.payload.get("reason", "")).strip()
        if len(reason) < 5:
            raise ValidationFailed(violations=[Violation("/reason", "min_length", "give a reason")])
        target.state = GrantState.REVOKED
        target.revoked_at = uow.now
        target.save(update_fields=["state", "revoked_at", "updated_at"])
        _bump_subject_epoch(target.subject_id)
        return CommandOutcome(
            status=200,
            body={"grant_id": str(target.pk), "state": target.state},
            aggregate=target,
            audits=[
                AuditEntry(
                    "authority_grant",
                    target.pk,
                    "grant.revoked",
                    {"subject_id": str(target.subject_id), "reason": reason[:200]},
                    authority_grant_id=target.pk,
                )
            ],
        )


class DisablePrincipal(CommandHandler[Principal]):
    """Target: the principal to disable. Admin role required; cannot disable self. The epoch
    bump makes every existing session fail its next recheck (FR-02 recovery)."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_role(snapshot, RoleKey.ADMIN)
        if uow.envelope.target_id == uow.actor.pk:
            raise SeparationOfDuties("You cannot disable your own account")

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        lock_principal_fences([uow.envelope.target_id])
        principal = Principal.objects.filter(pk=uow.envelope.target_id).first()
        if principal is None:
            raise ResourceNotFound("Principal not found")
        return principal

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        if target is None:
            raise ResourceNotFound("Principal not found")
        if not target.is_active:
            raise InvalidTransition("Account is already disabled")
        reason = str(uow.envelope.payload.get("reason", "")).strip()
        if len(reason) < 5:
            raise ValidationFailed(violations=[Violation("/reason", "min_length", "give a reason")])
        target.disable(uow.now)
        target.save(update_fields=["is_active", "disabled_at", "authz_epoch", "updated_at"])
        RoleBinding.objects.filter(principal=target, revoked_at__isnull=True).update(
            revoked_at=uow.now
        )
        return CommandOutcome(
            status=200,
            body={
                "principal_id": str(target.pk),
                "active": False,
                "authz_epoch": target.authz_epoch,
            },
            aggregate=target,
            audits=[
                AuditEntry("principal", target.pk, "principal.disabled", {"reason": reason[:200]})
            ],
        )


def _bump_subject_epoch(principal_id: UUID) -> None:
    from django.db.models import F

    Principal.objects.filter(pk=principal_id).update(authz_epoch=F("authz_epoch") + 1)
