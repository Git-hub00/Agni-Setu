"""Persistent clock recomputation (FR-18): due instants are derived from immutable facts
(start, budget, basis, pinned calendar) plus the persisted pauses, never edited by hand. A
recomputation writes the new `due_at` and supersedes future threshold actions that would now
fire at the wrong instant."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction

from agni.identity.models import Principal
from agni.platform.errors import InvalidTransition, ValidationFailed, Violation
from agni.policies.models import PolicyVersion

from ..domain.clock import Pause, WorkingCalendar, active_minutes, due_instant
from ..models import Obligation, ObligationPause, ObligationState, ThresholdAction


def pauses_for(obligation: Obligation) -> list[Pause]:
    return [
        Pause(p.starts_at, p.ends_at)
        for p in ObligationPause.objects.filter(obligation=obligation).order_by("starts_at")
    ]


def calendar_for(obligation: Obligation) -> WorkingCalendar | None:
    artifact = obligation.calendar_artifact
    return WorkingCalendar.from_artifact(artifact.payload) if artifact is not None else None


def clock_breakdown(obligation: Obligation, *, cutoff: datetime) -> dict[str, Any]:
    pauses = pauses_for(obligation)
    calendar = calendar_for(obligation)
    elapsed = active_minutes(
        basis=obligation.time_basis,
        started_at=obligation.started_at,
        cutoff=cutoff,
        calendar=calendar,
        pauses=pauses,
    )
    open_pause = any(p.ends_at is None for p in pauses)
    return {
        "basis": obligation.time_basis,
        "started_at": obligation.started_at.isoformat(),
        "budget_minutes": obligation.budget_minutes,
        "active_minutes": elapsed,
        "remaining_minutes": max(0, obligation.budget_minutes - elapsed),
        "due_at": obligation.due_at.isoformat() if obligation.due_at else None,
        "paused": obligation.state == ObligationState.PAUSED or open_pause,
        "due_estimate": "Paused - due date will be recalculated" if open_pause else None,
        "calendar_ref": obligation.calendar_artifact.reference
        if obligation.calendar_artifact
        else None,
        "pauses": [
            {
                "starts_at": p.starts_at.isoformat(),
                "ends_at": p.ends_at.isoformat() if p.ends_at else None,
            }
            for p in pauses
        ],
    }


def recompute_obligation(obligation: Obligation, *, now: datetime) -> Obligation:
    """Derive `due_at` from the persisted facts; supersede stale future threshold actions."""
    pauses = pauses_for(obligation)
    calendar = calendar_for(obligation)
    due = due_instant(
        basis=obligation.time_basis,
        started_at=obligation.started_at,
        budget_minutes=obligation.budget_minutes,
        calendar=calendar,
        pauses=pauses,
    )
    obligation.due_at = due
    open_pause = any(p.ends_at is None for p in pauses)
    if obligation.state in (ObligationState.ACTIVE, ObligationState.PAUSED):
        obligation.state = ObligationState.PAUSED if open_pause else ObligationState.ACTIVE
    obligation.save(update_fields=["due_at", "state", "updated_at"])
    # Future, not yet executed actions are stale once the due instant moves.
    ThresholdAction.objects.filter(
        obligation=obligation, executed_at__isnull=True, superseded_at__isnull=True
    ).update(superseded_at=now)
    return obligation


def add_pause(
    obligation: Obligation,
    *,
    starts_at: datetime,
    ends_at: datetime | None,
    authorized_by: Principal,
    reason_code: str,
    reason: str,
    now: datetime,
    hold_id: Any = None,
    authority_grant_id: Any = None,
) -> ObligationPause:
    """Record an authorised pause. The reason code must be permitted by the pinned policy;
    overlapping pauses are stored as-is and unioned by the clock (never double-subtracted)."""
    if ends_at is not None and ends_at <= starts_at:
        raise ValidationFailed(
            violations=[Violation("/ends_at", "interval", "must be after starts_at")]
        )
    policy = PolicyVersion.objects.filter(pk=obligation.policy_version_id).first()
    permitted = list((policy.payload if policy else {}).get("permitted_pause_reasons", []))
    if reason_code not in permitted:
        raise ValidationFailed(
            violations=[
                Violation(
                    "/reason_code",
                    "not_permitted",
                    f"the pinned policy permits only {permitted or 'no pause reasons'}",
                )
            ]
        )
    if obligation.state not in (ObligationState.ACTIVE, ObligationState.PAUSED):
        raise InvalidTransition("Only an active or paused obligation can be paused")
    with transaction.atomic():
        pause = ObligationPause.objects.create(
            obligation=obligation,
            hold_id=hold_id,
            starts_at=starts_at,
            ends_at=ends_at,
            authorized_by=authorized_by,
            reason_code=reason_code,
            reason=reason,
            authority_grant_id=authority_grant_id,
        )
        recompute_obligation(obligation, now=now)
    return pause


def end_pause(pause: ObligationPause, *, ends_at: datetime, now: datetime) -> ObligationPause:
    if pause.ends_at is not None:
        raise InvalidTransition("This pause already ended")
    if ends_at <= pause.starts_at:
        raise ValidationFailed(
            violations=[Violation("/ends_at", "interval", "must be after starts_at")]
        )
    with transaction.atomic():
        pause.ends_at = ends_at
        pause.version += 1
        pause.save(update_fields=["ends_at", "version", "updated_at"])
        recompute_obligation(pause.obligation, now=now)
    return pause
