"""Clock model (workflow s.8): due instants from a start, an integer minute budget, a time basis
(CALENDAR or WORKING with an IANA-zoned working calendar) and authorized pause intervals.

Active time = eligible intervals between start and cutoff minus the *union* of pauses that
intersect them (overlapping pauses count once). The due instant is the earliest instant at which
active time reaches the budget; boundary equality means due. An open-ended pause means no due
estimate (None) - never a fictitious far-future deadline. Pure functions, UTC in and out."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_DAYS_SEARCHED = 366 * 5  # hard bound: beyond this the due date is reported as unknown


@dataclass(frozen=True)
class Pause:
    starts_at: datetime
    ends_at: datetime | None  # None = still open


@dataclass(frozen=True)
class WorkingCalendar:
    timezone: ZoneInfo
    hours: Mapping[str, tuple[time, time]]  # weekday key -> (open, close) local time
    holidays: frozenset[date]

    @classmethod
    def from_artifact(cls, payload: Mapping[str, Any]) -> WorkingCalendar:
        hours: dict[str, tuple[time, time]] = {}
        for key, window in dict(payload.get("working_hours", {})).items():
            if key not in WEEKDAYS or not isinstance(window, list | tuple) or len(window) != 2:
                raise ValueError(f"invalid working_hours entry for {key!r}")
            opening, closing = (
                time.fromisoformat(str(window[0])),
                time.fromisoformat(str(window[1])),
            )
            if closing <= opening:
                raise ValueError(f"working day {key} closes before it opens")
            hours[key] = (opening, closing)
        holidays = frozenset(date.fromisoformat(str(d)) for d in payload.get("holidays", []))
        return cls(ZoneInfo(str(payload.get("timezone", "UTC"))), hours, holidays)

    def day_window(self, day: date) -> tuple[datetime, datetime] | None:
        """UTC (open, close) for a local calendar day, or None when closed."""
        if day in self.holidays:
            return None
        window = self.hours.get(WEEKDAYS[day.weekday()])
        if window is None:
            return None
        opening = datetime.combine(day, window[0], tzinfo=self.timezone).astimezone(UTC)
        closing = datetime.combine(day, window[1], tzinfo=self.timezone).astimezone(UTC)
        return opening, closing


def _merge_pauses(pauses: Sequence[Pause]) -> list[tuple[datetime, datetime | None]]:
    """Union of pause intervals, sorted; an open pause swallows everything after it."""
    ordered = sorted(pauses, key=lambda p: p.starts_at)
    merged: list[tuple[datetime, datetime | None]] = []
    for pause in ordered:
        if merged and merged[-1][1] is None:
            break
        if merged and merged[-1][1] is not None and pause.starts_at <= merged[-1][1]:
            start, end = merged[-1]
            new_end = None if pause.ends_at is None else max(end, pause.ends_at)  # type: ignore[type-var]
            merged[-1] = (start, new_end)
        else:
            merged.append((pause.starts_at, pause.ends_at))
    return merged


def _eligible_intervals(
    basis: str, start: datetime, calendar: WorkingCalendar | None
) -> Iterator[tuple[datetime, datetime]]:
    """Consecutive eligible intervals from `start` (UTC), bounded by MAX_DAYS_SEARCHED."""
    start = start.astimezone(UTC)
    if basis == "CALENDAR":
        cursor = start
        for _ in range(MAX_DAYS_SEARCHED):
            nxt = cursor + timedelta(days=1)
            yield cursor, nxt
            cursor = nxt
        return
    if calendar is None:
        raise ValueError("WORKING basis needs a calendar")
    local_day = start.astimezone(calendar.timezone).date()
    for offset in range(MAX_DAYS_SEARCHED):
        day = local_day + timedelta(days=offset)
        window = calendar.day_window(day)
        if window is None:
            continue
        opening, closing = window
        if closing <= start:
            continue
        yield max(opening, start), closing


def due_instant(
    *,
    basis: str,
    started_at: datetime,
    budget_minutes: int,
    calendar: WorkingCalendar | None = None,
    pauses: Sequence[Pause] = (),
) -> datetime | None:
    """Earliest instant at which active time reaches the budget, or None when an open pause or
    the search bound prevents an estimate."""
    if budget_minutes <= 0:
        raise ValueError("budget must be positive")
    remaining = timedelta(minutes=budget_minutes)
    merged = _merge_pauses(pauses)
    for seg_start, seg_end in _eligible_intervals(basis, started_at, calendar):
        cursor = seg_start
        for pause_start, pause_end in merged:
            if pause_end is not None and pause_end <= cursor:
                continue
            if pause_start >= seg_end:
                break
            active_until = min(max(pause_start, cursor), seg_end)
            if active_until > cursor:
                span = active_until - cursor
                if remaining <= span:
                    return cursor + remaining
                remaining -= span
            if pause_end is None:
                return None  # open-ended pause: no estimate
            cursor = max(cursor, min(pause_end, seg_end))
            if cursor >= seg_end:
                break
        if cursor < seg_end:
            span = seg_end - cursor
            if remaining <= span:
                return cursor + remaining
            remaining -= span
    return None


def active_minutes(
    *,
    basis: str,
    started_at: datetime,
    cutoff: datetime,
    calendar: WorkingCalendar | None = None,
    pauses: Sequence[Pause] = (),
) -> int:
    """Active minutes elapsed between start and cutoff (open pauses clamped to the cutoff)."""
    total = timedelta(0)
    merged = [(s, e if e is not None else cutoff) for s, e in _merge_pauses(pauses) if s < cutoff]
    for seg_start, seg_end in _eligible_intervals(basis, started_at, calendar):
        if seg_start >= cutoff:
            break
        seg_end = min(seg_end, cutoff)
        cursor = seg_start
        for pause_start, pause_end in merged:
            if pause_end <= cursor:
                continue
            if pause_start >= seg_end:
                break
            if pause_start > cursor:
                total += pause_start - cursor
            cursor = max(cursor, min(pause_end, seg_end))
        if cursor < seg_end:
            total += seg_end - cursor
        if seg_end >= cutoff:
            break
    return int(total.total_seconds() // 60)
