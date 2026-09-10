"""Premises delegation commands (FR-10; API-015..017). A delegate proposes for a named
beneficiary (resolved by verified contact, never by free-text claim); only the beneficiary can
confirm; either party can revoke; history stays attributable. Both fences are locked in sorted
order (the kernel locks the actor; the other party is locked here)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime

from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    SeparationOfDuties,
    ValidationFailed,
    Violation,
)
from agni.platform.locks import lock_principal_fences

from ..contacts import normalize_contact
from ..models import ContactIdentity, Delegation, DelegationState, Principal, PrincipalKind

ALLOWED_CAPABILITIES = frozenset({"draft.edit", "draft.submit", "notice.respond", "case.read"})
MAX_DELEGATION = timedelta(days=366)


def _body(d: Delegation) -> dict[str, Any]:
    return {
        "delegation_id": str(d.pk),
        "beneficiary_id": str(d.beneficiary_id),
        "delegate_id": str(d.delegate_id),
        "premises_id": str(d.premises_id) if d.premises_id else None,
        "service_id": str(d.service_id) if d.service_id else None,
        "capabilities": list(d.capabilities),
        "effective_from": d.effective_from.isoformat(),
        "effective_until": d.effective_until.isoformat(),
        "state": d.state,
        "version": d.version,
    }


class ProposeDelegation(CommandHandler[Delegation]):
    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.APPLICANT:
            raise Forbidden("Only applicant accounts can propose delegations")

    def lock_target(self, uow: UnitOfWork) -> Delegation | None:
        return None

    def apply(self, uow: UnitOfWork, target: Delegation | None) -> CommandOutcome[Delegation]:
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(
                set(data)
                - {
                    "beneficiary_contact",
                    "beneficiary_channel",
                    "premises_id",
                    "service_id",
                    "capabilities",
                    "effective_from",
                    "effective_until",
                    "reason",
                }
            )
        ]
        reason = str(data.get("reason", "")).strip()
        if not 10 <= len(reason) <= 4000:
            violations.append(
                Violation("/reason", "length", "explain the delegation in 10-4000 characters")
            )
        caps = data.get("capabilities")
        if not isinstance(caps, list) or not caps or not set(caps) <= ALLOWED_CAPABILITIES:
            violations.append(
                Violation(
                    "/capabilities", "allowlist", f"choose from {sorted(ALLOWED_CAPABILITIES)}"
                )
            )
        eff_from = (
            parse_datetime(str(data.get("effective_from", "")))
            if data.get("effective_from")
            else None
        )
        eff_until = (
            parse_datetime(str(data.get("effective_until", "")))
            if data.get("effective_until")
            else None
        )
        if eff_from is None or eff_from.tzinfo is None:
            violations.append(
                Violation("/effective_from", "format", "must be an ISO 8601 UTC timestamp")
            )
        if eff_until is None or eff_until.tzinfo is None:
            violations.append(Violation("/effective_until", "format", "a finite end is required"))
        elif eff_from is not None and eff_from.tzinfo is not None:
            if eff_until <= eff_from:
                violations.append(
                    Violation("/effective_until", "interval", "must be after effective_from")
                )
            elif eff_until - eff_from > MAX_DELEGATION:
                violations.append(
                    Violation(
                        "/effective_until", "max_duration", "a delegation may last at most one year"
                    )
                )
        if not data.get("premises_id") and not data.get("service_id"):
            violations.append(
                Violation("/premises_id", "scope", "delegation needs a premises or service scope")
            )
        if violations or eff_from is None or eff_until is None or not isinstance(caps, list):
            raise ValidationFailed(violations=violations)
        capabilities = sorted({str(c) for c in caps})

        contact = normalize_contact(
            str(data.get("beneficiary_channel", "EMAIL")).upper(),
            str(data.get("beneficiary_contact", "")),
        )
        identity = (
            ContactIdentity.objects.select_related("principal")
            .filter(
                channel=contact.channel,
                lookup_hmac=contact.lookup_hmac,
                replaced_at__isnull=True,
                verified_at__isnull=False,
            )
            .first()
        )
        # Enumeration-safe: an unknown contact is indistinguishable from an unusable one.
        if (
            identity is None
            or identity.principal.kind != PrincipalKind.APPLICANT
            or identity.principal_id == uow.actor.pk
        ):
            raise ResourceNotFound("No delegable beneficiary matches that verified contact")
        beneficiary = identity.principal
        lock_principal_fences([beneficiary.pk])

        premises = None
        if data.get("premises_id"):
            from agni.cases.models import Premises

            premises = Premises.objects.filter(
                pk=_uuid(data["premises_id"], "/premises_id"), owner=beneficiary
            ).first()
            if premises is None:
                raise ResourceNotFound("Premises not found for that beneficiary")
        service = None
        if data.get("service_id"):
            from agni.policies.models import Service

            service = Service.objects.filter(pk=_uuid(data["service_id"], "/service_id")).first()
            if service is None:
                raise ResourceNotFound("Service not found")

        delegation = Delegation.objects.create(
            beneficiary=beneficiary,
            delegate=uow.actor,
            proposed_by=uow.actor,
            premises=premises,
            service=service,
            capabilities=capabilities,
            effective_from=eff_from,
            effective_until=eff_until,
            reason=reason,
        )
        return CommandOutcome(
            status=201,
            body=_body(delegation),
            aggregate=delegation,
            created=True,
            audits=[
                AuditEntry(
                    "delegation",
                    delegation.pk,
                    "delegation.proposed",
                    {
                        "beneficiary_id": str(beneficiary.pk),
                        "capabilities": delegation.capabilities,
                    },
                ),
            ],
        )


def _uuid(value: Any, pointer: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationFailed(
            violations=[Violation(pointer, "invalid", "must be a UUID")]
        ) from None


class ConfirmDelegation(CommandHandler[Delegation]):
    """Only the beneficiary confirms; the proposer never self-confirms beneficiary authority."""

    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> Delegation | None:
        delegation = (
            Delegation.objects.select_for_update().filter(pk=uow.envelope.target_id).first()
        )
        if delegation is None or uow.actor.pk not in (
            delegation.beneficiary_id,
            delegation.delegate_id,
        ):
            raise ResourceNotFound("Delegation not found")
        lock_principal_fences([delegation.beneficiary_id, delegation.delegate_id])
        return delegation

    def apply(self, uow: UnitOfWork, target: Delegation | None) -> CommandOutcome[Delegation]:
        if target is None:
            raise ResourceNotFound("Delegation not found")
        if uow.actor.pk != target.beneficiary_id or uow.actor.pk == target.proposed_by_id:
            raise SeparationOfDuties(
                "Only the beneficiary can confirm a delegation proposed by someone else"
            )
        if target.state != DelegationState.PROPOSED:
            raise InvalidTransition(f"Delegation is {target.state}")
        if target.effective_until <= uow.now:
            target.state = DelegationState.EXPIRED
            target.save(update_fields=["state", "updated_at"])
            raise InvalidTransition("Delegation interval has already ended")
        target.state = DelegationState.ACTIVE
        target.confirmed_at = uow.now
        target.save(update_fields=["state", "confirmed_at", "updated_at"])
        return CommandOutcome(
            status=200,
            body=_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "delegation",
                    target.pk,
                    "delegation.confirmed",
                    {"delegate_id": str(target.delegate_id)},
                )
            ],
        )


class RevokeDelegation(CommandHandler[Delegation]):
    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> Delegation | None:
        delegation = (
            Delegation.objects.select_for_update().filter(pk=uow.envelope.target_id).first()
        )
        if delegation is None or uow.actor.pk not in (
            delegation.beneficiary_id,
            delegation.delegate_id,
        ):
            raise ResourceNotFound("Delegation not found")
        lock_principal_fences([delegation.beneficiary_id, delegation.delegate_id])
        return delegation

    def apply(self, uow: UnitOfWork, target: Delegation | None) -> CommandOutcome[Delegation]:
        if target is None:
            raise ResourceNotFound("Delegation not found")
        if target.state in (DelegationState.REVOKED, DelegationState.EXPIRED):
            raise InvalidTransition(f"Delegation is already {target.state}")
        reason = str(uow.envelope.payload.get("reason", "")).strip()
        if len(reason) < 5:
            raise ValidationFailed(violations=[Violation("/reason", "min_length", "give a reason")])
        target.state = DelegationState.REVOKED
        target.revoked_at = uow.now
        target.revoked_by = uow.actor
        target.save(update_fields=["state", "revoked_at", "revoked_by", "updated_at"])
        return CommandOutcome(
            status=200,
            body=_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "delegation",
                    target.pk,
                    "delegation.revoked",
                    {"by": str(uow.actor.pk), "reason": reason[:200]},
                )
            ],
        )


def active_delegations_for(delegate: Principal, at: Any) -> list[Delegation]:
    return [
        d
        for d in Delegation.objects.filter(
            delegate=delegate, state=DelegationState.ACTIVE, revoked_at__isnull=True
        )
        if d.effective_from <= at < d.effective_until
    ]
