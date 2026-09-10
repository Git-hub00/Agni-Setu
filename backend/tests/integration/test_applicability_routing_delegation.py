"""FR-03 applicability (AT-03), routing resolution (FR-07 foundations) and FR-10 delegation
(AT-10), including the API surface with real sessions and CSRF."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, Premises
from agni.cases.selectors import visible_applications, visible_premises
from agni.identity import otp
from agni.identity.application.delegations import (
    ConfirmDelegation,
    ProposeDelegation,
    RevokeDelegation,
)
from agni.identity.authz import load_snapshot
from agni.identity.contacts import normalize_contact
from agni.identity.models import Delegation, Principal
from agni.platform.clock import FrozenClock
from agni.platform.commands import CommandEnvelope, execute
from agni.platform.errors import (
    InvalidTransition,
    ResourceNotFound,
    SeparationOfDuties,
    ValidationFailed,
)
from agni.policies.models import Jurisdiction, PolicyArtifact, Service
from agni.policies.selection import evaluate_applicability
from agni.routing.models import DutyQueue, RoutingEntry
from agni.routing.resolution import RoutingFailure, RoutingUnresolvedError, resolve_route

from .conftest import demo_policy_payload
from .test_policy_governance import approved_active_v1, env


@pytest.mark.django_db
def test_at_03_applicability_reports_exact_requirements_or_uncertainty(
    governance_actors: dict[str, Principal],
    service: Service,
    inactive_service: Service,
    artifacts: dict[str, PolicyArtifact],
    jurisdiction: Jurisdiction,
    clock: FrozenClock,
) -> None:
    before = evaluate_applicability(
        service, jurisdiction_id=jurisdiction.pk, category_key="Hospital", at=clock.now()
    )
    assert (
        before.applicable is False
        and "No approved policy" in before.explanation
        and before.required_documents == ()
    )

    approved_active_v1(governance_actors, service, clock)
    hospital = evaluate_applicability(
        service, jurisdiction_id=jurisdiction.pk, category_key="Hospital", at=clock.now()
    )
    assert hospital.applicable is True and hospital.policy_number == 1
    assert hospital.required_documents == ("ownership", "plan", "electrical", "evacuation")
    assert (
        hospital.form_schema_ref == "premises-v1#1"
        and hospital.checklist_ref == "demo-checklist-v1#1"
    )
    office = evaluate_applicability(
        service, jurisdiction_id=jurisdiction.pk, category_key="Office", at=clock.now()
    )
    assert office.required_documents == ("ownership", "plan", "electrical")

    unknown = evaluate_applicability(
        service, jurisdiction_id=jurisdiction.pk, category_key="Nightclub", at=clock.now()
    )
    assert (
        unknown.applicable is False
        and unknown.required_documents == ()
        and "not covered" in unknown.explanation
    )
    assert set(unknown.allowed_categories) == set(demo_policy_payload()["allowed_categories"])

    other_jurisdiction = Jurisdiction.objects.create(code="ELSEWHERE", display_name="Unsupported")
    assert (
        evaluate_applicability(
            service, jurisdiction_id=other_jurisdiction.pk, category_key="Office", at=clock.now()
        ).applicable
        is False
    )
    assert (
        evaluate_applicability(
            inactive_service, jurisdiction_id=jurisdiction.pk, category_key="Office", at=clock.now()
        ).applicable
        is False
    )
    assert hospital.as_dict()["binding"] is False


@pytest.mark.django_db
def test_catalogue_and_applicability_api(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    approved_active_v1(governance_actors, service, clock)
    public = Client().get("/api/v1/services?category_key=Hospital")
    assert public.status_code == 200
    item = next(i for i in public.json()["data"]["items"] if i["key"] == service.key)
    assert item["available"] is True and "Hospital" in item["allowed_categories"]
    assert Client().get("/api/v1/services?category_key=bad%20key").status_code == 400

    client = signed_client(applicant)
    response = client.post(
        f"/api/v1/services/{service.pk}/applicability",
        data={"declared_category": "School"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["applicable"] is True and body["required_documents"] == [
        "ownership",
        "plan",
        "electrical",
        "evacuation",
    ]
    assert Client().post(
        f"/api/v1/services/{service.pk}/applicability",
        data={"declared_category": "School"},
        content_type="application/json",
    ).status_code in (401, 403)
    bad = client.post(
        f"/api/v1/services/{service.pk}/applicability",
        data={"declared_category": "", "extra": 1},
        content_type="application/json",
    )
    assert bad.status_code == 422 and {v["pointer"] for v in bad.json()["violations"]} == {
        "/extra",
        "/declared_category",
    }


@pytest.mark.django_db
def test_routing_resolution_rules(
    artifacts: dict[str, PolicyArtifact],
    jurisdiction: Jurisdiction,
    duty_queue: DutyQueue,
    clock: FrozenClock,
) -> None:
    routing = artifacts["ROUTING"]
    other_queue = DutyQueue.objects.create(
        jurisdiction=jurisdiction, queue_key="demo-hospitals", display_name="Hospital desk"
    )
    inactive_queue = DutyQueue.objects.create(
        jurisdiction=jurisdiction, queue_key="closed-desk", display_name="Closed", active=False
    )
    entries = [
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-01",
            category_key=None,
            target_jurisdiction=jurisdiction,
            target_queue=duty_queue,
            priority=0,
        ),
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-01",
            category_key="Hospital",
            target_jurisdiction=jurisdiction,
            target_queue=other_queue,
            priority=0,
        ),
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-09",
            category_key=None,
            target_jurisdiction=jurisdiction,
            target_queue=duty_queue,
            priority=1,
        ),
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-09",
            category_key=None,
            target_jurisdiction=jurisdiction,
            target_queue=other_queue,
            priority=1,
        ),
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-10",
            category_key=None,
            target_jurisdiction=jurisdiction,
            target_queue=inactive_queue,
            priority=0,
        ),
        RoutingEntry.objects.create(
            artifact=routing,
            ward_key="W-11",
            category_key=None,
            target_jurisdiction=jurisdiction,
            target_queue=duty_queue,
            priority=0,
            effective_until=clock.now() - timedelta(days=1),
        ),
    ]
    now = clock.now()
    assert (
        resolve_route(entries, ward_key="W-01", category_key="Office", at=now).target_queue_id
        == duty_queue.pk
    )
    assert (
        resolve_route(entries, ward_key="W-01", category_key="Hospital", at=now).target_queue_id
        == other_queue.pk
    )  # specific beats wildcard
    with pytest.raises(RoutingUnresolvedError) as multi:
        resolve_route(entries, ward_key="W-09", category_key="Office", at=now)
    assert multi.value.code == RoutingFailure.MULTIPLE_MATCH
    with pytest.raises(RoutingUnresolvedError) as none:
        resolve_route(entries, ward_key="W-99", category_key="Office", at=now)
    assert none.value.code == RoutingFailure.NO_MATCH
    with pytest.raises(RoutingUnresolvedError) as inactive:
        resolve_route(entries, ward_key="W-10", category_key="Office", at=now)
    assert inactive.value.code == RoutingFailure.INACTIVE_TARGET
    with pytest.raises(RoutingUnresolvedError) as expired:
        resolve_route(entries, ward_key="W-11", category_key="Office", at=now)
    assert expired.value.code == RoutingFailure.NO_MATCH


def _delegate_env(
    actor: Principal,
    command: str,
    target_type: str,
    target_id: Any,
    payload: dict[str, Any],
    version: int | None = None,
) -> CommandEnvelope:
    return env(actor, command, target_type, target_id, payload, version)


@pytest.mark.django_db
def test_at_10_delegation_lifecycle_and_scope(
    applicant: Principal,
    other_applicant: Principal,
    premises: Premises,
    service: Service,
    duty_queue: DutyQueue,
    clock: FrozenClock,
) -> None:
    beneficiary, delegate = applicant, other_applicant
    contact = normalize_contact("EMAIL", "asha@example.test")
    otp.record_verified_contact(beneficiary, contact, clock.now())
    proposal = {
        "beneficiary_contact": "asha@example.test",
        "beneficiary_channel": "EMAIL",
        "premises_id": str(premises.pk),
        "capabilities": ["draft.edit", "case.read"],
        "effective_from": clock.now().isoformat(),
        "effective_until": (clock.now() + timedelta(days=30)).isoformat(),
        "reason": "Consultant preparing the fire NOC application on behalf of the owner",
    }
    # Unknown contact and self-delegation are indistinguishable from "not found".
    with pytest.raises(ResourceNotFound):
        execute(
            _delegate_env(
                delegate,
                "propose-delegation",
                "propose-delegation:scope",
                delegate.pk,
                {**proposal, "beneficiary_contact": "nobody@example.test"},
            ),
            ProposeDelegation(),
            clock=clock,
        )
    with pytest.raises(ResourceNotFound):
        execute(
            _delegate_env(
                beneficiary,
                "propose-delegation",
                "propose-delegation:scope",
                beneficiary.pk,
                proposal,
            ),
            ProposeDelegation(),
            clock=clock,
        )
    with pytest.raises(ValidationFailed):
        execute(
            _delegate_env(
                delegate,
                "propose-delegation",
                "propose-delegation:scope",
                delegate.pk,
                {**proposal, "capabilities": ["case.decide"]},
            ),
            ProposeDelegation(),
            clock=clock,
        )

    result = execute(
        _delegate_env(
            delegate, "propose-delegation", "propose-delegation:scope", delegate.pk, proposal
        ),
        ProposeDelegation(),
        clock=clock,
    )
    delegation = Delegation.objects.get(pk=result.body["delegation_id"])
    assert (
        delegation.state == "PROPOSED"
        and delegation.beneficiary == beneficiary
        and delegation.delegate == delegate
    )

    # AT-10-02: not yet confirmed -> the delegate sees nothing of the beneficiary.
    application = Application.objects.create(
        draft_reference="DR-DEL-1",
        applicant=beneficiary,
        acting_operator=beneficiary,
        premises=premises,
        service=service,
        owner_queue=duty_queue,
    )
    snap_delegate = load_snapshot(delegate, clock.now())
    assert (
        not visible_applications(snap_delegate, clock.now()).exists()
        and not visible_premises(snap_delegate, clock.now()).exists()
    )

    # The proposer cannot confirm; only the beneficiary can.
    with pytest.raises(SeparationOfDuties):
        execute(
            _delegate_env(delegate, "confirm-delegation", "delegation", delegation.pk, {}, 1),
            ConfirmDelegation(),
            clock=clock,
        )
    execute(
        _delegate_env(beneficiary, "confirm-delegation", "delegation", delegation.pk, {}, 1),
        ConfirmDelegation(),
        clock=clock,
    )
    delegation.refresh_from_db()
    assert delegation.state == "ACTIVE" and delegation.confirmed_at == clock.now()

    # AT-10-01: both identities recorded; delegate now sees the beneficiary's case and premises.
    assert set(visible_applications(snap_delegate, clock.now())) == {application}
    assert set(visible_premises(snap_delegate, clock.now())) == {premises}
    # Outside the interval: nothing.
    assert not visible_applications(snap_delegate, clock.now() + timedelta(days=31)).exists()
    # A third applicant still sees nothing.
    stranger = Principal.objects.create_principal(kind="APPLICANT", display_name="Stranger")
    assert not visible_applications(load_snapshot(stranger, clock.now()), clock.now()).exists()

    # AT-10-03: beneficiary revokes; history attributable; delegate loses access.
    execute(
        _delegate_env(
            beneficiary,
            "revoke-delegation",
            "delegation",
            delegation.pk,
            {"reason": "Engagement ended"},
            2,
        ),
        RevokeDelegation(),
        clock=clock,
    )
    delegation.refresh_from_db()
    assert delegation.state == "REVOKED" and delegation.revoked_by == beneficiary
    assert not visible_applications(snap_delegate, clock.now()).exists()
    with pytest.raises(InvalidTransition):
        execute(
            _delegate_env(beneficiary, "confirm-delegation", "delegation", delegation.pk, {}, 3),
            ConfirmDelegation(),
            clock=clock,
        )
    assert Delegation.objects.count() == 1  # history retained, nothing deleted


@pytest.mark.django_db
def test_delegation_api_lists_both_roles(
    applicant: Principal,
    other_applicant: Principal,
    premises: Premises,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    otp.record_verified_contact(
        applicant, normalize_contact("EMAIL", "asha@example.test"), clock.now()
    )
    delegate_client = signed_client(other_applicant)
    response = delegate_client.post(
        "/api/v1/delegations",
        data={
            "beneficiary_contact": "asha@example.test",
            "beneficiary_channel": "EMAIL",
            "premises_id": str(premises.pk),
            "capabilities": ["case.read"],
            "effective_from": clock.now().isoformat(),
            "effective_until": (clock.now() + timedelta(days=10)).isoformat(),
            "reason": "Reading access for the consultant during the application",
        },
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.content
    delegation_id = response.json()["data"]["delegation_id"]
    assert response["ETag"] == f'"delegation:{delegation_id}:v1"'

    beneficiary_client = signed_client(applicant)
    listing = beneficiary_client.get("/api/v1/delegations").json()["data"]["items"]
    assert listing[0]["role"] == "beneficiary" and listing[0]["state"] == "PROPOSED"
    confirm = beneficiary_client.post(
        f"/api/v1/delegations/{delegation_id}/confirm",
        data={},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4()), "If-Match": response["ETag"]},
    )
    assert confirm.status_code == 200 and confirm.json()["data"]["state"] == "ACTIVE"
    stale = beneficiary_client.post(
        f"/api/v1/delegations/{delegation_id}/revoke",
        data={"reason": "done"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4()), "If-Match": response["ETag"]},
    )
    assert stale.status_code == 412 and stale.json()["code"] == "VERSION_CONFLICT"
    missing = beneficiary_client.post(
        f"/api/v1/delegations/{delegation_id}/revoke",
        data={"reason": "done"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert missing.status_code == 428
