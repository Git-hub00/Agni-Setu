"""Certificate lifecycle admissibility (FR-24; workflow s.5 'Certificate' machine; integrations
s.8). Pure rules over the recorded administrative state and the derived effective status:
an expired record is never reinstated, a revocation is final, a supersession is final, and a
suspension applies only to a record still in force."""

from __future__ import annotations

ACTIONS = ("SUSPEND", "REINSTATE", "REVOKE", "SUPERSEDE")

_AFTER = {
    "SUSPEND": "SUSPENDED",
    "REINSTATE": "ACTIVE",
    "REVOKE": "REVOKED",
    "SUPERSEDE": "SUPERSEDED",
}


def admissible_actions(recorded_status: str, effective_status: str) -> tuple[str, ...]:
    if recorded_status in ("REVOKED", "SUPERSEDED"):
        return ()
    if effective_status == "EXPIRED":
        # Nothing brings an expired record back into force; it can still be revoked for cause
        # or superseded by a new instrument.
        return ("REVOKE", "SUPERSEDE")
    if recorded_status == "ACTIVE":
        return ("SUSPEND", "REVOKE", "SUPERSEDE")
    if recorded_status == "SUSPENDED":
        return ("REINSTATE", "REVOKE", "SUPERSEDE")
    return ()


def status_after(action: str) -> str:
    return _AFTER[action]


def requires_evidence(action: str) -> bool:
    """Adverse actions cite their basis; reinstatement and supersession cite the successor or
    the earlier instrument instead."""
    return action in ("SUSPEND", "REVOKE")
