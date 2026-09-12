"""B02 acceptance (task card): rollback leaves no receipt/outbox; duplicate command has one
result; stale version rejected; critical audit failure aborts mutation. Real PostgreSQL only."""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction

from agni.cases.models import Premises
from agni.identity.models import Principal
from agni.platform import audit as audit_module
from agni.platform.clock import FrozenClock
from agni.platform.commands import (
    ActorContext,
    AuditEntry,
    CommandEnvelope,
    CommandHandler,
    CommandOutcome,
    OutboxIntent,
    UnitOfWork,
    execute,
)
from agni.platform.errors import (
    AuthorityRevoked,
    IdempotencyConflict,
    MalformedRequest,
    PreconditionRequired,
    ResourceNotFound,
    ValidationFailed,
    VersionConflict,
)
from agni.platform.models import AuditEvent, CommandReceipt, OutboxMessage


class RenamePremises(CommandHandler[Premises]):
    """Probe handler over a real aggregate: renames the actor's premises, audits, and emits one
    outbox intent. `fail_after_write` simulates a guard failing after a mutation."""

    def __init__(self, fail_after_write: bool = False) -> None:
        self.fail_after_write = fail_after_write

    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> Premises | None:
        target = (
            Premises.objects.select_for_update()
            .filter(pk=uow.envelope.target_id, owner=uow.actor)
            .first()
        )
        if target is None:
            raise ResourceNotFound("Premises not found")
        return target

    def apply(self, uow: UnitOfWork, target: Premises | None) -> CommandOutcome[Premises]:
        assert target is not None
        new_name = uow.envelope.payload.get("display_name")
        if not isinstance(new_name, str) or not new_name:
            raise ValidationFailed()
        target.display_name = new_name
        target.save(update_fields=["display_name", "updated_at"])
        if self.fail_after_write:
            raise ValidationFailed(detail="simulated guard failure after write")
        return CommandOutcome(
            status=200,
            body={"premises_id": str(target.id), "display_name": new_name},
            aggregate=target,
            audits=[
                AuditEntry("premises", target.id, "premises.renamed", {"display_name": new_name})
            ],
            intents=[
                OutboxIntent(
                    "premises.renamed.v1", "premises", target.id, {"display_name": new_name}
                )
            ],
        )


def _envelope(
    actor: Principal, premises: Premises, *, key: str, version: int | None, name: str = "Renamed"
) -> CommandEnvelope:
    return CommandEnvelope(
        actor=ActorContext(principal_id=actor.pk, request_id=uuid4()),
        command_name="rename-premises",
        target_type="premises",
        target_id=premises.pk,
        payload={"display_name": name},
        idempotency_key=key,
        expected_version=version,
    )


