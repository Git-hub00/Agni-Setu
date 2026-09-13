"""DEF-015 - the per-entity audit hash chain must survive concurrent appends and out-of-order
event times (invariant: one verifiable chain per entity; FR-28 audit reader).

Found by the production-readiness restore check on 2026-09-13: the live reader chain
`audit_query:<principal>` carried four forks - pairs of audit-search events 1-2 s apart that both
chained to the same predecessor because `record_audit` selected the chain head and inserted
without any per-entity serialisation on the read path (commands are serialised by their aggregate
lock; audit searches are not). `verify_chain` also ordered rows by the caller-supplied event time,
so two overlapping requests whose later-started one committed first broke verification even
without a fork. The writer now serialises appends per chain with a transaction-scoped advisory
lock and selects the head by following the links; verification follows the links too.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.utils import timezone

from agni.identity.models import Principal
from agni.platform import audit
from agni.platform.audit_reader import record_audit_read
from agni.platform.canonical import canonical_sha256
from agni.platform.models import AuditEvent

CHAIN = "audit_query"


def _rows(entity_id: Any) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(entity_type=CHAIN, entity_id=entity_id))


@pytest.mark.django_db(transaction=True)
def test_concurrent_audit_reads_do_not_fork_the_readers_chain(applicant: Principal) -> None:
    """Six audit searches by the same reader race through the barrier; the chain must stay a
    single verifiable path (every prior_hash used exactly once)."""
    workers = 6
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                record_audit_read(
                    principal_id=applicant.pk,
                    request_id=uuid4(),
                    now=timezone.now(),
                    filters={"entity_type": "application"},
                    count=0,
                )
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    rows = _rows(applicant.pk)
    assert len(rows) == workers
    priors = [row.prior_hash for row in rows]
    assert len(set(priors)) == workers, "two rows chained to the same predecessor (fork)"
    assert audit.verify_chain(CHAIN, applicant.pk) is True


@pytest.mark.django_db
def test_verify_chain_detects_a_fork(applicant: Principal) -> None:
    now = timezone.now()
    root = audit.record_audit(
        entity_type=CHAIN,
        entity_id=applicant.pk,
        action="audit.read",
        actor_id=applicant.pk,
        request_id=uuid4(),
        at=now,
        summary={"count": 0},
    )
    for offset in (1, 2):
        # Two honest-looking rows that both chain to the root: exactly what two overlapping
        # requests produced before the fix.
        at = now + timedelta(seconds=offset)
        request_id = uuid4()
        payload = {
            "prior_hash": root.hash,
            "entity_type": CHAIN,
            "entity_id": applicant.pk,
            "action": "audit.read",
            "actor_id": applicant.pk,
            "request_id": request_id,
            "timestamp": at,
            "summary": {"count": offset},
        }
        AuditEvent.objects.create(
            entity_type=CHAIN,
            entity_id=applicant.pk,
            action="audit.read",
            actor_id=applicant.pk,
            request_id=request_id,
            timestamp=at,
            safe_change_summary={"count": offset},
            prior_hash=root.hash,
            hash=canonical_sha256(payload),
        )
    assert audit.verify_chain(CHAIN, applicant.pk) is False


@pytest.mark.django_db
def test_verify_chain_follows_links_when_event_times_are_out_of_order(
    applicant: Principal,
) -> None:
    """A request that started earlier (older event time) may commit after a later one. The chain
    is defined by its links, not by the clock, so it must still verify."""
    base = timezone.now()
    for seconds in (10, 5, 7):
        audit.record_audit(
            entity_type=CHAIN,
            entity_id=applicant.pk,
            action="audit.read",
            actor_id=applicant.pk,
            request_id=uuid4(),
            at=base + timedelta(seconds=seconds),
            summary={"count": seconds},
        )
    rows = _rows(applicant.pk)
    assert len(rows) == 3
    assert len({row.prior_hash for row in rows}) == 3, "each predecessor used exactly once"
    assert audit.verify_chain(CHAIN, applicant.pk) is True


@pytest.mark.django_db
def test_head_selection_follows_links_not_event_times(applicant: Principal) -> None:
    base = timezone.now()
    first = audit.record_audit(
        entity_type=CHAIN,
        entity_id=applicant.pk,
        action="audit.read",
        actor_id=applicant.pk,
        request_id=uuid4(),
        at=base + timedelta(seconds=10),
        summary={"count": 1},
    )
    second = audit.record_audit(
        entity_type=CHAIN,
        entity_id=applicant.pk,
        action="audit.read",
        actor_id=applicant.pk,
        request_id=uuid4(),
        at=base,  # an older event time than the row already recorded
        summary={"count": 2},
    )
    assert second.prior_hash == first.hash
    assert audit.verify_chain(CHAIN, applicant.pk) is True


@pytest.mark.django_db
def test_empty_and_single_row_chains_verify(applicant: Principal) -> None:
    assert audit.verify_chain(CHAIN, applicant.pk) is True
    audit.record_audit(
        entity_type=CHAIN,
        entity_id=applicant.pk,
        action="audit.read",
        actor_id=applicant.pk,
        request_id=uuid4(),
        at=timezone.now(),
        summary={"count": 0},
    )
    assert audit.verify_chain(CHAIN, applicant.pk) is True
