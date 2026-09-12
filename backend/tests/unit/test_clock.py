"""Clock model worked tests (workflow s.8) plus pause-union and open-pause behaviour."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from agni.obligations.domain.clock import Pause, WorkingCalendar, active_minutes, due_instant

IST = ZoneInfo("Asia/Kolkata")
CALENDAR = WorkingCalendar.from_artifact(
    {
        "timezone": "Asia/Kolkata",
        "working_hours": {d: ["09:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")},
        "holidays": [],
    }
)
WITH_HOLIDAY = WorkingCalendar.from_artifact(
    {
        "timezone": "Asia/Kolkata",
        "working_hours": {d: ["09:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")},
        "holidays": ["2026-09-14"],  # the Monday after Friday 2026-09-11
    }
)


def local(day: int, hour: int, minute: int = 0, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=IST).astimezone(UTC)


def test_monday_0900_240_working_minutes_is_due_1300() -> None:
    assert due_instant(
        basis="WORKING", started_at=local(7, 9), budget_minutes=240, calendar=CALENDAR
    ) == local(7, 13)


def test_authorized_pause_shifts_due_by_the_pause() -> None:
    pauses = [Pause(local(7, 10), local(7, 11))]
    assert due_instant(
        basis="WORKING",
        started_at=local(7, 9),
        budget_minutes=240,
        calendar=CALENDAR,
        pauses=pauses,
    ) == local(7, 14)


# PROP-06 (overlapping pauses are unioned; elapsed time never negative)
def test_overlapping_pauses_are_subtracted_once() -> None:
    pauses = [Pause(local(7, 10), local(7, 11)), Pause(local(7, 10, 30), local(7, 11, 30))]
    assert due_instant(
        basis="WORKING",
        started_at=local(7, 9),
        budget_minutes=240,
        calendar=CALENDAR,
        pauses=pauses,
    ) == local(7, 14, 30)


def test_friday_1600_rolls_over_the_weekend() -> None:
    assert due_instant(
        basis="WORKING", started_at=local(11, 16), budget_minutes=240, calendar=CALENDAR
    ) == local(14, 12)


def test_pinned_holiday_pushes_to_tuesday() -> None:
    assert due_instant(
        basis="WORKING", started_at=local(11, 16), budget_minutes=240, calendar=WITH_HOLIDAY
    ) == local(15, 12)


def test_calendar_hours_ignore_the_working_calendar() -> None:
    saturday = local(12, 10, 30)
    assert due_instant(basis="CALENDAR", started_at=saturday, budget_minutes=24 * 60) == local(
        13, 10, 30
    )


def test_open_pause_means_no_estimate_and_boundary_equality_is_due() -> None:
    assert (
        due_instant(
            basis="WORKING",
            started_at=local(7, 9),
            budget_minutes=240,
            calendar=CALENDAR,
            pauses=[Pause(local(7, 10), None)],
        )
        is None
    )
    # Exactly 480 working minutes from 09:00 is 17:00 the same day (boundary), not the next day.
    assert due_instant(
        basis="WORKING", started_at=local(7, 9), budget_minutes=480, calendar=CALENDAR
    ) == local(7, 17)
    with pytest.raises(ValueError):
        due_instant(basis="CALENDAR", started_at=local(7, 9), budget_minutes=0)


def test_active_minutes_clamps_open_pauses_to_the_cutoff() -> None:
    assert (
        active_minutes(
            basis="WORKING", started_at=local(7, 9), cutoff=local(7, 13), calendar=CALENDAR
        )
        == 240
    )
    assert (
        active_minutes(
            basis="WORKING",
            started_at=local(7, 9),
            cutoff=local(7, 13),
            calendar=CALENDAR,
            pauses=[Pause(local(7, 10), local(7, 11))],
        )
        == 180
    )
    assert (
        active_minutes(
            basis="WORKING",
            started_at=local(7, 9),
            cutoff=local(7, 13),
            calendar=CALENDAR,
            pauses=[Pause(local(7, 12), None)],
        )
        == 180
    )
    assert (
        active_minutes(basis="CALENDAR", started_at=local(12, 10, 30), cutoff=local(13, 10, 30))
        == 1440
    )
    # Weekend start: nothing accrues until Monday 09:00.
    assert (
        active_minutes(
            basis="WORKING", started_at=local(12, 10), cutoff=local(14, 10), calendar=CALENDAR
        )
        == 60
    )


def test_calendar_rejects_invalid_hours() -> None:
    with pytest.raises(ValueError):
        WorkingCalendar.from_artifact(
            {"timezone": "Asia/Kolkata", "working_hours": {"mon": ["17:00", "09:00"]}}
        )
    with pytest.raises(ValueError):
        WorkingCalendar.from_artifact(
            {"timezone": "Asia/Kolkata", "working_hours": {"funday": ["09:00", "17:00"]}}
        )
