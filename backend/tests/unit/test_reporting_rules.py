"""Pure reporting rules (FR-25/26): stage-at-cutoff, nearest-rank percentiles and CSV formula
neutralisation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agni.reporting.domain.metrics import (
    DEFINITION_VERSION,
    DEFINITIONS,
    csv_safe,
    percentile,
    state_at,
)

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def test_state_at_picks_the_stage_in_force_at_the_cutoff() -> None:
    stages: list[tuple[str, datetime, datetime | None]] = [
        ("SUBMITTED", T0, T0 + timedelta(hours=1)),
        ("SCRUTINY", T0 + timedelta(hours=1), T0 + timedelta(days=2)),
        ("INSPECTION_PENDING", T0 + timedelta(days=2), None),
    ]
    assert state_at(stages, T0 - timedelta(seconds=1)) is None
    assert state_at(stages, T0) == "SUBMITTED"
    assert state_at(stages, T0 + timedelta(hours=1)) == "SCRUTINY"  # exited_at is exclusive
    assert state_at(stages, T0 + timedelta(days=1)) == "SCRUTINY"
    assert state_at(stages, T0 + timedelta(days=30)) == "INSPECTION_PENDING"
    # Two entries at the same instant: the later entry wins.
    same: list[tuple[str, datetime, datetime | None]] = [
        ("A", T0, None),
        ("B", T0 + timedelta(microseconds=1), None),
    ]
    assert state_at(same, T0 + timedelta(hours=1)) == "B"


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([], 50, None),
        ([10.0], 50, 10.0),
        ([10.0], 90, 10.0),
        ([1.0, 2.0, 3.0, 4.0], 50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 90, 4.0),
        ([5.0, 1.0, 3.0], 50, 3.0),
        ([float(n) for n in range(1, 11)], 90, 9.0),
    ],
)
def test_percentile_is_nearest_rank(values: list[float], p: float, expected: float | None) -> None:
    assert percentile(values, p) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Demo Warehouse A", "Demo Warehouse A"),
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+1234", "'+1234"),
        ("-cmd", "'-cmd"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("", ""),
        (None, ""),
        (42, "42"),
    ],
)
def test_csv_safe_neutralises_formula_prefixes(value: object, expected: str) -> None:
    assert csv_safe(value) == expected


def test_definitions_are_versioned_and_complete() -> None:
    assert DEFINITION_VERSION == "metrics-v1"
    assert set(DEFINITIONS) >= {
        "received",
        "open",
        "completed",
        "rejected",
        "withdrawn",
        "published_certificates",
        "overdue_obligations",
        "resolution_hours",
    }
