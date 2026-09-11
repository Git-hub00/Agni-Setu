"""First case commands on the kernel (FR-03 premises master, FR-04 draft creation; API-011,
API-021). They prove the kernel end to end with real aggregates: scoped authorization,
validation with JSON-pointer violations, append-only events, stage instances and audit.

Client-supplied actors, roles, states and dates are never trusted: the actor comes from the
locked principal in the unit of work, state is always DRAFT, times come from the clock.
"""

from __future__ import annotations

import secrets
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from agni.identity.models import PrincipalKind
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    ResourceNotFound,
    ServiceDisabled,
    ValidationFailed,
    Violation,
)
from agni.policies.models import Service

from ..domain.states import ApplicationStatus, allowed_transitions
from ..models import Application, CaseEvent, EventAudience, Premises, StageInstance

_ALNUM = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L


def _draft_reference(year: int) -> str:
    return f"DR-{year}-{''.join(secrets.choice(_ALNUM) for _ in range(6))}"


def _require_applicant(uow: UnitOfWork) -> None:
    if uow.actor.kind != PrincipalKind.APPLICANT:
        raise Forbidden("Only applicant accounts can manage premises and drafts")


def _decimal(
    value: Any, pointer: str, violations: list[Violation], *, max_digits: int, places: int
) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        violations.append(Violation(pointer, "invalid", "must be a decimal number as a string"))
        return None
    if not parsed.is_finite():
        violations.append(Violation(pointer, "invalid", "must be a finite decimal number"))
        return None
    if parsed < 0:
        violations.append(Violation(pointer, "min_value", "must not be negative"))
        return None
    exponent = parsed.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) else 0
    if len(parsed.as_tuple().digits) > max_digits or scale > places:
        violations.append(
            Violation(
                pointer, "precision", f"at most {max_digits} digits and {places} decimal places"
            )
        )
        return None
    return parsed


def _text(
    payload: dict[str, Any],
    key: str,
    violations: list[Violation],
    *,
    max_length: int,
    required: bool = True,
) -> str:
    value = payload.get(key)
    if value is None or value == "":
        if required:
            violations.append(Violation(f"/{key}", "required", "is required"))
        return ""
    if not isinstance(value, str):
        violations.append(Violation(f"/{key}", "invalid", "must be a string"))
        return ""
    if len(value) > max_length:
        violations.append(Violation(f"/{key}", "max_length", f"at most {max_length} characters"))
    return value.strip()


class RegisterPremises(CommandHandler[Premises]):
    """API-011: create a reusable premises master owned by the acting applicant."""

    ALLOWED_FIELDS = frozenset(
        {
            "display_name",
            "address_line1",
            "address_line2",
            "locality",
            "ward_key",
            "postal_code",
            "category_key",
            "area_sqm",
            "height_m",
            "floor_count",
            "occupancy_count",
        }
    )

    def authorize(self, uow: UnitOfWork) -> None:
        _require_applicant(uow)

    def lock_target(self, uow: UnitOfWork) -> Premises | None:
        return None

    def apply(self, uow: UnitOfWork, target: Premises | None) -> CommandOutcome[Premises]:
        payload = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{key}", "unknown_field", "unknown field")
            for key in sorted(set(payload) - self.ALLOWED_FIELDS)
        ]
        display_name = _text(payload, "display_name", violations, max_length=160)
        address_line1 = _text(payload, "address_line1", violations, max_length=200)
        address_line2 = _text(payload, "address_line2", violations, max_length=200, required=False)
        locality = _text(payload, "locality", violations, max_length=100)
        ward_key = _text(payload, "ward_key", violations, max_length=40)
        postal_code = _text(payload, "postal_code", violations, max_length=6)
        if postal_code and (len(postal_code) != 6 or not postal_code.isdigit()):
            violations.append(Violation("/postal_code", "format", "must be a 6-digit postal code"))
        category_key = _text(payload, "category_key", violations, max_length=40)
        area = _decimal(payload.get("area_sqm"), "/area_sqm", violations, max_digits=12, places=2)
        height = _decimal(payload.get("height_m"), "/height_m", violations, max_digits=7, places=2)
        floors = payload.get("floor_count")
        if not isinstance(floors, int) or isinstance(floors, bool) or floors < 1:
            violations.append(
                Violation("/floor_count", "min_value", "must be an integer of at least 1")
            )
        occupancy = payload.get("occupancy_count")
        if occupancy is not None and (
            not isinstance(occupancy, int) or isinstance(occupancy, bool) or occupancy < 0
        ):
            violations.append(
                Violation("/occupancy_count", "min_value", "must be a non-negative integer")
            )
        if violations or area is None or height is None or not isinstance(floors, int):
            raise ValidationFailed(violations=violations)

        premises = Premises.objects.create(
            owner=uow.actor,
            display_name=display_name,
            address_line1=address_line1,
            address_line2=address_line2,
            locality=locality,
            ward_key=ward_key,
            postal_code=postal_code,
            category_key=category_key,
            area_sqm=area,
            height_m=height,
            floor_count=floors,
            occupancy_count=occupancy,
        )
        return CommandOutcome(
            status=201,
            body={
                "premises_id": str(premises.id),
                "display_name": premises.display_name,
                "version": premises.version,
            },
            aggregate=premises,
            created=True,
            audits=[
                AuditEntry(
                    "premises",
                    premises.id,
                    "premises.registered",
                    {
                        "display_name": display_name,
                        "ward_key": ward_key,
                        "category_key": category_key,
                    },
                )
            ],
        )


