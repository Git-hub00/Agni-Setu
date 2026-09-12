"""Race a privileged command against the revocation of the authority it depends on (docs/08
s.10 "race a decision with grant revocation"; PROP-10). Two real database connections, a
barrier so both start together. Either the command commits before the revocation (and the
revocation then lands) or the revocation wins and the command is refused - never a command
recorded under an already-revoked grant."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection

from agni.identity.application.commands import ApproveAuthorityGrant, RevokeAuthorityGrant
from agni.identity.domain.roles import Capability, ScopeKind
from agni.identity.models import AuthorityGrant, GrantState, Principal
from agni.platform.clock import FrozenClock
from agni.platform.commands import ActorContext, CommandEnvelope, execute
from agni.platform.errors import DomainError
from agni.platform.models import AuditEvent
from tests.integration.test_grants_and_provisioning import (  # noqa: F401 - fixture import
    actors,
    approved_grant,
    staff,
)


def envelope(
    actor: Principal,
    command: str,
    target_type: str,
    target_id: Any,
    payload: dict[str, Any],
    version: int,
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("round_trip", range(3))
def test_privileged_command_and_revocation_race_yield_one_consistent_outcome(
    actors: dict[str, Principal],  # noqa: F811
    clock: FrozenClock,
    round_trip: int,
) -> None:
    approver = actors["grant_authority"]  # holds grant.approve
    approver_grant = AuthorityGrant.objects.get(
        subject=approver, capability=Capability.GRANT_APPROVE, state=GrantState.APPROVED
    )
    # A second grant authority (the admin) who may revoke the approver's power.
    approved_grant(actors["admin"], Capability.GRANT_APPROVE, actors["bootstrap"], approver, clock)
    subject = staff(f"Subject {round_trip}", f"subject-{round_trip}")
    proposed = AuthorityGrant.objects.create(
        subject=subject,
        capability=Capability.CASE_DECIDE,
        scope_kind=ScopeKind.GLOBAL,
        effective_from=clock.now() - timedelta(days=1),
        preparer=actors["admin"],
        state=GrantState.PROPOSED,
    )
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def approve() -> None:
        try:
            barrier.wait(timeout=10)
            execute(
                envelope(
                    approver,
                    "approve-grant",
                    "authority_grant",
                    proposed.pk,
                    {"approval_basis": "Fault drill approval (synthetic)"},
                    proposed.version,
                ),
                ApproveAuthorityGrant(),
                clock=clock,
            )
            outcomes["approve"] = "COMMITTED"
        except DomainError as exc:
            outcomes["approve"] = type(exc).code
        finally:
            connection.close()

    def revoke() -> None:
        try:
            barrier.wait(timeout=10)
            execute(
                envelope(
                    actors["admin"],
                    "revoke-grant",
                    "authority_grant",
                    approver_grant.pk,
                    {"reason": "Fault drill revocation (synthetic)"},
                    approver_grant.version,
                ),
                RevokeAuthorityGrant(),
                clock=clock,
            )
            outcomes["revoke"] = "COMMITTED"
        except DomainError as exc:
            outcomes["revoke"] = type(exc).code
        finally:
            connection.close()

    threads = [threading.Thread(target=approve), threading.Thread(target=revoke)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert set(outcomes) == {"approve", "revoke"}, outcomes
    # Both commands serialise on the approver's authorization fence: the revocation always
    # commits; the approval either committed BEFORE it (and stands) or ran after it and was
    # refused. Never an approval recorded under an already-revoked power.
    proposed.refresh_from_db()
    approver_grant.refresh_from_db()
    assert outcomes["revoke"] == "COMMITTED" and approver_grant.state == GrantState.REVOKED
    if outcomes["approve"] == "COMMITTED":
        assert proposed.state == GrantState.APPROVED
        assert proposed.approved_at is not None and approver_grant.revoked_at is not None
        assert proposed.approved_at <= approver_grant.revoked_at
    else:
        assert proposed.state == GrantState.PROPOSED
        assert outcomes["approve"] in ("FORBIDDEN", "AUTHORITY_REVOKED")
    # Exactly one audit row per committed command; none for refused ones.
    assert AuditEvent.objects.filter(entity_id=proposed.pk, action="grant.approved").count() == (
        1 if proposed.state == GrantState.APPROVED else 0
    )
    assert AuditEvent.objects.filter(
        entity_id=approver_grant.pk, action="grant.revoked"
    ).count() == (1 if approver_grant.state == GrantState.REVOKED else 0)
