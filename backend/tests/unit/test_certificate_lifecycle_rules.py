"""Pure admissibility rules of certificate status actions (FR-24; workflow s.5)."""

from __future__ import annotations

import pytest

from agni.certificates.domain.lifecycle import (
    ACTIONS,
    admissible_actions,
    requires_evidence,
    status_after,
)


@pytest.mark.parametrize(
    ("recorded", "effective", "expected"),
    [
        ("ACTIVE", "ACTIVE", ("SUSPEND", "REVOKE", "SUPERSEDE")),
        ("SUSPENDED", "SUSPENDED", ("REINSTATE", "REVOKE", "SUPERSEDE")),
        ("ACTIVE", "EXPIRED", ("REVOKE", "SUPERSEDE")),
        ("SUSPENDED", "EXPIRED", ("REVOKE", "SUPERSEDE")),
        ("REVOKED", "REVOKED", ()),
        ("SUPERSEDED", "SUPERSEDED", ()),
    ],
)
def test_admissible_actions_follow_the_certificate_machine(
    recorded: str, effective: str, expected: tuple[str, ...]
) -> None:
    assert admissible_actions(recorded, effective) == expected


def test_expired_and_revoked_records_are_never_reinstated() -> None:
    for recorded in ("ACTIVE", "SUSPENDED"):
        assert "REINSTATE" not in admissible_actions(recorded, "EXPIRED")
    assert admissible_actions("REVOKED", "REVOKED") == ()


def test_status_after_and_evidence_requirements() -> None:
    assert {a: status_after(a) for a in ACTIONS} == {
        "SUSPEND": "SUSPENDED",
        "REINSTATE": "ACTIVE",
        "REVOKE": "REVOKED",
        "SUPERSEDE": "SUPERSEDED",
    }
    assert requires_evidence("SUSPEND") and requires_evidence("REVOKE")
    assert not requires_evidence("REINSTATE") and not requires_evidence("SUPERSEDE")
