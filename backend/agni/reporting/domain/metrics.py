"""Pure reporting rules (FR-25/FR-26): metric definitions with their version, the stage-at-cutoff
rule, nearest-rank percentiles and spreadsheet-formula neutralisation for exported cells."""

from __future__ import annotations

import math
from datetime import datetime

DEFINITION_VERSION = "metrics-v1"
TERMINAL = ("COMPLETED", "REJECTED", "WITHDRAWN")
MIN_SAMPLE = 5

DEFINITIONS: dict[str, str] = {
    "received": (
        "Applications with a receipt (submitted_at) at or before the cutoff. Drafts are never "
        "counted."
    ),
    "open": (
        "Received applications whose stage at the cutoff is not COMPLETED, REJECTED or WITHDRAWN."
    ),
    "completed": "Received applications in COMPLETED at the cutoff (a certificate was published).",
    "rejected": "Received applications in REJECTED at the cutoff (a final decision).",
    "withdrawn": "Received applications withdrawn at or before the cutoff.",
    "published_certificates": (
        "Certificates with issued_at at or before the cutoff for the same population."
    ),
    "overdue_obligations": (
        "Obligations of the population still ACTIVE or PAUSED whose due time passed before "
        "the cutoff (business overdue work, not infrastructure failure)."
    ),
    "resolution_hours": (
        "Hours from receipt to the terminal stage (COMPLETED or REJECTED) for cases closed by "
        f"the cutoff; median and P90 over the sample. Fewer than {MIN_SAMPLE} closed cases are "
        "marked insufficient and support no performance claim."
    ),
}


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100) over a non-empty list; None for an empty one."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def state_at(stages: list[tuple[str, datetime, datetime | None]], as_of: datetime) -> str | None:
    """The stage in force at `as_of`: entered at or before the cutoff and not yet exited (or
    exited after it). With several candidates the latest entry wins."""
    best: tuple[str, datetime, bool] | None = None
    for state, entered_at, exited_at in stages:
        if entered_at > as_of:
            continue
        if exited_at is not None and exited_at <= as_of:
            continue
        # Ties on entered_at (same-instant transitions) resolve to the stage still open.
        key = (entered_at, exited_at is None)
        if best is None or key > (best[1], best[2]):
            best = (state, entered_at, exited_at is None)
    return best[0] if best else None


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection: a cell starting with =, +, -, @, tab or CR is
    prefixed with an apostrophe so it is read as text (security s.8 'formula neutralization')."""
    text = "" if value is None else str(value)
    if text and text[0] in FORMULA_PREFIXES:
        return "'" + text
    return text
