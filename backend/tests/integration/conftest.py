"""Integration fixtures: real PostgreSQL rows for principals, master data and premises."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agni.cases.models import Premises
from agni.identity.models import Principal, PrincipalKind
from agni.policies.models import Jurisdiction, Service
from agni.routing.models import DutyQueue


@pytest.fixture
def applicant(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT, display_name="Asha Applicant"
    )


@pytest.fixture
def other_applicant(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT, display_name="Bala Bystander"
    )


@pytest.fixture
def staff(db: None) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name="Chitra Clerk",
        external_issuer="http://localhost:8080/realms/agni-dev",
        external_subject="chitra",
    )


@pytest.fixture
def jurisdiction(db: None) -> Jurisdiction:
    return Jurisdiction.objects.create(code="DEMO-CIRCLE-1", display_name="Demo Circle 1")


@pytest.fixture
def duty_queue(jurisdiction: Jurisdiction) -> DutyQueue:
    return DutyQueue.objects.create(
        jurisdiction=jurisdiction,
        queue_key="demo-central-review",
        display_name="Demo central review",
    )


@pytest.fixture
def service(duty_queue: DutyQueue) -> Service:
    return Service.objects.create(
        key="demo-fire-noc",
        title="Demo fire safety certificate",
        active=True,
        owner_queue=duty_queue,
    )


@pytest.fixture
def inactive_service(duty_queue: DutyQueue) -> Service:
    return Service.objects.create(
        key="demo-dormant", title="Dormant demo service", active=False, owner_queue=duty_queue
    )


@pytest.fixture
def premises(applicant: Principal) -> Premises:
    return Premises.objects.create(
        owner=applicant,
        display_name="Demo Warehouse A",
        address_line1="1 Demo Road",
        locality="Demo Nagar",
        ward_key="W-01",
        postal_code="560001",
        category_key="WAREHOUSE",
        area_sqm=Decimal("1200.50"),
        height_m=Decimal("9.50"),
        floor_count=2,
    )
