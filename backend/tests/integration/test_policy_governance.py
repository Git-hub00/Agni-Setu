"""FR-27 / AT-27-01..05: immutable versions, independent approval, simulation gate, interval
validation, overlap rejection, activation under the service fence, and the activation-vs-
submission race."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction

from agni.identity.models import Principal
from agni.platform.canonical import canonical_sha256
from agni.platform.clock import FrozenClock
from agni.platform.commands import ActorContext, CommandEnvelope, execute
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    PolicyAmbiguous,
    PolicyIntervalOverlap,
    PolicyReviewConflict,
    PolicyUnavailable,
    SeparationOfDuties,
    ValidationFailed,
)
from agni.platform.models import AuditEvent
from agni.policies.application.commands import (
    ActivatePolicy,
    ApprovePolicy,
    PatchPolicyDraft,
    PreparePolicyDraft,
    ReturnPolicy,
    RunPolicySimulation,
    SubmitPolicyForReview,
)
from agni.policies.models import (
    PolicyArtifact,
    PolicyContributor,
    PolicySimulation,
    PolicyVersion,
    Service,
)
from agni.policies.selection import lock_service_fence, select_policy

from .conftest import demo_policy_payload


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


def prepare(
    actor: Principal, service: Service, clock: FrozenClock, **overrides: Any
) -> PolicyVersion:
    result = execute(
        env(
            actor,
            "prepare-policy",
            "prepare-policy:scope",
            actor.pk,
            {
                "service_id": str(service.pk),
                "schema_version": "1.0",
                "payload": demo_policy_payload(**overrides),
                "source_references": ["demo-marker"],
                "reason": "Prepare the synthetic demonstration policy package",
            },
        ),
        PreparePolicyDraft(),
        clock=clock,
    )
    return PolicyVersion.objects.get(pk=result.body["policy_version_id"])


def submit(actor: Principal, version: PolicyVersion, clock: FrozenClock) -> PolicyVersion:
    execute(
        env(
            actor,
            "submit-policy-review",
            "policy_version",
            version.pk,
            {"reason": "Ready for independent review"},
            version.version,
        ),
        SubmitPolicyForReview(),
        clock=clock,
    )
    version.refresh_from_db()
    return version


def simulate(actor: Principal, version: PolicyVersion, clock: FrozenClock) -> dict[str, Any]:
    result = execute(
        env(
            actor,
            "simulate-policy",
            "policy_version",
            version.pk,
            {
                "candidate_sha256": version.payload_sha256,
                "fixture_suite_key": "demo-baseline-v1",
                "reason": "Pre-approval simulation",
            },
            version.version,
        ),
        RunPolicySimulation(),
        clock=clock,
    )
    version.refresh_from_db()
    return result.body


def approve(
    actor: Principal,
    version: PolicyVersion,
    clock: FrozenClock,
    effective_from: str,
    effective_until: str | None = None,
    **extra: Any,
) -> PolicyVersion:
    payload: dict[str, Any] = {
        "candidate_sha256": version.payload_sha256,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "reason": "Independent approval of the demo package",
    }
    payload.update(extra)
    execute(
        env(actor, "approve-policy", "policy_version", version.pk, payload, version.version),
        ApprovePolicy(),
        clock=clock,
    )
    version.refresh_from_db()
    return version


def activate(actor: Principal, version: PolicyVersion, clock: FrozenClock) -> PolicyVersion:
    execute(
        env(
            actor,
            "activate-policy",
            "policy_version",
            version.pk,
            {
                "approved_candidate_sha256": version.payload_sha256,
                "reason": "Activate at approved effective time",
            },
            version.version,
        ),
        ActivatePolicy(),
        clock=clock,
    )
    version.refresh_from_db()
    return version


def approved_active_v1(
    actors: dict[str, Principal], service: Service, clock: FrozenClock
) -> PolicyVersion:
    v1 = prepare(actors["admin"], service, clock)
    submit(actors["admin"], v1, clock)
    simulate(actors["admin"], v1, clock)
    approve(actors["approver"], v1, clock, (clock.now() - timedelta(days=30)).isoformat())
    return activate(actors["activator"], v1, clock)


@pytest.mark.django_db
def test_prepare_validates_schema_records_contributor_and_numbers_versions(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin = governance_actors["admin"]
    v1 = prepare(admin, service, clock)
    assert (
        v1.state == "DRAFT" and v1.number == 1 and v1.payload_sha256 == canonical_sha256(v1.payload)
    )
    assert PolicyContributor.objects.filter(
        policy_version=v1, principal=admin, action="CREATE"
    ).exists()
    assert AuditEvent.objects.filter(
        entity_type="policy_version", entity_id=v1.pk, action="policy.drafted"
    ).exists()
    v2 = prepare(admin, service, clock)
    assert v2.number == 2

    bad = demo_policy_payload()
    del bad["checklist_key"]
    bad["reminder_fractions"] = [1.0, 0.5]
    bad["executable"] = "return 1"
    with pytest.raises(ValidationFailed) as excinfo:
        execute(
            env(
                admin,
                "prepare-policy",
                "prepare-policy:scope",
                admin.pk,
                {
                    "service_id": str(service.pk),
                    "schema_version": "1.0",
                    "payload": bad,
                    "source_references": [],
                    "reason": "broken candidate for test",
                },
            ),
            PreparePolicyDraft(),
            clock=clock,
        )
    pointers = {v.pointer for v in excinfo.value.violations}
    assert "/payload" in pointers or any(p.startswith("/payload") for p in pointers)
    assert any("reminder_fractions" in p for p in pointers)
    assert any("executable" in p for p in pointers)


@pytest.mark.django_db
def test_applicant_cannot_prepare_policy(
    applicant: Principal, service: Service, clock: FrozenClock
) -> None:
    with pytest.raises(Forbidden):
        prepare(applicant, service, clock)


@pytest.mark.django_db
def test_at_27_02_contributors_cannot_approve_and_approval_needs_simulation(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin, editor, approver = (
        governance_actors["admin"],
        governance_actors["editor"],
        governance_actors["approver"],
    )
    v1 = prepare(admin, service, clock)
    execute(
        env(
            editor,
            "patch-policy",
            "policy_version",
            v1.pk,
            {
                "payload": demo_policy_payload(sample_validity_days=730),
                "reason": "Extend sample validity for the demo",
            },
            v1.version,
        ),
        PatchPolicyDraft(),
        clock=clock,
    )
    v1.refresh_from_db()
    assert v1.payload["sample_validity_days"] == 730 and v1.version == 2
    assert set(
        PolicyContributor.objects.filter(policy_version=v1).values_list("action", flat=True)
    ) == {"CREATE", "EDIT"}
    submit(admin, v1, clock)

    # Give both contributors the approval capability: separation of duties is what refuses them.
    from agni.identity.domain.roles import Capability

    from .conftest import grant

    grant(editor, Capability.POLICY_APPROVE, governance_actors["bootstrap"], approver, clock)
    simulate(admin, v1, clock)
    with pytest.raises(SeparationOfDuties):
        approve(editor, v1, clock, clock.now().isoformat())
    assert PolicyVersion.objects.get(pk=v1.pk).state == "IN_REVIEW"

    # Independent approver, but without a passed simulation for the exact hash -> blocked.
    fresh = prepare(admin, service, clock)
    submit(admin, fresh, clock)
    with pytest.raises(PolicyReviewConflict):
        approve(approver, fresh, clock, clock.now().isoformat())
    # Stale hash
    with pytest.raises(PolicyReviewConflict):
        execute(
            env(
                approver,
                "approve-policy",
                "policy_version",
                v1.pk,
                {
                    "candidate_sha256": "0" * 64,
                    "effective_from": clock.now().isoformat(),
                    "reason": "stale candidate attempt",
                },
                v1.version,
            ),
            ApprovePolicy(),
            clock=clock,
        )


@pytest.mark.django_db
def test_simulation_runs_deterministic_checks_and_rejects_stale_candidate(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin = governance_actors["admin"]
    v1 = prepare(admin, service, clock)
    result = simulate(admin, v1, clock)
    assert result["passed"] is True and result["current_candidate_unchanged"] is True
    keys = {c["key"] for c in result["checks"]}
    assert {
        "schema.valid",
        "checklist.mandatory_items",
        "routing.entries_present",
        "clocks.case_target_covers_stages",
        "documents.Hospital",
    } <= keys
    assert PolicySimulation.objects.filter(policy_version=v1, passed=True).count() == 1
    with pytest.raises(PolicyReviewConflict):
        execute(
            env(
                admin,
                "simulate-policy",
                "policy_version",
                v1.pk,
                {
                    "candidate_sha256": "f" * 64,
                    "fixture_suite_key": "demo-baseline-v1",
                    "reason": "stale hash simulation",
                },
                PolicyVersion.objects.get(pk=v1.pk).version,
            ),
            RunPolicySimulation(),
            clock=clock,
        )
    with pytest.raises(ValidationFailed):
        execute(
            env(
                admin,
                "simulate-policy",
                "policy_version",
                v1.pk,
                {
                    "candidate_sha256": v1.payload_sha256,
                    "fixture_suite_key": "not-allowlisted",
                    "reason": "unknown suite",
                },
                PolicyVersion.objects.get(pk=v1.pk).version,
            ),
            RunPolicySimulation(),
            clock=clock,
        )

    # A failing candidate still records the run (passed=false) and blocks approval later.
    weak = prepare(admin, service, clock, case_target_calendar_minutes=10)
    weak_result = simulate(admin, weak, clock)
    assert weak_result["passed"] is False
    assert any(
        c["key"] == "clocks.case_target_covers_stages" and not c["passed"]
        for c in weak_result["checks"]
    )


@pytest.mark.django_db
def test_at_27_01_future_version_affects_only_its_interval(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin, approver, activator = (
        governance_actors["admin"],
        governance_actors["approver"],
        governance_actors["activator"],
    )
    v1 = prepare(admin, service, clock)
    submit(admin, v1, clock)
    simulate(admin, v1, clock)
    future = clock.now() + timedelta(days=7)
    approve(approver, v1, clock, future.isoformat())
    assert v1.state == "APPROVED" and v1.approved_by == approver and v1.effective_from == future
    epoch_before = Service.objects.get(pk=service.pk).activation_epoch
    activate(activator, v1, clock)
    assert v1.state == "SCHEDULED"
    assert Service.objects.get(pk=service.pk).activation_epoch == epoch_before + 1

    with pytest.raises(PolicyUnavailable):
        select_policy(service.pk, v1.jurisdiction_id, clock.now())  # not yet effective
    assert select_policy(service.pk, v1.jurisdiction_id, future + timedelta(minutes=1)).pk == v1.pk
    assert AuditEvent.objects.filter(
        entity_type="service", entity_id=service.pk, action="service.activation_epoch_bumped"
    ).exists()


@pytest.mark.django_db
def test_at_27_02_overlapping_and_invalid_intervals_are_rejected(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin, approver = governance_actors["admin"], governance_actors["approver"]
    v1 = approved_active_v1(governance_actors, service, clock)
    assert v1.state == "ACTIVE" and v1.effective_until is None

    v2 = prepare(admin, service, clock, sample_validity_days=180)
    submit(admin, v2, clock)
    simulate(admin, v2, clock)
    with pytest.raises(PolicyIntervalOverlap):
        approve(approver, v2, clock, (clock.now() + timedelta(days=1)).isoformat())
    with pytest.raises(ValidationFailed):
        approve(
            approver,
            v2,
            clock,
            clock.now().isoformat(),
            (clock.now() - timedelta(days=1)).isoformat(),
        )
    assert PolicyVersion.objects.get(pk=v2.pk).state == "IN_REVIEW"

    # Explicit supersession closes the open-ended predecessor at the new effective instant.
    switch = clock.now() + timedelta(days=2)
    approve(approver, v2, clock, switch.isoformat(), close_predecessor=True)
    v1.refresh_from_db()
    assert v2.state == "APPROVED" and v1.effective_until == switch
    assert select_policy(service.pk, v1.jurisdiction_id, clock.now()).pk == v1.pk
    execute(
        env(
            governance_actors["activator"],
            "activate-policy",
            "policy_version",
            v2.pk,
            {
                "approved_candidate_sha256": v2.payload_sha256,
                "reason": "Schedule the successor version",
            },
            v2.version,
        ),
        ActivatePolicy(),
        clock=clock,
    )
    assert select_policy(service.pk, v1.jurisdiction_id, switch + timedelta(seconds=1)).pk == v2.pk
    # Boundary equality: the switch instant already belongs to v2 (half-open intervals).
    assert select_policy(service.pk, v1.jurisdiction_id, switch).pk == v2.pk


@pytest.mark.django_db
def test_return_and_resubmit_preserve_history(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    admin, approver = governance_actors["admin"], governance_actors["approver"]
    v1 = prepare(admin, service, clock)
    submit(admin, v1, clock)
    execute(
        env(
            approver,
            "return-policy",
            "policy_version",
            v1.pk,
            {"reason": "Please justify the 365-day sample validity"},
            v1.version,
        ),
        ReturnPolicy(),
        clock=clock,
    )
    v1.refresh_from_db()
    assert v1.state == "RETURNED" and "justify" in v1.returned_reason
    execute(
        env(
            admin,
            "patch-policy",
            "policy_version",
            v1.pk,
            {
                "payload": demo_policy_payload(sample_validity_days=365),
                "reason": "Validity kept at 365 days with justification in source refs",
            },
            v1.version,
        ),
        PatchPolicyDraft(),
        clock=clock,
    )
    v1.refresh_from_db()
    assert v1.state == "DRAFT" and v1.review_candidate_sha256 == ""
    with pytest.raises(InvalidTransition):
        execute(
            env(
                approver,
                "return-policy",
                "policy_version",
                v1.pk,
                {"reason": "not in review anymore"},
                v1.version,
            ),
            ReturnPolicy(),
            clock=clock,
        )
    assert AuditEvent.objects.filter(entity_type="policy_version", entity_id=v1.pk).count() >= 4


@pytest.mark.django_db
def test_approved_payload_is_immutable(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    v1 = approved_active_v1(governance_actors, service, clock)
    with pytest.raises(InvalidTransition):
        execute(
            env(
                governance_actors["admin"],
                "patch-policy",
                "policy_version",
                v1.pk,
                {
                    "payload": demo_policy_payload(sample_validity_days=1),
                    "reason": "attempt to edit an active version",
                },
                v1.version,
            ),
            PatchPolicyDraft(),
            clock=clock,
        )
    assert PolicyVersion.objects.get(pk=v1.pk).payload["sample_validity_days"] == 365


@pytest.mark.django_db
def test_ambiguous_policies_are_reported_not_chosen(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    """Defence in depth: if two effective versions ever coexist (e.g. a bad data migration),
    selection refuses rather than picking the last array entry."""
    v1 = approved_active_v1(governance_actors, service, clock)
    v2 = prepare(governance_actors["admin"], service, clock)
    PolicyVersion.objects.filter(pk=v2.pk).update(
        state="ACTIVE",
        effective_from=v1.effective_from,
        approved_by=governance_actors["approver"],
        approved_at=clock.now(),
    )
    with pytest.raises(PolicyAmbiguous):
        select_policy(service.pk, v1.jurisdiction_id, clock.now())


@pytest.mark.django_db(transaction=True)
def test_at_27_05_activation_serialises_with_submission_selection(
    governance_actors: dict[str, Principal],
    service: Service,
    artifacts: dict[str, PolicyArtifact],
    clock: FrozenClock,
) -> None:
    """Both activation and submission lock the service activation fence: a submission that holds
    the fence pins the version visible at that instant; the activation commits afterwards."""
    v1 = approved_active_v1(governance_actors, service, clock)
    admin, approver, activator = (
        governance_actors["admin"],
        governance_actors["approver"],
        governance_actors["activator"],
    )
    v2 = prepare(admin, service, clock, sample_validity_days=180)
    submit(admin, v2, clock)
    simulate(admin, v2, clock)
    # v2 takes over exactly now; v1 is closed at the same instant (half-open intervals).
    switch = clock.now()
    approve(approver, v2, clock, switch.isoformat(), close_predecessor=True)
    v2_version = PolicyVersion.objects.get(pk=v2.pk).version

    order: list[str] = []
    errors: list[BaseException] = []
    holding = threading.Event()
    release = threading.Event()

    def submission_like() -> None:
        try:
            with transaction.atomic():
                lock_service_fence(service.pk)
                # A submission that arrived just before the switch pins the version effective
                # at its own instant, whatever the activation thread is about to do.
                pinned = select_policy(
                    service.pk, v1.jurisdiction_id, switch - timedelta(seconds=1)
                )
                order.append(f"pinned:v{pinned.number}")
                holding.set()
                release.wait(timeout=15)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread
            errors.append(exc)
            holding.set()
        finally:
            connection.close()

    def activation() -> None:
        try:
            holding.wait(timeout=15)
            execute(
                env(
                    activator,
                    "activate-policy",
                    "policy_version",
                    v2.pk,
                    {
                        "approved_candidate_sha256": v2.payload_sha256,
                        "reason": "Activate successor during race",
                    },
                    v2_version,
                ),
                ActivatePolicy(),
                clock=clock,
            )
            order.append("activated:v2")
        except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread
            errors.append(exc)
        finally:
            connection.close()

    t1, t2 = threading.Thread(target=submission_like), threading.Thread(target=activation)
    t1.start()
    t2.start()
    assert holding.wait(timeout=15)
    assert not errors, errors
    time.sleep(0.5)  # the activation is now blocked on the fence held by the submission
    assert order == ["pinned:v1"]
    release.set()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not errors, errors
    assert order == ["pinned:v1", "activated:v2"]
    assert PolicyVersion.objects.get(pk=v2.pk).state == "ACTIVE"
    assert PolicyVersion.objects.get(pk=v1.pk).state == "RETIRED"
    assert select_policy(service.pk, v1.jurisdiction_id, switch).pk == v2.pk