@pytest.mark.django_db
def test_happy_path_bumps_version_and_writes_receipt_audit_outbox(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    result = execute(
        _envelope(applicant, premises, key="k-1", version=1), RenamePremises(), clock=clock
    )

    premises.refresh_from_db()
    assert result.status == 200 and result.replayed is False
    assert premises.display_name == "Renamed" and premises.version == 2
    assert result.resulting_version == 2 and result.body["version"] == 2
    assert result.accepted_at == clock.now()
    receipt = CommandReceipt.objects.get()
    assert receipt.id == result.command_id and receipt.result_status == 200
    assert (
        OutboxMessage.objects.filter(
            event_type="premises.renamed.v1", aggregate_id=premises.pk
        ).count()
        == 1
    )
    audit_row = AuditEvent.objects.get(entity_type="premises", entity_id=premises.pk)
    assert audit_row.actor_id == applicant.pk and audit_row.prior_hash is None
    assert audit_module.verify_chain("premises", premises.pk)


@pytest.mark.django_db
# PROP-04 (replaying an accepted command creates nothing new)
def test_duplicate_command_returns_original_result_once(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    first = execute(
        _envelope(applicant, premises, key="dup", version=1), RenamePremises(), clock=clock
    )
    # A retry after the first commit still carries the client's stale expected_version; replay
    # is resolved BEFORE the version check (API s.4), so the original receipt is returned.
    second = execute(
        _envelope(applicant, premises, key="dup", version=1), RenamePremises(), clock=clock
    )

    assert second.replayed is True and first.replayed is False
    assert second.command_id == first.command_id and second.body == first.body
    assert CommandReceipt.objects.count() == 1
    assert OutboxMessage.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    premises.refresh_from_db()
    assert premises.version == 2


@pytest.mark.django_db
# PROP-05 (same key, different normalised payload never reuses the previous success)
def test_same_key_different_payload_is_idempotency_conflict(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    execute(_envelope(applicant, premises, key="same", version=1), RenamePremises(), clock=clock)
    with pytest.raises(IdempotencyConflict):
        execute(
            _envelope(applicant, premises, key="same", version=2, name="Other"),
            RenamePremises(),
            clock=clock,
        )
    assert CommandReceipt.objects.count() == 1


@pytest.mark.django_db
def test_stale_version_is_rejected_without_side_effects(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    with pytest.raises(VersionConflict) as excinfo:
        execute(
            _envelope(applicant, premises, key="stale", version=99), RenamePremises(), clock=clock
        )
    assert excinfo.value.extensions["current_version"] == 1
    premises.refresh_from_db()
    assert premises.display_name == "Demo Warehouse A" and premises.version == 1
    assert (
        not CommandReceipt.objects.exists()
        and not OutboxMessage.objects.exists()
        and not AuditEvent.objects.exists()
    )


@pytest.mark.django_db
def test_missing_precondition_is_428(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    with pytest.raises(PreconditionRequired):
        execute(
            _envelope(applicant, premises, key="nopre", version=None), RenamePremises(), clock=clock
        )
    assert not CommandReceipt.objects.exists()


@pytest.mark.django_db
def test_missing_idempotency_key_is_malformed(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    with pytest.raises(MalformedRequest):
        execute(_envelope(applicant, premises, key="", version=1), RenamePremises(), clock=clock)


@pytest.mark.django_db
# DS-22 (exception before commit rolls back completely; with tests/faults for after-commit cases)
def test_rollback_after_write_leaves_no_receipt_outbox_or_change(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    with pytest.raises(ValidationFailed):
        execute(
            _envelope(applicant, premises, key="rb", version=1),
            RenamePremises(fail_after_write=True),
            clock=clock,
        )
    premises.refresh_from_db()
    assert premises.display_name == "Demo Warehouse A" and premises.version == 1
    assert (
        not CommandReceipt.objects.exists()
        and not OutboxMessage.objects.exists()
        and not AuditEvent.objects.exists()
    )


@pytest.mark.django_db
def test_audit_failure_aborts_the_mutation(
    applicant: Principal, premises: Premises, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_audit(**_: Any) -> AuditEvent:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(audit_module, "record_audit", broken_audit)
    with pytest.raises(RuntimeError, match="audit store unavailable"):
        execute(
            _envelope(applicant, premises, key="audit", version=1), RenamePremises(), clock=clock
        )
    premises.refresh_from_db()
    assert premises.display_name == "Demo Warehouse A" and premises.version == 1
    assert not CommandReceipt.objects.exists() and not OutboxMessage.objects.exists()


@pytest.mark.django_db
def test_disabled_principal_cannot_command(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    applicant.disable(clock.now())
    applicant.save()
    with pytest.raises(AuthorityRevoked):
        execute(_envelope(applicant, premises, key="dis", version=1), RenamePremises(), clock=clock)
    assert not CommandReceipt.objects.exists()


@pytest.mark.django_db
def test_cross_principal_target_is_not_found_not_forbidden(
    other_applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    with pytest.raises(ResourceNotFound):
        execute(
            _envelope(other_applicant, premises, key="x", version=1), RenamePremises(), clock=clock
        )
    premises.refresh_from_db()
    assert premises.display_name == "Demo Warehouse A"


@pytest.mark.django_db
def test_receipts_are_scoped_per_principal(
    applicant: Principal, other_applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    """The same key from another principal is a different receipt scope, never a replay."""
    execute(_envelope(applicant, premises, key="shared", version=1), RenamePremises(), clock=clock)
    with pytest.raises(ResourceNotFound):
        execute(
            _envelope(other_applicant, premises, key="shared", version=2),
            RenamePremises(),
            clock=clock,
        )
    assert CommandReceipt.objects.filter(principal=applicant).count() == 1
    assert CommandReceipt.objects.filter(principal=other_applicant).count() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_commands_produce_exactly_one_receipt(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    """Two workers race the same command key: the principal fence serialises them, so one
    executes and the other replays. Exactly one receipt, one outbox row, one version bump."""
    results: list[Any] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(
                execute(
                    _envelope(applicant, premises, key="race", version=1),
                    RenamePremises(),
                    clock=clock,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - collected for assertion
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert sorted(r.replayed for r in results) == [False, True]
    assert len({r.command_id for r in results}) == 1
    assert CommandReceipt.objects.count() == 1
    assert OutboxMessage.objects.count() == 1
    premises.refresh_from_db()
    assert premises.version == 2


@pytest.mark.django_db
def test_kernel_runs_inside_a_single_transaction(
    applicant: Principal, premises: Premises, clock: FrozenClock
) -> None:
    """Handlers must not see autocommit: the kernel owns the boundary."""

    class AssertAtomic(RenamePremises):
        def apply(self, uow: UnitOfWork, target: Premises | None) -> CommandOutcome[Premises]:
            assert transaction.get_connection().in_atomic_block
            return super().apply(uow, target)

    execute(_envelope(applicant, premises, key="atomic", version=1), AssertAtomic(), clock=clock)


@pytest.mark.django_db
def test_lock_order_is_sorted_principal_ids(
    applicant: Principal, other_applicant: Principal
) -> None:
    from agni.platform.locks import lock_principal_fences, sorted_unique

    ids: list[UUID] = [other_applicant.pk, applicant.pk, applicant.pk]
    assert sorted_unique(ids) == sorted({applicant.pk, other_applicant.pk})
    with transaction.atomic():
        fences = lock_principal_fences(ids)
        assert [f.principal_id for f in fences] == sorted({applicant.pk, other_applicant.pk})
