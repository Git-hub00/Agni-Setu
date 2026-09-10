"""RegisterPremises (API-011) and CreateDraftApplication (API-021) on the kernel."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from agni.cases.application.commands import CreateDraftApplication, RegisterPremises
from agni.cases.domain.states import ApplicationStatus
from agni.cases.models import Application, CaseEvent, Premises, StageInstance
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.platform.commands import ActorContext, CommandEnvelope, execute
from agni.platform.errors import Forbidden, ResourceNotFound, ServiceDisabled, ValidationFailed
from agni.platform.models import AuditEvent, CommandReceipt
from agni.policies.models import Service

VALID_PREMISES: dict[str, Any] = {
    "display_name": "Demo Mall",
    "address_line1": "12 Market Street",
    "locality": "Demo Nagar",
    "ward_key": "W-07",
    "postal_code": "560002",
    "category_key": "COMMERCIAL",
    "area_sqm": "4500.00",
    "height_m": "18.50",
    "floor_count": 4,
    "occupancy_count": 800,
}


def _create_env(
    actor: Principal, command: str, payload: dict[str, Any], key: str
) -> CommandEnvelope:
    return CommandEnvelope(
        actor=ActorContext(principal_id=actor.pk, request_id=uuid4()),
        command_name=command,
        target_type=f"{command}:scope",
        target_id=actor.pk,
        payload=payload,
        idempotency_key=key,
    )


@pytest.mark.django_db
def test_register_premises_creates_owned_master_record(
    applicant: Principal, clock: FrozenClock
) -> None:
    result = execute(
        _create_env(applicant, "register-premises", VALID_PREMISES, "p-1"),
        RegisterPremises(),
        clock=clock,
    )

    assert result.status == 201
    premises = Premises.objects.get(pk=result.body["premises_id"])
    assert premises.owner == applicant and premises.version == 1 and result.body["version"] == 1
    assert str(premises.area_sqm) == "4500.00"
    assert AuditEvent.objects.filter(
        entity_type="premises", entity_id=premises.pk, action="premises.registered"
    ).exists()
    assert CommandReceipt.objects.count() == 1


@pytest.mark.django_db
def test_register_premises_reports_every_violation_with_pointers(
    applicant: Principal, clock: FrozenClock
) -> None:
    bad = {**VALID_PREMISES, "postal_code": "12", "area_sqm": "-1", "floor_count": 0, "bogus": True}
    with pytest.raises(ValidationFailed) as excinfo:
        execute(
            _create_env(applicant, "register-premises", bad, "p-bad"),
            RegisterPremises(),
            clock=clock,
        )
    pointers = {v.pointer for v in excinfo.value.violations}
    assert {"/postal_code", "/area_sqm", "/floor_count", "/bogus"} <= pointers
    assert not Premises.objects.exists() and not CommandReceipt.objects.exists()


@pytest.mark.django_db
def test_staff_cannot_register_premises(staff: Principal, clock: FrozenClock) -> None:
    with pytest.raises(Forbidden):
        execute(
            _create_env(staff, "register-premises", VALID_PREMISES, "p-staff"),
            RegisterPremises(),
            clock=clock,
        )


@pytest.mark.django_db
def test_create_draft_builds_application_stage_and_event(
    applicant: Principal, premises: Premises, service: Service, clock: FrozenClock
) -> None:
    payload = {"premises_id": str(premises.pk), "service_key": service.key}
    result = execute(
        _create_env(applicant, "create-draft", payload, "d-1"),
        CreateDraftApplication(),
        clock=clock,
    )

    application = Application.objects.get(pk=result.body["application_id"])
    assert application.status == ApplicationStatus.DRAFT.value
    assert (
        application.draft_reference.startswith("DR-2026-") and application.public_reference is None
    )
    assert application.submitted_at is None and application.owner_queue == service.owner_queue
    assert application.applicant == applicant and application.acting_operator == applicant

    stage = StageInstance.objects.get(application=application)
    assert stage.state == "DRAFT" and stage.cycle_number == 1 and stage.exited_at is None
    assert application.current_stage_instance == stage

    event = CaseEvent.objects.get(application=application)
    assert event.event_type == "application.draft_created.v1"
    assert event.aggregate_version == 1 and event.occurred_at == clock.now()
    assert (
        event.command_receipt_id == result.command_id
    )  # receipt referenced within the same transaction
    assert stage.entered_event == event

    assert result.body["allowed_actions"] == [
        {"key": "submit", "enabled": False, "reason_code": "DRAFT_INCOMPLETE"},
        {"key": "withdraw", "enabled": False, "reason_code": "DRAFT_INCOMPLETE"},
    ]


@pytest.mark.django_db
def test_create_draft_replays_instead_of_creating_twice(
    applicant: Principal, premises: Premises, service: Service, clock: FrozenClock
) -> None:
    payload = {"premises_id": str(premises.pk), "service_key": service.key}
    first = execute(
        _create_env(applicant, "create-draft", payload, "d-dup"),
        CreateDraftApplication(),
        clock=clock,
    )
    second = execute(
        _create_env(applicant, "create-draft", payload, "d-dup"),
        CreateDraftApplication(),
        clock=clock,
    )
    assert second.replayed and second.body["application_id"] == first.body["application_id"]
    assert Application.objects.count() == 1


@pytest.mark.django_db
def test_create_draft_for_someone_elses_premises_is_not_found(
    other_applicant: Principal, premises: Premises, service: Service, clock: FrozenClock
) -> None:
    payload = {"premises_id": str(premises.pk), "service_key": service.key}
    with pytest.raises(ResourceNotFound):
        execute(
            _create_env(other_applicant, "create-draft", payload, "d-x"),
            CreateDraftApplication(),
            clock=clock,
        )
    assert not Application.objects.exists()


@pytest.mark.django_db
def test_create_draft_rejects_inactive_service(
    applicant: Principal, premises: Premises, inactive_service: Service, clock: FrozenClock
) -> None:
    payload = {"premises_id": str(premises.pk), "service_key": inactive_service.key}
    with pytest.raises(ServiceDisabled):
        execute(
            _create_env(applicant, "create-draft", payload, "d-inactive"),
            CreateDraftApplication(),
            clock=clock,
        )


@pytest.mark.django_db
def test_create_draft_validates_payload(applicant: Principal, clock: FrozenClock) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        execute(
            _create_env(
                applicant, "create-draft", {"premises_id": "not-a-uuid", "extra": 1}, "d-v"
            ),
            CreateDraftApplication(),
            clock=clock,
        )
    assert {v.pointer for v in excinfo.value.violations} == {
        "/premises_id",
        "/service_key",
        "/extra",
    }