class UpdatePremises(CommandHandler[Premises]):
    """API-013: new master version of the owner's premises; never touches submitted snapshots."""

    EDITABLE = frozenset(RegisterPremises.ALLOWED_FIELDS)

    def authorize(self, uow: UnitOfWork) -> None:
        _require_applicant(uow)

    def lock_target(self, uow: UnitOfWork) -> Premises | None:
        premises = (
            Premises.objects.select_for_update()
            .filter(pk=uow.envelope.target_id, owner=uow.actor)
            .first()
        )
        if premises is None:
            raise ResourceNotFound("Premises not found")
        return premises

    def apply(self, uow: UnitOfWork, target: Premises | None) -> CommandOutcome[Premises]:
        if target is None:
            raise ResourceNotFound("Premises not found")
        payload = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{key}", "unknown_field", "not an editable field")
            for key in sorted(set(payload) - self.EDITABLE)
        ]
        if not payload:
            violations.append(Violation("/", "empty", "at least one editable field is required"))
            raise ValidationFailed(violations=violations)
        merged: dict[str, Any] = {
            "display_name": target.display_name,
            "address_line1": target.address_line1,
            "address_line2": target.address_line2,
            "locality": target.locality,
            "ward_key": target.ward_key,
            "postal_code": target.postal_code,
            "category_key": target.category_key,
            "area_sqm": str(target.area_sqm),
            "height_m": str(target.height_m),
            "floor_count": target.floor_count,
            "occupancy_count": target.occupancy_count,
        }
        merged.update({k: v for k, v in payload.items() if k in self.EDITABLE})
        try:
            validated = validate_premises_fields(merged)
        except ValidationFailed as exc:
            # Report unknown fields and field errors together (one round trip for the client).
            raise ValidationFailed(violations=[*violations, *exc.violations]) from None
        if violations:
            raise ValidationFailed(violations=violations)
        changed = sorted(
            k
            for k in payload
            if merged[k] != getattr(target, k, None) or k in ("area_sqm", "height_m")
        )
        for key, value in validated.items():
            setattr(target, key, value)
        target.save(update_fields=[*validated.keys(), "updated_at"])
        return CommandOutcome(
            status=200,
            body={"premises_id": str(target.id), "display_name": target.display_name},
            aggregate=target,
            audits=[
                AuditEntry("premises", target.id, "premises.updated", {"changed_fields": changed})
            ],
        )


