"""Threshold plan for one obligation cycle (FR-19; workflow s.8; docs/08 s.5).

Pure: given the pinned policy's `reminder_fractions` and `escalation_minutes_after_due`, the
obligation's start/budget/basis, its calendar and its pauses, return the instants at which each
logical threshold is crossed. Reminder fractions apply to the *active* budget (so a 75 % reminder
of a working-time task lands at 75 % of the working minutes, not of wall-clock time);
escalations are calendar minutes after the due instant. Keys are stable so persistence can
enforce exactly one action per (obligation, stage instance, key)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .clock import Pause, WorkingCalendar, due_instant


@dataclass(frozen=True)
class Threshold:
    key: str
    action_type: str  # REMINDER | ESCALATION
    scheduled_for: datetime
    level: int = 0


def threshold_plan(
    *,
    policy_payload: dict[str, Any],
    basis: str,
    started_at: datetime,
    budget_minutes: int,
    due_at: datetime | None,
    calendar: WorkingCalendar | None,
    pauses: Sequence[Pause] = (),
) -> list[Threshold]:
    plan: list[Threshold] = []
    fractions = [
        float(f)
        for f in policy_payload.get("reminder_fractions", [])
        if isinstance(f, int | float) and 0 < float(f) <= 1
    ]
    for fraction in sorted(set(fractions)):
        if fraction >= 1.0:
            if due_at is not None:
                plan.append(Threshold("DUE", "REMINDER", due_at, 0))
            continue
        partial = max(1, int(round(budget_minutes * fraction)))
        instant = due_instant(
            basis=basis,
            started_at=started_at,
            budget_minutes=partial,
            calendar=calendar,
            pauses=pauses,
        )
        if instant is not None:
            plan.append(
                Threshold(f"REMINDER_{int(round(fraction * 100)):02d}", "REMINDER", instant)
            )
    if due_at is not None:
        levels = [
            int(m)
            for m in policy_payload.get("escalation_minutes_after_due", [])
            if isinstance(m, int | float) and int(m) >= 0
        ]
        for level, minutes in enumerate(sorted(set(levels)), start=1):
            plan.append(
                Threshold(
                    f"ESCALATION_{minutes}",
                    "ESCALATION",
                    due_at + timedelta(minutes=minutes),
                    level,
                )
            )
    return sorted(plan, key=lambda t: (t.scheduled_for, t.key))


def due_thresholds(plan: Sequence[Threshold], now: datetime) -> list[Threshold]:
    return [t for t in plan if t.scheduled_for <= now]
