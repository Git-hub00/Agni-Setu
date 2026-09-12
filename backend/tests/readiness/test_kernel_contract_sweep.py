"""KRN-0317..0844 - the command-kernel contract across the API surface (PRODUCTION_READY_TEST.md
s.12.1 `KRN`; invariants 4-7): anonymous callers never reach a handler, a missing idempotency key
is a malformed request, versioned targets demand a current `If-Match` (428) and refuse a stale
one (412), same key + same body replays, same key + different body conflicts.

Command-specific success paths live in the feature suites; this sweep asserts that the shared
contract holds uniformly on every reachable command endpoint with its legitimate actor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Application, CaseEvent, Premises
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.platform.models import CommandReceipt
from agni.policies.models import Jurisdiction, Service
from tests.integration.test_decisions import APPROVE, decide_grant
from tests.integration.test_drafts import create_draft
from tests.integration.test_notices import info_notice_body
from tests.integration.test_premises_api import VALID as VALID_PREMISES
from tests.integration.test_reports import all_pass, submit_body
from tests.integration.test_submission import cmd

JSON = "application/json"
REASON = "Production-readiness kernel contract probe; synthetic demonstration data only."
STALE = '"probe:00000000-0000-0000-0000-000000000000:v999"'


def versioned_commands(
    v: dict[str, Any], premises_id: str
) -> list[tuple[str, str, str, str, dict[str, Any], str]]:
    """(label, actor slot, method, path, body, etag slot) per command with a versioned target."""
    app, insp = v["app_id"], v["inspection_id"]
    a = f"/api/v1/applications/{app}"
    i = f"/api/v1/inspections/{insp}"
    return [
        (
            "application-draft-update",
            "applicant",
            "patch",
            f"{a}/draft",
            {"draft_revision": 1, "fields": {}},
            "app",
        ),
        (
            "application-submit",
            "applicant",
            "post",
            f"{a}/submit",
            {
                "draft_revision": 1,
                "reviewed_policy_version_id": str(uuid4()),
                "declaration_acceptances": [],
                "document_version_ids": [],
            },
            "app",
        ),
        ("application-withdraw", "applicant", "post", f"{a}/withdraw", {"reason": REASON}, "app"),
        ("start-scrutiny", "boss", "post", f"{a}/start-scrutiny", {"reason": REASON}, "app"),
        (
            "resolve-routing",
            "boss",
            "post",
            f"{a}/resolve-routing",
            {"reason": REASON, "target_queue_key": "demo-central-review"},
            "app",
        ),
        (
            "require-inspection",
            "boss",
            "post",
            f"{a}/require-inspection",
            {"purpose": "INITIAL", "reason": REASON},
            "app",
        ),
        (
            "place-hold",
            "boss",
            "post",
            f"{a}/holds",
            {"kind": "ADMINISTRATIVE", "reason": REASON},
            "app",
        ),
        ("notice-information-publish", "boss", "post", f"{a}/notices", info_notice_body(), "app"),
        (
            "complete-corrections",
            "boss",
            "post",
            f"{a}/complete-corrections",
            {"reason": REASON},
            "app",
        ),
        (
            "require-reinspection",
            "boss",
            "post",
            f"{a}/reinspect",
            {"finding_ids": [str(uuid4())], "reason": REASON, "previous_inspection_id": insp},
            "app",
        ),
        (
            "return-for-clarification",
            "boss",
            "post",
            f"{a}/return-review",
            {
                "report_id": str(uuid4()),
                "items_requiring_clarification": [{"code": "C02", "text": "Probe."}],
                "reason": REASON,
            },
            "app",
        ),
        (
            "decision-record",
            "boss",
            "post",
            f"{a}/decisions",
            {**APPROVE, "submission_revision_id": str(uuid4()), "report_id": str(uuid4())},
            "app",
        ),
        (
            "inspection-schedule",
            "boss",
            "post",
            f"{i}/schedule",
            {
                "officer_id": str(uuid4()),
                "starts_at": "2026-09-15T04:30:00+00:00",
                "ends_at": "2026-09-15T06:30:00+00:00",
                "appointment_timezone": "Asia/Kolkata",
                "reason": REASON,
                "application_version": 1,
            },
            "insp",
        ),
        (
            "inspection-reassign",
            "boss",
            "post",
            f"{i}/reassign",
            {"new_officer_id": str(uuid4()), "reason": REASON, "application_version": 1},
            "insp",
        ),
        (
            "inspection-cancel",
            "boss",
            "post",
            f"{i}/cancel",
            {"reason": REASON, "application_version": 1},
            "insp",
        ),
        (
            "inspection-check-in",
            "priya",
            "post",
            f"{i}/check-in",
            {
                "application_version": 1,
                "assignment_version": 1,
                "captured_at": "2026-09-14T04:32:00+00:00",
                "location_unavailable_reason": "probe",
            },
            "insp",
        ),
        (
            "inspection-fail-visit",
            "priya",
            "post",
            f"{i}/fail-visit",
            {
                "application_version": 1,
                "assignment_version": 1,
                "reason_code": "OTHER",
                "reason": REASON,
                "captured_at": "2026-09-14T04:40:00+00:00",
            },
            "insp",
        ),
        (
            "inspection-draft-save",
            "priya",
            "put",
            f"{i}/draft",
            {
                "application_version": 1,
                "assignment_version": 1,
                "checklist_version": v["detail"]["checklist_ref"],
                "observations": [],
                "summary": "probe",
                "local_revision": 1,
            },
            "insp",
        ),
        (
            "inspection-report-submit",
            "priya",
            "post",
            f"{i}/reports",
            submit_body(v["detail"], all_pass(str(uuid4()))),
            "insp",
        ),
        (
            "premises-update",
            "applicant",
            "patch",
            f"/api/v1/premises/{premises_id}",
            {"display_name": "Probe name"},
            "premises",
        ),
    ]


def creation_commands(
    app_id: str, draft_id: str
) -> list[tuple[str, str, str, dict[str, Any], dict[str, Any]]]:
    """(label, actor slot, path, body, different body) for commands that create a resource."""
    return [
        (
            "premises-create",
            "applicant",
            "/api/v1/premises",
            VALID_PREMISES,
            {**VALID_PREMISES, "display_name": "Other"},
        ),
        (
            "support-ticket-create",
            "applicant",
            "/api/v1/tickets",
            {
                "category": "TECHNICAL",
                "subject": "Kernel contract probe ticket",
                "description": "The probe opens one ticket and replays it.",
                "application_id": app_id,
            },
            {
                "category": "TECHNICAL",
                "subject": "Kernel contract probe ticket B",
                "description": "The probe opens one ticket and replays it.",
                "application_id": app_id,
            },
        ),
        (
            "export-request",
            "boss",
            "/api/v1/exports",
            {"kind": "CASES", "field_set_key": "case-summary", "purpose": REASON},
            {"kind": "CASES", "field_set_key": "case-summary", "purpose": REASON + " changed"},
        ),
        (
            "upload-reserve",
            "applicant",
            "/api/v1/uploads",
            {
                "target_type": "APPLICATION_DRAFT",
                "target_id": draft_id,
                "original_name": "probe.pdf",
                "media_type": "application/pdf",
                "size_bytes": 10,
                "requirement_code": "plan",
            },
            {
                "target_type": "APPLICATION_DRAFT",
                "target_id": draft_id,
                "original_name": "probe2.pdf",
                "media_type": "application/pdf",
                "size_bytes": 10,
                "requirement_code": "plan",
            },
        ),
    ]


def _send(
    client: Client, method: str, path: str, body: dict[str, Any], headers: dict[str, str]
) -> Any:
    return getattr(client, method)(path, data=body, content_type=JSON, headers=headers)


@pytest.mark.django_db
def test_versioned_commands_share_the_kernel_contract(
    visit: dict[str, Any],
    premises: Premises,
    supervisor: Principal,
    jurisdiction: Jurisdiction,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    v = visit
    decide_grant(supervisor, jurisdiction, clock)
    v["boss"] = signed_client(supervisor)
    anonymous = Client(enforce_csrf_checks=True)
    etags = {
        "app": v["boss"].get(f"/api/v1/applications/{v['app_id']}")["ETag"],
        "insp": v["etag"],
        "premises": v["applicant"].get(f"/api/v1/premises/{premises.pk}")["ETag"],
    }
    before_version = Application.objects.get(pk=v["app_id"]).version
    before_events = CaseEvent.objects.filter(application_id=v["app_id"]).count()
    failures: list[str] = []
    for label, slot, method, path, body, etag_slot in versioned_commands(v, str(premises.pk)):
        client: Client = v[slot]
        # 1. anonymous -> 401 (CSRF-less anonymous requests are refused before any handler)
        r = _send(anonymous, method, path, body, {})
        if r.status_code not in (401, 403):
            failures.append(f"{label}: anonymous HTTP {r.status_code}")
        # 2. missing Idempotency-Key -> 400 MALFORMED_REQUEST
        r = _send(client, method, path, body, {"If-Match": etags[etag_slot]})
        if not (r.status_code == 400 and r.json().get("code") == "MALFORMED_REQUEST"):
            failures.append(f"{label}: missing key HTTP {r.status_code} {r.content[:160]!r}")
        # 3. missing If-Match -> 428 PRECONDITION_REQUIRED
        r = _send(client, method, path, body, cmd())
        if not (r.status_code == 428 and r.json().get("code") == "PRECONDITION_REQUIRED"):
            failures.append(f"{label}: missing If-Match HTTP {r.status_code} {r.content[:160]!r}")
        # 4. stale If-Match -> 412 VERSION_CONFLICT
        r = _send(client, method, path, body, cmd(etag=STALE))
        if not (r.status_code == 412 and r.json().get("code") == "VERSION_CONFLICT"):
            failures.append(f"{label}: stale If-Match HTTP {r.status_code} {r.content[:160]!r}")
    # Nothing above may have changed the case.
    assert Application.objects.get(pk=v["app_id"]).version == before_version
    assert CaseEvent.objects.filter(application_id=v["app_id"]).count() == before_events
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_creation_commands_replay_and_conflict_on_the_same_key(
    visit: dict[str, Any], premises: Premises, service: Service
) -> None:
    v = visit
    anonymous = Client(enforce_csrf_checks=True)
    failures: list[str] = []
    # Upload reservations belong to a DRAFT case; the submitted `visit` case anchors the rest.
    draft_id = create_draft(v["applicant"], premises, service).json()["data"]["application_id"]
    for label, slot, path, body, different in creation_commands(v["app_id"], draft_id):
        client: Client = v[slot]
        r = anonymous.post(path, data=body, content_type=JSON)
        if r.status_code not in (401, 403):
            failures.append(f"{label}: anonymous HTTP {r.status_code}")
        r = client.post(path, data=body, content_type=JSON)
        if not (r.status_code == 400 and r.json().get("code") == "MALFORMED_REQUEST"):
            failures.append(f"{label}: missing key HTTP {r.status_code} {r.content[:160]!r}")
        key = str(uuid4())
        receipts = CommandReceipt.objects.count()
        first = client.post(path, data=body, content_type=JSON, headers=cmd(key=key))
        if first.status_code not in (201, 202):
            failures.append(f"{label}: first call HTTP {first.status_code} {first.content[:200]!r}")
            continue
        replay = client.post(path, data=body, content_type=JSON, headers=cmd(key=key))
        if not (
            replay.status_code == first.status_code
            and replay.json()["data"].get("replayed") is True
            and replay.json()["data"].get("command_id") == first.json()["data"].get("command_id")
        ):
            failures.append(f"{label}: replay HTTP {replay.status_code} {replay.content[:200]!r}")
        if CommandReceipt.objects.count() != receipts + 1:
            failures.append(f"{label}: replay created a second receipt")
        conflict = client.post(path, data=different, content_type=JSON, headers=cmd(key=key))
        if not (
            conflict.status_code == 409 and conflict.json().get("code") == "IDEMPOTENCY_CONFLICT"
        ):
            failures.append(
                f"{label}: conflict HTTP {conflict.status_code} {conflict.content[:200]!r}"
            )
    assert not failures, "\n".join(failures)