def validate_premises_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Shared field validation for register/update (DTO catalogue `PremisesCreate`)."""
    violations: list[Violation] = []
    display_name = _text(payload, "display_name", violations, max_length=160)
    if display_name and len(display_name) < 2:
        violations.append(Violation("/display_name", "min_length", "at least 2 characters"))
    address_line1 = _text(payload, "address_line1", violations, max_length=200)
    if address_line1 and len(address_line1) < 5:
        violations.append(Violation("/address_line1", "min_length", "at least 5 characters"))
    address_line2 = _text(payload, "address_line2", violations, max_length=200, required=False)
    locality = _text(payload, "locality", violations, max_length=100)
    if locality and len(locality) < 2:
        violations.append(Violation("/locality", "min_length", "at least 2 characters"))
    ward_key = _text(payload, "ward_key", violations, max_length=40)
    postal_code = _text(payload, "postal_code", violations, max_length=6)
    if postal_code and (len(postal_code) != 6 or not postal_code.isdigit()):
        violations.append(Violation("/postal_code", "format", "must be a 6-digit postal code"))
    category_key = _text(payload, "category_key", violations, max_length=40)
    area = _decimal(payload.get("area_sqm"), "/area_sqm", violations, max_digits=12, places=2)
    if area is not None and area <= 0:
        violations.append(
            Violation("/area_sqm", "min_value", "enter an area greater than zero in square metres")
        )
    height = _decimal(payload.get("height_m"), "/height_m", violations, max_digits=7, places=2)
    floors = payload.get("floor_count")
    if not isinstance(floors, int) or isinstance(floors, bool) or not 1 <= floors <= 300:
        violations.append(
            Violation("/floor_count", "range", "must be an integer between 1 and 300")
        )
    occupancy = payload.get("occupancy_count")
    if occupancy is not None and (
        not isinstance(occupancy, int)
        or isinstance(occupancy, bool)
        or not 0 <= occupancy <= 1_000_000
    ):
        violations.append(
            Violation("/occupancy_count", "range", "must be an integer between 0 and 1000000")
        )
    if violations or area is None or height is None or not isinstance(floors, int):
        raise ValidationFailed(violations=violations)
    return {
        "display_name": display_name,
        "address_line1": address_line1,
        "address_line2": address_line2,
        "locality": locality,
        "ward_key": ward_key,
        "postal_code": postal_code,
        "category_key": category_key,
        "area_sqm": area,
        "height_m": height,
        "floor_count": floors,
        "occupancy_count": occupancy,
    }


class CreateDraftApplication(CommandHandler[Application]):
    """API-021 / FR-04: create a DRAFT for one of the applicant's own premises under an active
    service. No receipt, no case target, no routing yet; the draft is not a received case."""

    def authorize(self, uow: UnitOfWork) -> None:
        _require_applicant(uow)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return None

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        payload = dict(uow.envelope.payload)
        allowed = {
            "premises_id",
            "service_key",
            "service_id",
            "application_type",
            "prior_certificate_reference",
        }
        violations: list[Violation] = [
            Violation(f"/{key}", "unknown_field", "unknown field")
            for key in sorted(set(payload) - allowed)
        ]
        premises_id = _uuid(payload.get("premises_id"), "/premises_id", violations)
        service_id: UUID | None = None
        service_key = ""
        if payload.get("service_id") not in (None, ""):
            service_id = _uuid(payload.get("service_id"), "/service_id", violations)
        else:
            service_key = _text(payload, "service_key", violations, max_length=80)
        application_type = payload.get("application_type", "NEW")
        if application_type not in ("NEW", "RENEWAL"):
            violations.append(Violation("/application_type", "invalid", "NEW or RENEWAL"))
        prior = payload.get("prior_certificate_reference")
        if application_type == "RENEWAL" and not (isinstance(prior, str) and prior.strip()):
            violations.append(
                Violation("/prior_certificate_reference", "required", "required for a renewal")
            )
        if violations or premises_id is None:
            raise ValidationFailed(violations=violations)

        # Scope: a premises outside the actor's ownership is indistinguishable from a missing one.
        premises = Premises.objects.filter(pk=premises_id, owner=uow.actor).first()
        if premises is None:
            raise ResourceNotFound("Premises not found")
        services = Service.objects.select_related("owner_queue__jurisdiction")
        service = (
            services.filter(pk=service_id).first()
            if service_id is not None
            else services.filter(key=service_key).first()
        )
        if service is None:
            raise ResourceNotFound("Service not found")
        if not service.active:
            raise ServiceDisabled("This service is not currently accepting applications")

        now = uow.now
        application = _create_with_unique_reference(uow, premises, service, now)
        _create_initial_revision(uow, application, premises, service, application_type, prior)

        event = CaseEvent.objects.create(
            application=application,
            aggregate_version=application.version,
            ordinal=0,
            event_type="application.draft_created.v1",
            actor=uow.actor,
            actor_kind=uow.actor.kind,
            occurred_at=now,
            payload={"draft_reference": application.draft_reference, "service_key": service.key},
            audience=EventAudience.PUBLIC_CASE,
            request_id=uow.request_id,
            command_receipt_id=uow.command_id,
        )
        stage = StageInstance.objects.create(
            application=application,
            state=ApplicationStatus.DRAFT.value,
            cycle_number=1,
            entered_event=event,
            entered_at=now,
        )
        application.current_stage_instance = stage
        application.save(update_fields=["current_stage_instance", "updated_at"])

        return CommandOutcome(
            status=201,
            body={
                "application_id": str(application.id),
                "draft_reference": application.draft_reference,
                "status": application.status,
                "version": application.version,
                "allowed_actions": [
                    {"key": command, "enabled": False, "reason_code": "DRAFT_INCOMPLETE"}
                    for _, command, _ in allowed_transitions(ApplicationStatus.DRAFT)
                ],
            },
            aggregate=application,
            created=True,
            audits=[
                AuditEntry(
                    "application",
                    application.id,
                    "application.draft_created",
                    {
                        "draft_reference": application.draft_reference,
                        "premises_id": str(premises.id),
                        "service_key": service.key,
                    },
                )
            ],
        )


def _uuid(value: Any, pointer: str, violations: list[Violation]) -> UUID | None:
    if value is None or value == "":
        violations.append(Violation(pointer, "required", "is required"))
        return None
    try:
        return UUID(str(value))
    except ValueError:
        violations.append(Violation(pointer, "invalid", "must be a UUID"))
        return None


def _create_initial_revision(
    uow: UnitOfWork,
    application: Application,
    premises: Premises,
    service: Service,
    application_type: str,
    prior: Any,
) -> None:
    """Revision 1 pre-fills the premises snapshot and pins the form schema of the policy in
    force (or none, when no policy applies yet - the draft then reports that as a blocker)."""
    from agni.policies.selection import artifact_ref, evaluate_applicability

    from ..models import DraftRevision

    applicability = evaluate_applicability(
        service,
        jurisdiction_id=service.owner_queue.jurisdiction_id,
        category_key=premises.category_key,
        at=uow.now,
    )
    form_ref = applicability.form_schema_ref or ""
    artifact = None
    if form_ref:
        from agni.policies.models import PolicyArtifact

        key, _, number = form_ref.partition("#")
        artifact = PolicyArtifact.objects.filter(
            kind="FORM", key=key, number=int(number or 0)
        ).first()
    fields: dict[str, Any] = {
        "display_name": premises.display_name,
        "address_line1": premises.address_line1,
        "address_line2": premises.address_line2,
        "locality": premises.locality,
        "ward_key": premises.ward_key,
        "postal_code": premises.postal_code,
        "category_key": premises.category_key,
        "area_sqm": str(premises.area_sqm),
        "height_m": str(premises.height_m),
        "floor_count": premises.floor_count,
        "occupancy_count": premises.occupancy_count,
        "application_type": application_type,
    }
    if isinstance(prior, str) and prior.strip():
        fields["prior_certificate_reference"] = prior.strip()[:40]
    revision = DraftRevision.objects.create(
        application=application,
        revision_number=1,
        editable_payload={"fields": fields, "declaration_drafts": [], "attachment_links": []},
        form_schema_ref=form_ref,
        form_schema_artifact=artifact,
        saved_by=uow.actor,
        saved_at=uow.now,
    )
    application.current_draft_revision = revision
    application.save(update_fields=["current_draft_revision", "updated_at"])
    _ = artifact_ref  # imported for symmetry with selection; policy label read by the detail view


def _create_with_unique_reference(
    uow: UnitOfWork, premises: Premises, service: Service, now: Any
) -> Application:
    for _ in range(5):
        try:
            with (
                transaction.atomic()
            ):  # savepoint: a reference collision must not poison the outer transaction
                return Application.objects.create(
                    draft_reference=_draft_reference(now.year),
                    applicant=uow.actor,
                    acting_operator=uow.actor,
                    premises=premises,
                    service=service,
                    owner_queue=service.owner_queue,
                    status=ApplicationStatus.DRAFT.value,
                )
        except IntegrityError:
            continue
    raise RuntimeError("could not allocate a unique draft reference after 5 attempts")
