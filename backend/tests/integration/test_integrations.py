"""B15 against real PostgreSQL (AT-29): authenticated partner inbox with deduplication and
body-hash checks, ordered application per source entity (gap / older / duplicate), owned
reconciliation from a verified source lookup, allowlisted probes and scoped reads."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client

from agni.identity.models import Principal
from agni.integrations import auth
from agni.integrations.adapters import SimulatedPartnerCaseSource
from agni.integrations.models import (
    ConflictState,
    InboxState,
    Integration,
    IntegrationConflict,
    IntegrationInbox,
    IntegrationMode,
    IntegrationState,
    PartnerEntityState,
    ProviderKind,
)
from agni.platform.clock import FrozenClock
from agni.platform.models import AuditEvent, OutboxMessage
from agni.policies.models import Jurisdiction
from agni.routing.models import DutyQueue

from .test_submission import cmd
from .test_uploads import run_worker

JSON = "application/json"
ENTITY = "UPG-TEST-0001"
REASON = "Recorded during the B15 acceptance drill; synthetic demonstration data only."
SECRET_REF = "DEMO_PARTNER_SHARED_SECRET"


@pytest.fixture(autouse=True)
def _reset_simulator() -> Iterator[None]:
    SimulatedPartnerCaseSource.reset()
    yield
    SimulatedPartnerCaseSource.reset()


@pytest.fixture
def partner(db: None, duty_queue: DutyQueue) -> Integration:
    return Integration.objects.create(
        key="test-partner",
        display_name="Test partner (simulated)",
        mode=IntegrationMode.SIMULATED,
        provider_kind=ProviderKind.PARTNER_CASE_SOURCE,
        system_of_record_fields=["source_status", "source_reference", "local_reference"],
        endpoint_allowlist=["simulated://partner"],
        capabilities=["receive_event", "lookup_case"],
        credential_secret_ref=SECRET_REF,
        state=IntegrationState.ENABLED,
        owner_queue=duty_queue,
    )


def event(
    seq: int | None, *, event_id: str | None = None, version: str | None = None, **payload: Any
) -> dict[str, Any]:
    return {
        "source_event_id": event_id or f"evt-{seq}-{uuid4().hex[:6]}",
        "source_entity_id": ENTITY,
        "source_sequence": seq,
        "occurred_at": "2026-09-12T09:00:00+00:00",
        "schema_version": "1.0",
        "event_type": "partner.case.status_changed",
        "payload": {
            "source_version": version or (f"v{seq}" if seq else "v-unsequenced"),
            "source_status": payload.pop("source_status", "UNDER_REVIEW"),
            "source_reference": ENTITY,
            **payload,
        },
    }


def post_event(
    partner: Integration,
    body: dict[str, Any],
    clock: FrozenClock,
    *,
    secret: str | None = None,
    timestamp: int | None = None,
    key: str | None = None,
) -> Any:
    raw = json.dumps(body).encode("utf-8")
    ts = str(timestamp if timestamp is not None else int(clock.now().timestamp()))
    secret_value = secret or settings.INTEGRATION_DEMO_SECRETS[SECRET_REF]
    headers = {
        auth.HEADER_KEY: key or partner.key,
        auth.HEADER_TIMESTAMP: ts,
        auth.HEADER_SIGNATURE: auth.sign(secret_value, ts, raw),
    }
    return Client().post(
        f"/api/v1/integrations/{partner.key}/events", data=raw, content_type=JSON, headers=headers
    )


def state_of(partner: Integration) -> PartnerEntityState:
    return PartnerEntityState.objects.get(integration=partner, source_entity_id=ENTITY)


# ---- AT-29-01 / AT-29-02: intake, dedup, ordering ---------------------------------------------


@pytest.mark.django_db
def test_at_29_01_duplicate_event_acknowledged_without_a_second_effect(
    partner: Integration,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    first = event(1, event_id="evt-1")
    received = post_event(partner, first, clock)
    assert received.status_code == 202, received.content
    body = received.json()["data"]
    assert body["state"] == "PROCESSING" and body["duplicate"] is False
    assert received["Cache-Control"] == "no-store"
    assert IntegrationInbox.objects.filter(integration=partner).count() == 1
    report = run_worker(clock)
    assert report.completed == 1
    applied = state_of(partner)
    assert applied.applied_sequence == 1 and applied.applied_source_version == "v1"
    assert applied.snapshot == {"source_status": "UNDER_REVIEW", "source_reference": ENTITY}
    assert "secret_note" not in applied.snapshot
    assert AuditEvent.objects.filter(action="integration.event_applied").count() == 1
    # Exact replay: acknowledged with the prior receipt, no new row, no new effect.
    again = post_event(partner, first, clock)
    assert again.status_code == 202 and again.json()["data"]["duplicate"] is True
    assert again.json()["data"]["state"] == "PROCESSED"
    assert again.json()["data"]["receipt_id"] == body["receipt_id"]
    assert IntegrationInbox.objects.filter(integration=partner).count() == 1
    assert run_worker(clock).claimed == 0
    assert AuditEvent.objects.filter(action="integration.event_applied").count() == 1
    assert state_of(partner).version == applied.version
    # Same id, different body: 409 and an owned PAYLOAD_MISMATCH conflict; nothing applied.
    changed = post_event(partner, event(1, event_id="evt-1", source_status="APPROVED"), clock)
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    conflict = IntegrationConflict.objects.get(pk=changed.json()["conflict_id"])
    assert conflict.reason_code == "PAYLOAD_MISMATCH" and conflict.state == ConflictState.OPEN
    assert conflict.owner_queue_id == partner.owner_queue_id
    assert state_of(partner).snapshot["source_status"] == "UNDER_REVIEW"
    assert OutboxMessage.objects.filter(event_type="integration.conflict_detected.v1").count() == 1


@pytest.mark.django_db
def test_at_29_02_older_or_out_of_order_events_never_overwrite(
    partner: Integration,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    assert post_event(partner, event(1), clock).status_code == 202
    run_worker(clock)
    # A gap (3 after 1) is stored, acknowledged as PROCESSING, then quarantined as a conflict.
    gap = post_event(partner, event(3, source_status="APPROVED"), clock)
    assert gap.status_code == 202
    run_worker(clock)
    inbox3 = IntegrationInbox.objects.get(pk=gap.json()["data"]["receipt_id"])
    assert inbox3.state == InboxState.CONFLICT and inbox3.error_code == "SEQUENCE_GAP"
    gap_conflict = IntegrationConflict.objects.get(inbox=inbox3)
    assert gap_conflict.detail["expected_sequence"] == 2
    assert state_of(partner).applied_sequence == 1
    # The receipt now says CONFLICT, not applied success.
    assert post_event(
        partner, {**event(3), "source_event_id": inbox3.source_event_id}, clock
    ).status_code in (202, 409)
    # The missing predecessor arrives: 2 applies and releases 3 automatically.
    assert post_event(partner, event(2, source_status="INSPECTED"), clock).status_code == 202
    run_worker(clock)
    run_worker(clock)
    applied = state_of(partner)
    assert applied.applied_sequence == 3 and applied.snapshot["source_status"] == "APPROVED"
    inbox3.refresh_from_db()
    gap_conflict.refresh_from_db()
    assert inbox3.state == InboxState.PROCESSED and inbox3.disposition == "APPLIED"
    assert gap_conflict.state == ConflictState.RESOLVED
    assert gap_conflict.outcome == "PREDECESSOR_ARRIVED"
    # An older event (2 again, new id, other body) cannot overwrite the newer reflection.
    older = post_event(partner, event(2, version="v2-late", source_status="REJECTED"), clock)
    assert older.status_code == 202
    run_worker(clock)
    inbox_old = IntegrationInbox.objects.get(pk=older.json()["data"]["receipt_id"])
    assert inbox_old.state == InboxState.CONFLICT and inbox_old.error_code == "OLDER_THAN_APPLIED"
    assert state_of(partner).snapshot["source_status"] == "APPROVED"
    # An exact duplicate of the applied head is ignored without a conflict.
    dup = post_event(partner, event(3, source_status="APPROVED"), clock)
    run_worker(clock)
    assert IntegrationInbox.objects.get(pk=dup.json()["data"]["receipt_id"]).disposition == (
        "IGNORED_DUPLICATE"
    )
    # Authentication and structure are enforced before anything is stored.
    before = IntegrationInbox.objects.count()
    bad_secret = post_event(partner, event(4), clock, secret="wrong-secret")
    assert bad_secret.status_code == 401
    assert bad_secret.json()["code"] == "INTEGRATION_SIGNATURE_INVALID"
    stale = post_event(partner, event(4), clock, timestamp=int(clock.now().timestamp()) - 3600)
    assert stale.status_code == 401
    wrong_key = post_event(partner, event(4), clock, key="someone-else")
    assert wrong_key.status_code == 401
    assert IntegrationInbox.objects.count() == before
    malformed = post_event(partner, {**event(4), "source_entity_id": ""}, clock)
    assert malformed.status_code == 422 and malformed.json()["code"] == "VALIDATION_FAILED"
    unknown_type = post_event(partner, {**event(4), "event_type": "partner.unknown"}, clock)
    assert unknown_type.status_code == 422
    assert IntegrationInbox.objects.count() == before
    Integration.objects.filter(pk=partner.pk).update(state=IntegrationState.DISABLED)
    partner.refresh_from_db()
    assert post_event(partner, event(4), clock).status_code == 409
    assert Client().post(
        f"/api/v1/integrations/{partner.key}/events", data=b"{}", content_type=JSON
    ).status_code in (401, 409)
    assert (
        Client().post("/api/v1/integrations/nope/events", data=b"{}", content_type=JSON).status_code
        == 404
    )


# ---- AT-29-03 / AT-29-05: reconciliation -----------------------------------------------------


@pytest.mark.django_db
def test_at_29_03_reconciliation_applies_only_a_verified_source_record(
    partner: Integration,
    governance_actors: dict[str, Principal],
    supervisor: Principal,
    foreign_supervisor: Principal,
    applicant: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
) -> None:
    assert post_event(partner, event(1), clock).status_code == 202
    run_worker(clock)
    gap = post_event(partner, event(4, source_status="APPROVED"), clock)
    run_worker(clock)
    conflict = IntegrationConflict.objects.get(inbox_id=gap.json()["data"]["receipt_id"])
    admin = signed_client(governance_actors["admin"])
    boss = signed_client(supervisor)
    url = f"/api/v1/integration-conflicts/{conflict.pk}/resolve"
    detail = admin.get(f"/api/v1/integration-conflicts/{conflict.pk}")
    assert detail.status_code == 200 and detail.json()["data"]["reason_code"] == "SEQUENCE_GAP"
    etag = detail["ETag"]
    base = {
        "outcome": "APPLY_VERIFIED_SOURCE",
        "reason": REASON,
        "authoritative_source_version": "v4",
        "verification_evidence_refs": ["lookup:test"],
    }
    # Validation and scope.
    assert (
        admin.post(
            url,
            data={**base, "verification_evidence_refs": []},
            content_type=JSON,
            headers=cmd(etag=etag),
        ).status_code
        == 422
    )
    assert (
        admin.post(
            url,
            data={**base, "outcome": "FORCE_SUCCESS"},
            content_type=JSON,
            headers=cmd(etag=etag),
        ).status_code
        == 422
    )
    assert admin.post(url, data=base, content_type=JSON, headers=cmd()).status_code == 428
    assert (
        signed_client(applicant)
        .post(url, data=base, content_type=JSON, headers=cmd(etag=etag))
        .status_code
        == 403
    )
    assert (
        signed_client(foreign_supervisor)
        .post(url, data=base, content_type=JSON, headers=cmd(etag=etag))
        .status_code
        == 404
    )
    # The source has no record yet: nothing may be invented.
    missing = admin.post(url, data=base, content_type=JSON, headers=cmd(etag=etag))
    assert missing.status_code == 409 and "no such record" in missing.json()["detail"]
    # The source is unreachable / ambiguous: explicit, no change.
    SimulatedPartnerCaseSource.set_record(
        ENTITY,
        source_version="v4",
        sequence=4,
        payload={"source_status": "APPROVED", "source_reference": ENTITY},
    )
    SimulatedPartnerCaseSource.force_unavailable = True
    assert admin.post(url, data=base, content_type=JSON, headers=cmd(etag=etag)).status_code == 503
    SimulatedPartnerCaseSource.force_unavailable = False
    SimulatedPartnerCaseSource.force_unknown = True
    unknown = admin.post(url, data=base, content_type=JSON, headers=cmd(etag=etag))
    assert unknown.status_code == 409 and unknown.json()["code"] == "EXTERNAL_OUTCOME_UNKNOWN"
    SimulatedPartnerCaseSource.force_unknown = False
    # A cited version that the source does not confirm is refused.
    wrong = admin.post(
        url,
        data={**base, "authoritative_source_version": "v9"},
        content_type=JSON,
        headers=cmd(etag=etag),
    )
    assert wrong.status_code == 409 and wrong.json()["source_version"] == "v4"
    assert state_of(partner).applied_sequence == 1
    # The owning desk's supervisor resolves with the verified record (idempotent replay).
    key = str(uuid4())
    resolved = boss.post(url, data=base, content_type=JSON, headers=cmd(etag=etag, key=key))
    assert resolved.status_code == 200, resolved.content
    body = resolved.json()["data"]
    assert body["state"] == "RESOLVED" and body["outcome"] == "APPLY_VERIFIED_SOURCE"
    assert body["applied_sequence"] == 4
    assert body["resolution_basis"]["lookup"]["source_version"] == "v4"
    assert body["resolution_basis"]["lookup"]["provider_request_id"].startswith("sim-")
    replay = boss.post(url, data=base, content_type=JSON, headers=cmd(etag=etag, key=key))
    assert replay.status_code == 200 and replay.json()["data"]["replayed"] is True
    stale = boss.post(url, data=base, content_type=JSON, headers=cmd(etag=etag))
    assert stale.status_code in (409, 412)
    applied = state_of(partner)
    assert applied.applied_sequence == 4 and applied.snapshot["source_status"] == "APPROVED"
    assert applied.applied_event_id.startswith("lookup:")
    inbox = IntegrationInbox.objects.get(pk=gap.json()["data"]["receipt_id"])
    assert (
        inbox.state == InboxState.PROCESSED and inbox.disposition == "SUPERSEDED_BY_VERIFIED_SOURCE"
    )
    assert (
        AuditEvent.objects.filter(
            entity_type="integration_conflict",
            entity_id=conflict.pk,
            action="integration.conflict_resolved",
        ).count()
        == 1
    )
    # A later older event still cannot overwrite (2 after 4 -> OLDER_THAN_APPLIED); the
    # supervisor may ignore it as a duplicate with evidence; another jurisdiction sees nothing.
    late = post_event(partner, event(2, source_status="REJECTED"), clock)
    run_worker(clock)
    late_conflict = IntegrationConflict.objects.get(inbox_id=late.json()["data"]["receipt_id"])
    listing = boss.get("/api/v1/integration-conflicts", {"state": "OPEN"}).json()["data"]
    assert [c["conflict_id"] for c in listing["items"]] == [str(late_conflict.pk)]
    assert listing["scope"] == "JURISDICTIONS"
    assert (
        signed_client(foreign_supervisor)
        .get("/api/v1/integration-conflicts")
        .json()["data"]["items"]
        == []
    )
    assert signed_client(applicant).get("/api/v1/integration-conflicts").status_code == 403
    ignored = boss.post(
        f"/api/v1/integration-conflicts/{late_conflict.pk}/resolve",
        data={
            "outcome": "IGNORE_DUPLICATE",
            "reason": REASON,
            "verification_evidence_refs": ["partner-email:2026-09-12"],
        },
        content_type=JSON,
        headers=cmd(etag=late_conflict.etag),
    )
    assert ignored.status_code == 200 and ignored.json()["data"]["outcome"] == "IGNORE_DUPLICATE"
    assert (
        IntegrationInbox.objects.get(pk=late.json()["data"]["receipt_id"]).disposition
        == "IGNORED_DUPLICATE"
    )
    assert state_of(partner).snapshot["source_status"] == "APPROVED"


# ---- API-107 / API-108 / AT-29-04 ------------------------------------------------------------


@pytest.mark.django_db
def test_integration_list_and_probe_are_operator_only_and_never_leak_secrets(
    partner: Integration,
    governance_actors: dict[str, Principal],
    supervisor: Principal,
    signed_client: Callable[[Principal], Client],
    clock: FrozenClock,
    jurisdiction: Jurisdiction,
) -> None:
    admin = signed_client(governance_actors["admin"])
    boss = signed_client(supervisor)
    assert boss.get("/api/v1/integrations").status_code == 403
    listing = admin.get("/api/v1/integrations")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["data"]["items"] if i["key"] == partner.key)
    assert item["mode"] == "SIMULATED" and item["state"] == "ENABLED"
    assert item["credential_secret_ref"] == SECRET_REF and item["credential_configured"] is True
    assert item["freshness"] == "UNKNOWN" and item["last_health_status"] == "NOT_RUN"
    assert item["allowed_tests"] == ["connectivity", "auth", "schema"]
    assert settings.INTEGRATION_DEMO_SECRETS[SECRET_REF] not in listing.content.decode()
    detail = admin.get(f"/api/v1/integrations/{partner.pk}")
    assert detail.status_code == 200 and detail.json()["data"]["recent_inbox"] == []
    etag = detail["ETag"]
    url = f"/api/v1/integrations/{partner.key}/test"
    probe = {"test_case_key": "connectivity", "reason": REASON}
    assert boss.post(url, data=probe, content_type=JSON, headers=cmd(etag=etag)).status_code == 403
    assert (
        admin.post(
            url,
            data={**probe, "test_case_key": "delete_everything"},
            content_type=JSON,
            headers=cmd(etag=etag),
        ).status_code
        == 422
    )
    assert (
        admin.post(
            url,
            data={**probe, "test_case_key": "https://evil.example/hook"},
            content_type=JSON,
            headers=cmd(etag=etag),
        ).status_code
        == 422
    )
    accepted = admin.post(url, data=probe, content_type=JSON, headers=cmd(etag=etag))
    assert accepted.status_code == 202, accepted.content
    assert accepted.json()["data"]["state"] == "PENDING"
    run_worker(clock)
    after = admin.get(f"/api/v1/integrations/{partner.key}").json()["data"]
    assert (
        after["last_health_status"] == "OK"
        and "no partner workflow proven" in after["last_health_detail"]
    )
    assert AuditEvent.objects.filter(
        entity_type="integration", entity_id=partner.pk, action="integration.test_completed"
    ).exists()
    # An unconfigured SANDBOX adapter reports FAIL and degrades the row; nothing is fabricated.
    sandbox = Integration.objects.create(
        key="sandbox-partner",
        display_name="Sandbox partner",
        mode=IntegrationMode.SANDBOX,
        provider_kind=ProviderKind.PARTNER_CASE_SOURCE,
        credential_secret_ref="SANDBOX_PARTNER_SECRET",
        state=IntegrationState.ENABLED,
        owner_queue=partner.owner_queue,
    )
    sb_detail = admin.get(f"/api/v1/integrations/{sandbox.key}")
    accepted = admin.post(
        f"/api/v1/integrations/{sandbox.key}/test",
        data=probe,
        content_type=JSON,
        headers=cmd(etag=sb_detail["ETag"]),
    )
    assert accepted.status_code == 202
    run_worker(clock)
    sb_after = admin.get(f"/api/v1/integrations/{sandbox.key}").json()["data"]
    assert sb_after["last_health_status"] == "FAIL" and sb_after["state"] == "DEGRADED"
    # A sandbox partner without a configured secret cannot deliver events (fail closed).
    assert post_event(sandbox, event(1), clock, secret="anything").status_code == 401
    # Disabled rows refuse probes with a transition error.
    Integration.objects.filter(pk=partner.pk).update(state=IntegrationState.DISABLED)
    disabled = admin.post(
        url,
        data=probe,
        content_type=JSON,
        headers=cmd(etag=admin.get(f"/api/v1/integrations/{partner.key}")["ETag"]),
    )
    assert disabled.status_code == 409
    assert clock.now() > clock.now() - timedelta(seconds=1)
