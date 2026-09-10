"""FR-02 / AT-02-01..05: provisioning from approved requests, grant approval with separation of
duties, revocation with epoch bump, expired grants, and the revocation-vs-write race."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction

from agni.identity.application.commands import (
    ApproveAuthorityGrant,
    DisablePrincipal,
    ProvisionStaff,
    RevokeAuthorityGrant,
)
from agni.identity.authz import load_snapshot, require_capability
from agni.identity.domain.roles import Capability, RoleKey, ScopeKind
from agni.identity.models import (
    AccessRequest,
    AccessRequestStatus,
    AuthorityGrant,
    GrantState,
    Principal,
    PrincipalKind,
    RoleBinding,
)
from agni.platform.clock import FrozenClock
from agni.platform.commands import ActorContext, CommandEnvelope, execute
from agni.platform.errors import Forbidden, InvalidTransition, SeparationOfDuties
from agni.platform.locks import lock_principal_fences
from agni.platform.models import AuditEvent
from agni.policies.models import Jurisdiction

ISSUER = "http://localhost:8080/realms/agni-dev"


def staff(name: str, subject: str) -> Principal:
    return Principal.objects.create_principal(
        kind=PrincipalKind.STAFF,
        display_name=name,
        external_issuer=ISSUER,
        external_subject=subject,
    )


def bind(
    principal: Principal,
    role: RoleKey,
    approved_by: Principal,
    clock: FrozenClock,
    jurisdiction: Jurisdiction | None = None,
) -> RoleBinding:
    return RoleBinding.objects.create(
        principal=principal,
        role_key=role,
        jurisdiction=jurisdiction,
        effective_from=clock.now() - timedelta(days=1),
        approved_by=approved_by,
    )


def approved_grant(
    subject: Principal,
    capability: Capability,
    preparer: Principal,
    approver: Principal,
    clock: FrozenClock,
    **kw: Any,
) -> AuthorityGrant:
    return AuthorityGrant.objects.create(
        subject=subject,
        capability=capability,
        scope_kind=kw.pop("scope_kind", ScopeKind.GLOBAL),
        effective_from=kw.pop("effective_from", clock.now() - timedelta(days=1)),
        preparer=preparer,
        approver=approver,
        state=GrantState.APPROVED,
        approval_basis="bootstrap fixture",
        approved_at=clock.now() - timedelta(days=1),
        **kw,
    )


def env(
    actor: Principal,
    command: str,
    target_type: str,
    target_id: UUID,
    payload: dict[str, Any],
    version: int | None = None,
) -> CommandEnvelope:
    return CommandEnvelope(
        actor=ActorContext(principal_id=actor.pk, request_id=uuid4()),
        command_name=command,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        idempotency_key=str(uuid4()),
        expected_version=version,
    )


@pytest.fixture
def actors(db: None, clock: FrozenClock) -> dict[str, Principal]:
    bootstrap = staff("Bootstrap Ceremony", "bootstrap")
    admin = staff("Arjun Rao", "arjun")
    grant_authority = staff("Meera Shah", "meera")
    bind(admin, RoleKey.ADMIN, bootstrap, clock)
    approved_grant(admin, Capability.STAFF_PROVISION, bootstrap, grant_authority, clock)
    approved_grant(grant_authority, Capability.GRANT_APPROVE, bootstrap, admin, clock)
    return {"bootstrap": bootstrap, "admin": admin, "grant_authority": grant_authority}


@pytest.fixture
def approved_request(
    actors: dict[str, Principal], jurisdiction: Jurisdiction, clock: FrozenClock
) -> AccessRequest:
    return AccessRequest.objects.create(
        requester=actors["bootstrap"],
        intended_issuer=ISSUER,
        intended_subject="anita",
        intended_display_name="Anita Kapoor",
        requested_role=RoleKey.SUPERVISOR,
        jurisdiction=jurisdiction,
        justification="Supervisor for Demo Circle 1",
        status=AccessRequestStatus.APPROVED,
        approver=actors["grant_authority"],
        decision_at=clock.now(),
    )


@pytest.mark.django_db
def test_at_02_01_provisioning_binds_subject_and_exposes_only_approved_workspace(
    actors: dict[str, Principal], approved_request: AccessRequest, clock: FrozenClock
) -> None:
    admin = actors["admin"]
    result = execute(
        env(
            admin,
            "provision-staff",
            "provision-staff:scope",
            admin.pk,
            {"access_request_id": str(approved_request.pk)},
        ),
        ProvisionStaff(),
        clock=clock,
    )
    assert result.status == 201 and result.body["workspaces"] == ["supervisor"]
    anita = Principal.objects.get(external_issuer=ISSUER, external_subject="anita")
    assert anita.kind == "STAFF" and anita.is_active
    binding = RoleBinding.objects.get(principal=anita)
    assert binding.role_key == "SUPERVISOR" and binding.approved_request == approved_request
    approved_request.refresh_from_db()
    assert approved_request.consumed_at == clock.now() and approved_request.beneficiary == anita
    assert AuditEvent.objects.filter(
        entity_type="principal", entity_id=anita.pk, action="staff.provisioned"
    ).exists()
    snapshot = load_snapshot(anita, clock.now())
    assert snapshot.grants == ()  # a role never implies statutory powers

    with pytest.raises(InvalidTransition):
        execute(
            env(
                admin,
                "provision-staff",
                "provision-staff:scope",
                admin.pk,
                {"access_request_id": str(approved_request.pk)},
            ),
            ProvisionStaff(),
            clock=clock,
        )


@pytest.mark.django_db
def test_at_02_02_public_or_unapproved_paths_cannot_create_privileged_access(
    actors: dict[str, Principal], jurisdiction: Jurisdiction, clock: FrozenClock
) -> None:
    admin = actors["admin"]
    open_request = AccessRequest.objects.create(
        requester=actors["bootstrap"],
        intended_issuer=ISSUER,
        intended_subject="x",
        requested_role=RoleKey.ADMIN,
        justification="j",
    )
    with pytest.raises(InvalidTransition):
        execute(
            env(
                admin,
                "provision-staff",
                "provision-staff:scope",
                admin.pk,
                {"access_request_id": str(open_request.pk)},
            ),
            ProvisionStaff(),
            clock=clock,
        )

    # An applicant (public sign-up path) has no ADMIN role and no capability: Forbidden.
    applicant = Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT, display_name="Anyone"
    )
    with pytest.raises(Forbidden):
        execute(
            env(
                applicant,
                "provision-staff",
                "provision-staff:scope",
                applicant.pk,
                {"access_request_id": str(open_request.pk)},
            ),
            ProvisionStaff(),
            clock=clock,
        )
    assert not Principal.objects.filter(external_subject="x").exists()


@pytest.mark.django_db
def test_requester_or_approver_cannot_provision_their_own_request(
    actors: dict[str, Principal], jurisdiction: Jurisdiction, clock: FrozenClock
) -> None:
    ga = actors["grant_authority"]
    bind(ga, RoleKey.ADMIN, actors["bootstrap"], clock)
    approved_grant(ga, Capability.STAFF_PROVISION, actors["bootstrap"], actors["admin"], clock)
    request = AccessRequest.objects.create(
        requester=actors["bootstrap"],
        intended_issuer=ISSUER,
        intended_subject="y",
        requested_role=RoleKey.OFFICER,
        justification="j",
        status=AccessRequestStatus.APPROVED,
        approver=ga,
        decision_at=clock.now(),
    )
    with pytest.raises(SeparationOfDuties):
        execute(
            env(
                ga,
                "provision-staff",
                "provision-staff:scope",
                ga.pk,
                {"access_request_id": str(request.pk)},
            ),
            ProvisionStaff(),
            clock=clock,
        )


@pytest.mark.django_db
def test_grant_approval_requires_independent_approver_and_bumps_subject_epoch(
    actors: dict[str, Principal], clock: FrozenClock
) -> None:
    subject = staff("Anita Kapoor", "anita")
    proposed = AuthorityGrant.objects.create(
        subject=subject,
        capability=Capability.CASE_DECIDE,
        scope_kind=ScopeKind.GLOBAL,
        effective_from=clock.now(),
        preparer=actors["admin"],
        state=GrantState.PROPOSED,
    )
    epoch_before = subject.authz_epoch
    # Give the preparer the approval power too: separation of duties, not a missing capability,
    # must be what refuses self-approval.
    approved_grant(
        actors["admin"],
        Capability.GRANT_APPROVE,
        actors["bootstrap"],
        actors["grant_authority"],
        clock,
    )

    with pytest.raises(SeparationOfDuties):  # preparer approving own proposal
        execute(
            env(
                actors["admin"],
                "approve-grant",
                "authority_grant",
                proposed.pk,
                {"approval_basis": "I prepared it myself"},
                1,
            ),
            ApproveAuthorityGrant(),
            clock=clock,
        )
    with pytest.raises(Forbidden):  # subject lacks grant.approve capability entirely
        execute(
            env(
                subject,
                "approve-grant",
                "authority_grant",
                proposed.pk,
                {"approval_basis": "approving myself"},
                1,
            ),
            ApproveAuthorityGrant(),
            clock=clock,
        )

    result = execute(
        env(
            actors["grant_authority"],
            "approve-grant",
            "authority_grant",
            proposed.pk,
            {"approval_basis": "Designated grant authority; ceremony ref GA-1"},
            1,
        ),
        ApproveAuthorityGrant(),
        clock=clock,
    )
    proposed.refresh_from_db()
    subject.refresh_from_db()
    assert (
        result.status == 200
        and proposed.state == "APPROVED"
        and proposed.approver == actors["grant_authority"]
    )
    assert proposed.version == 2 and subject.authz_epoch == epoch_before + 1
    snapshot = load_snapshot(subject, clock.now())
    assert require_capability(snapshot, Capability.CASE_DECIDE).grant_id == proposed.pk
    assert AuditEvent.objects.filter(
        entity_type="authority_grant", entity_id=proposed.pk, authority_grant_id=proposed.pk
    ).exists()


@pytest.mark.django_db
def test_at_02_02_expired_and_revoked_grants_are_denied(
    actors: dict[str, Principal], clock: FrozenClock
) -> None:
    subject = staff("Anita Kapoor", "anita")
    expired = approved_grant(
        subject,
        Capability.CASE_DECIDE,
        actors["admin"],
        actors["grant_authority"],
        clock,
        effective_from=clock.now() - timedelta(days=10),
        effective_until=clock.now() - timedelta(days=1),
    )
    with pytest.raises(Forbidden):
        require_capability(load_snapshot(subject, clock.now()), Capability.CASE_DECIDE)
    assert (
        load_snapshot(subject, clock.now() - timedelta(days=5)).grant_for(Capability.CASE_DECIDE)
        is not None
    )  # was valid then

    live = approved_grant(
        subject, Capability.CERTIFICATE_STATUS, actors["admin"], actors["grant_authority"], clock
    )
    assert (
        require_capability(
            load_snapshot(subject, clock.now()), Capability.CERTIFICATE_STATUS
        ).grant_id
        == live.pk
    )
    result = execute(
        env(
            actors["grant_authority"],
            "revoke-grant",
            "authority_grant",
            live.pk,
            {"reason": "role change"},
            1,
        ),
        RevokeAuthorityGrant(),
        clock=clock,
    )
    assert result.body["state"] == "REVOKED"
    with pytest.raises(Forbidden):
        require_capability(load_snapshot(subject, clock.now()), Capability.CERTIFICATE_STATUS)
    assert expired.state == "APPROVED"  # untouched; expiry is time-derived


@pytest.mark.django_db
def test_at_02_03_disable_revokes_bindings_and_bumps_epoch_but_keeps_history(
    actors: dict[str, Principal], clock: FrozenClock
) -> None:
    subject = staff("Suresh Yadav", "suresh")
    bind(subject, RoleKey.OFFICER, actors["bootstrap"], clock)
    result = execute(
        env(
            actors["admin"],
            "disable-principal",
            "principal",
            subject.pk,
            {"reason": "left the service"},
            1,
        ),
        DisablePrincipal(),
        clock=clock,
    )
    subject.refresh_from_db()
    assert (
        result.body["active"] is False and subject.is_active is False and subject.authz_epoch == 2
    )
    assert RoleBinding.objects.filter(principal=subject, revoked_at__isnull=False).count() == 1
    assert RoleBinding.objects.filter(principal=subject).count() == 1  # history retained
    with pytest.raises(SeparationOfDuties):
        execute(
            env(
                actors["admin"],
                "disable-principal",
                "principal",
                actors["admin"].pk,
                {"reason": "self"},
                1,
            ),
            DisablePrincipal(),
            clock=clock,
        )


@pytest.mark.django_db(transaction=True)
def test_at_02_05_revocation_serialises_after_a_write_that_holds_the_subject_fence(
    actors: dict[str, Principal], clock: FrozenClock
) -> None:
    """Lock ordering: a write holding the subject's fence completes before the revocation
    commits; a write that starts after the revocation is denied. No stale-authority acceptance."""
    subject = staff("Anita Kapoor", "anita")
    grant = approved_grant(
        subject, Capability.CASE_DECIDE, actors["admin"], actors["grant_authority"], clock
    )
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def authorized_write() -> None:
        try:
            with transaction.atomic():
                lock_principal_fences([subject.pk])
                require_capability(load_snapshot(subject, clock.now()), Capability.CASE_DECIDE)
                holding.set()
                release.wait(timeout=10)
                order.append("write-committed")
        finally:
            connection.close()

    def revoke() -> None:
        try:
            holding.wait(timeout=10)
            execute(
                env(
                    actors["grant_authority"],
                    "revoke-grant",
                    "authority_grant",
                    grant.pk,
                    {"reason": "race test revocation"},
                    1,
                ),
                RevokeAuthorityGrant(),
                clock=clock,
            )
            order.append("revoked")
        finally:
            connection.close()

    t1, t2 = threading.Thread(target=authorized_write), threading.Thread(target=revoke)
    t1.start()
    t2.start()
    holding.wait(timeout=10)
    import time

    time.sleep(0.5)
    assert order == []  # revocation is blocked behind the fence
    release.set()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert order == ["write-committed", "revoked"]
    with pytest.raises(Forbidden):
        require_capability(
            load_snapshot(Principal.objects.get(pk=subject.pk), clock.now()), Capability.CASE_DECIDE
        )
