"""RA-0205..0316 - every workflow command attempted by every actor that must NOT execute it is
refused (401 anonymous; 403/404 otherwise, as the object-security policy requires) and leaves no
side effect (PRODUCTION_READY_TEST.md s.12.1 `RA`; invariants 1-3).

For every API-reachable command the case is forced into a legal source state (test harness only)
so that the refusal comes from the authorization boundary, not from the state machine. The legal
actor's success path is covered by the feature suites (tests/integration).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from agni.cases.models import Application, CaseEvent
from agni.decisions.models import Decision
from agni.identity.models import Principal
from agni.notices.models import Notice
from agni.platform.clock import FrozenClock

from .test_state_command_matrix import API_COMMANDS, LEGAL_SOURCES, fire, force_state

# Which conceptual role legitimately runs each command (docs/02 s.3, docs/07 permission matrix).
LEGAL_ROLE: dict[str, str] = {
    "submit": "APPLICANT",
    "withdraw": "APPLICANT",
    "accept-report": "OFFICER",
    "start-scrutiny": "SUPERVISOR",
    "request-information": "SUPERVISOR",
    "accept-information": "SUPERVISOR",
    "require-inspection": "SUPERVISOR",
    "issue-deficiencies": "SUPERVISOR",
    "complete-corrections": "SUPERVISOR",
    "require-reinspection": "SUPERVISOR",
    "approve": "SUPERVISOR",
    "reject": "SUPERVISOR",
    "return-for-clarification": "SUPERVISOR",
}


def counts(app_id: str) -> tuple[str, int, int, int, int]:
    app = Application.objects.get(pk=app_id)
    return (
        app.status,
        app.version,
        CaseEvent.objects.filter(application_id=app_id).count(),
        Decision.objects.filter(application_id=app_id).count(),
        Notice.objects.filter(application_id=app_id).count(),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("command", API_COMMANDS)
def test_every_other_actor_is_refused_without_side_effects(
    command: str,
    visit: dict[str, Any],
    other_applicant: Principal,
    officers: dict[str, Principal],
    foreign_supervisor: Principal,
    leadership: Principal,
    governance_actors: dict[str, Principal],
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    owner, boss, priya = v["applicant"], v["boss"], v["priya"]
    anonymous = Client(enforce_csrf_checks=True)
    # Actors that must be refused for this command, by conceptual role.
    wrong: dict[str, Client] = {
        "APPLICANT_OTHER": signed_client(other_applicant),
        "OFFICER_UNASSIGNED": signed_client(officers["suresh"]),
        "OFFICER_OUTSIDE_JURISDICTION": signed_client(officers["outsider"]),
        "SUPERVISOR_FOREIGN": signed_client(foreign_supervisor),
        "LEADERSHIP": signed_client(leadership),
        "ADMIN": signed_client(governance_actors["admin"]),
        "POLICY_APPROVER": signed_client(governance_actors["approver"]),
        "PUBLIC": anonymous,
    }
    legal = LEGAL_ROLE[command]
    if legal != "APPLICANT":
        wrong["APPLICANT_OWNER"] = owner
    if legal != "OFFICER":
        wrong["OFFICER_ASSIGNED"] = priya
    if legal != "SUPERVISOR":
        wrong["SUPERVISOR_OWNER_QUEUE"] = boss

    source = sorted(LEGAL_SOURCES[command], key=lambda s: s.value)[0]
    force_state(v["app_id"], source)
    # The owner always sees the case (staff do not see DRAFTs); the version is unchanged.
    app_etag = owner.get(f"/api/v1/applications/{v['app_id']}")["ETag"]
    failures: list[str] = []
    observed: list[str] = []
    for role, client in wrong.items():
        probe = dict(v)
        # Route the command's legitimate actor slot to the wrong actor under test.
        if legal == "APPLICANT":
            probe["applicant"] = client
        elif legal == "OFFICER":
            probe["priya"] = client
        else:
            probe["boss"] = client
        before = counts(v["app_id"])
        response = fire(command, probe, app_etag=app_etag)
        after = counts(v["app_id"])
        code = response.status_code
        observed.append(f"{role}={code}")
        expected = (401, 403) if role == "PUBLIC" else (403, 404)
        if code not in expected:
            failures.append(f"{command} by {role}: HTTP {code} {response.content[:200]!r}")
        if after != before:
            failures.append(f"{command} by {role}: side effect {before} -> {after}")
        if b"Demo Warehouse" in response.content and role != "APPLICANT_OWNER":
            failures.append(f"{command} by {role}: case content disclosed")
    print(f"[RA] {command} from {source.value}:", " ".join(observed))
    assert not failures, "\n".join(failures)
