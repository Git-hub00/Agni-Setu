"""STM-0051..0204 - every (application state x workflow command) pair that the state machine does
NOT admit is refused through the HTTP API without any side effect (PRODUCTION_READY_TEST.md
s.12.1 `STM`; invariants 8 and 9).

The legal pairs are exercised end to end by the feature suites (tests/integration). This module
forces one real case into each of the eleven states directly in the database (test harness only,
never a product path) and fires the thirteen API-reachable commands with the most privileged
legitimate actor for that command. `publish-instrument` (TR-11) is a system transition executed
by the certificate.issue job and has no HTTP command (STM rows for it are NOT_APPLICABLE at the
API; the job path is covered by tests/integration/test_decisions.py).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.domain.states import TRANSITIONS, ApplicationStatus
from agni.cases.models import Application, CaseEvent
from agni.decisions.models import Decision
from agni.identity.models import Principal
from agni.notices.models import Notice
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent
from agni.policies.models import Jurisdiction
from tests.integration.test_decisions import APPROVE, decide_grant
from tests.integration.test_notices import info_notice_body
from tests.integration.test_reports import all_pass, submit_body
from tests.integration.test_submission import cmd

JSON = "application/json"
REASON = "Production-readiness state-machine probe; synthetic demonstration data only."

LEGAL_SOURCES: dict[str, frozenset[ApplicationStatus]] = {
    command: sources for _, command, sources, _, _ in TRANSITIONS
}
API_COMMANDS: tuple[str, ...] = tuple(c for c in LEGAL_SOURCES if c != "publish-instrument")


def force_state(app_id: str, state: ApplicationStatus) -> None:
    """Test harness only: put the case into `state` without touching version or history."""
    Application.objects.filter(pk=app_id).update(status=state.value, closed_at=None)


def snapshot(app_id: str) -> dict[str, Any]:
    app = Application.objects.get(pk=app_id)
    return {
        "status": app.status,
        "version": app.version,
        "events": CaseEvent.objects.filter(application_id=app_id).count(),
        "decisions": Decision.objects.filter(application_id=app_id).count(),
        "notices": Notice.objects.filter(application_id=app_id).count(),
        "audit": AuditEvent.objects.filter(entity_id=app_id).count(),
    }


def fire(
    command: str,
    v: dict[str, Any],
    *,
    app_etag: str,
) -> Any:
    """Issue `command` through the API with its legitimate actor and a well-formed body."""
    boss: Client = v["boss"]
    applicant: Client = v["applicant"]
    priya: Client = v["priya"]
    app_id, inspection_id = v["app_id"], v["inspection_id"]
    base = f"/api/v1/applications/{app_id}"
    if command == "submit":
        return applicant.post(
            f"{base}/submit",
            data={
                "draft_revision": 1,
                "reviewed_policy_version_id": str(uuid4()),
                "declaration_acceptances": [],
                "document_version_ids": [],
            },
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "start-scrutiny":
        return boss.post(
            f"{base}/start-scrutiny",
            data={"reason": REASON},
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "request-information":
        return boss.post(
            f"{base}/notices",
            data=info_notice_body(),
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "accept-information":
        # No open information notice exists on this case: the command targets a notice id.
        notice_id = (
            Notice.objects.filter(application_id=app_id).values_list("pk", flat=True).first()
            or uuid4()
        )
        return boss.post(
            f"/api/v1/notices/{notice_id}/accept-information",
            data={"reason": REASON},
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "require-inspection":
        return boss.post(
            f"{base}/require-inspection",
            data={"purpose": "INITIAL", "reason": REASON},
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "accept-report":
        return priya.post(
            f"/api/v1/inspections/{inspection_id}/reports",
            data=submit_body(v["detail"], all_pass(str(uuid4()))),
            content_type=JSON,
            headers=cmd(etag=v["etag"]),
        )
    if command == "issue-deficiencies":
        return boss.post(
            f"{base}/notices",
            data={
                "type": "DEFICIENCY",
                "public_reason": REASON,
                "items": [
                    {
                        "code": "DEF-01",
                        "title": "Probe deficiency",
                        "description": "Probe deficiency description text.",
                        "required": True,
                        "finding_id": str(uuid4()),
                        "acceptable_evidence_types": ["PHOTOGRAPH"],
                    }
                ],
            },
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "complete-corrections":
        return boss.post(
            f"{base}/complete-corrections",
            data={"reason": REASON},
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "require-reinspection":
        return boss.post(
            f"{base}/reinspect",
            data={
                "finding_ids": [str(uuid4())],
                "reason": REASON,
                "previous_inspection_id": inspection_id,
            },
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command in ("approve", "reject"):
        return boss.post(
            f"{base}/decisions",
            data={
                **APPROVE,
                "kind": "APPROVE" if command == "approve" else "REJECT",
                "submission_revision_id": str(uuid4()),
                "report_id": str(uuid4()),
            },
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "withdraw":
        return applicant.post(
            f"{base}/withdraw",
            data={"reason": REASON},
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    if command == "return-for-clarification":
        return boss.post(
            f"{base}/return-review",
            data={
                "report_id": str(uuid4()),
                "items_requiring_clarification": [{"code": "C02", "text": "Probe clarification."}],
                "reason": REASON,
            },
            content_type=JSON,
            headers=cmd(etag=app_etag),
        )
    raise AssertionError(f"unknown command {command}")


@pytest.mark.django_db
@pytest.mark.parametrize("state", list(ApplicationStatus))
def test_illegal_commands_are_refused_from_every_state_without_side_effects(
    state: ApplicationStatus,
    visit: dict[str, Any],
    supervisor: Principal,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    # The supervisor holds decision authority so that approve/reject reach the state guard.
    decide_grant(supervisor, jurisdiction, clock)
    v["boss"] = signed_client(supervisor)
    app_etag = v["boss"].get(f"/api/v1/applications/{v['app_id']}")["ETag"]
    illegal = [c for c in API_COMMANDS if state not in LEGAL_SOURCES[c]]
    failures: list[str] = []
    observed: list[str] = []
    for command in illegal:
        force_state(v["app_id"], state)
        before = snapshot(v["app_id"])
        response = fire(command, v, app_etag=app_etag)
        after = snapshot(v["app_id"])
        code = response.status_code
        observed.append(f"{state.value}:{command}={code}")
        if not (400 <= code < 500) or code == 401:
            failures.append(f"{state.value} x {command}: HTTP {code} {response.content[:200]!r}")
        if code != 405:
            body = response.json()
            if "request_id" not in body or "code" not in body:
                failures.append(f"{state.value} x {command}: problem envelope missing {body}")
        if after != before:
            failures.append(f"{state.value} x {command}: side effect {before} -> {after}")
    print("[STM]", " ".join(observed))
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_terminal_states_admit_no_command_at_all(visit: dict[str, Any]) -> None:
    """Invariant 9: COMPLETED / REJECTED / WITHDRAWN never reopen through any HTTP command."""
    v = visit
    app_etag = v["boss"].get(f"/api/v1/applications/{v['app_id']}")["ETag"]
    for state in (
        ApplicationStatus.COMPLETED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ):
        assert not has_outgoing(state)
        for command in API_COMMANDS:
            force_state(v["app_id"], state)
            response = fire(command, v, app_etag=app_etag)
            assert 400 <= response.status_code < 500, (state, command, response.content)
            assert Application.objects.get(pk=v["app_id"]).status == state.value


def has_outgoing(state: ApplicationStatus) -> bool:
    return any(state in sources for sources in LEGAL_SOURCES.values())
