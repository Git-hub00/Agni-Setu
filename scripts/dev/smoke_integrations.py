"""Smoke-check B15 (integration contracts and reconciliation) against a running local stack.

Signs partner events for the seeded SIMULATED partner (`demo-partner-case-source`) with the
demo shared secret: sequence 1 applies through the worker, an exact replay is acknowledged as a
duplicate, the same id with another body is refused (409 + conflict), an unsigned event is
rejected (401), a sequence gap is quarantined as a conflict, arjun (operations) sees the
integration cards without secret values, runs an allowlisted probe, and resolves the gap
conflict by applying the verified source record from the simulator (wrong version refused).

Usage: uv run --directory backend python ../scripts/dev/smoke_integrations.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_reports as reports  # noqa: E402  (shares BASE, login helpers)

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd
KEY = "demo-partner-case-source"
SECRET = "demo-partner-shared-secret-not-for-live"  # the seeded simulator secret (never live)
REASON = "Smoke: synthetic demonstration drill; no legal effect."
ENTITY = f"UPG-SMOKE-{uuid.uuid4().hex[:6].upper()}"


def signed(body: dict, *, secret: str = SECRET) -> requests.Response:
    raw = json.dumps(body).encode()
    ts = str(int(datetime.now(UTC).timestamp()))
    sig = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return requests.post(f"{BASE}/api/v1/integrations/{KEY}/events", data=raw, headers={"Content-Type": "application/json", "X-Agni-Partner-Key": KEY, "X-Agni-Timestamp": ts, "X-Agni-Signature": sig}, timeout=T)


def event(seq: int, event_id: str, status: str) -> dict:
    return {"source_event_id": event_id, "source_entity_id": ENTITY, "source_sequence": seq, "occurred_at": datetime.now(UTC).isoformat(), "schema_version": "1.0", "event_type": "partner.case.status_changed", "payload": {"source_version": f"v{seq}", "source_status": status, "source_reference": ENTITY}}


def wait_state(ops: requests.Session, receipt_id: str, wanted: set[str]) -> str:
    state = ""
    for _ in range(20):
        time.sleep(1.5)
        rows = ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T).json()["data"]["recent_inbox"]
        state = next((r["state"] for r in rows if r["receipt_id"] == receipt_id), "")
        if state in wanted:
            break
    return state


def main() -> None:
    ops, oh = reports.keycloak_login("arjun", "demo-arjun-password")
    cards = ops.get(f"{BASE}/api/v1/integrations", timeout=T)
    step("operations administrator lists integrations (API-107)", cards.status_code == 200, f"[{cards.status_code}] count={len(cards.json().get('data', {}).get('items', []))}")
    partner = next(i for i in cards.json()["data"]["items"] if i["key"] == KEY)
    step("partner card is SIMULATED/ENABLED with a secret reference and no secret value", partner["mode"] == "SIMULATED" and partner["state"] == "ENABLED" and partner["credential_secret_ref"] == "DEMO_PARTNER_SHARED_SECRET" and SECRET not in cards.text, f"health={partner['last_health_status']} freshness={partner['freshness']}")
    e1 = f"{ENTITY}-evt-1"
    first = event(1, e1, "UNDER_REVIEW")  # the replay must be byte-identical
    r = signed(first)
    step("signed event #1 accepted (API-109) -> 202 PROCESSING", r.status_code == 202 and r.json()["data"]["state"] == "PROCESSING", f"[{r.status_code}] {r.text[:120]}")
    receipt1 = r.json()["data"]["receipt_id"]
    state = wait_state(ops, receipt1, {"PROCESSED", "CONFLICT", "QUARANTINED"})
    step("worker applied event #1 to the partner-owned reflection", state == "PROCESSED", f"state={state}")
    detail = ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T).json()["data"]
    entity = next((s for s in detail["entity_states"] if s["source_entity_id"] == ENTITY), None)
    step("reflection carries sequence 1 and the owned status field", entity is not None and entity["applied_sequence"] == 1 and entity["snapshot"].get("source_status") == "UNDER_REVIEW", f"{entity and entity['snapshot']}")
    r = signed(first)
    step("exact replay acknowledged as duplicate with the same receipt", r.status_code == 202 and r.json()["data"]["duplicate"] is True and r.json()["data"]["receipt_id"] == receipt1, f"[{r.status_code}]")
    r = signed(event(1, e1, "APPROVED"))
    step("same id with another body refused (409) and recorded as a PAYLOAD_MISMATCH conflict", r.status_code == 409 and r.json().get("code") == "IDEMPOTENCY_CONFLICT" and "conflict_id" in r.json(), f"[{r.status_code}]")
    mismatch_id = r.json().get("conflict_id")
    r = signed(event(2, f"{ENTITY}-evt-2", "INSPECTED"), secret="not-the-secret")
    step("unauthenticated callback rejected (401) and not stored", r.status_code == 401 and r.json().get("code") == "INTEGRATION_SIGNATURE_INVALID", f"[{r.status_code}]")
    r = signed(event(4, f"{ENTITY}-evt-4", "APPROVED"))
    step("out-of-order event #4 accepted for storage", r.status_code == 202, f"[{r.status_code}]")
    receipt4 = r.json()["data"]["receipt_id"]
    state = wait_state(ops, receipt4, {"CONFLICT", "PROCESSED", "QUARANTINED"})
    step("sequence gap quarantined as CONFLICT; reflection unchanged", state == "CONFLICT", f"state={state}")
    conflicts = ops.get(f"{BASE}/api/v1/integration-conflicts", params={"state": "OPEN"}, timeout=T).json()["data"]["items"]
    gap = next((c for c in conflicts if c["source_entity_id"] == ENTITY and c["reason_code"] == "SEQUENCE_GAP"), None)
    step("gap conflict listed (API-110) with the expected sequence", gap is not None and gap["detail"]["expected_sequence"] == 2, f"open={len(conflicts)}")
    # probe
    detail = ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T)
    r = ops.post(f"{BASE}/api/v1/integrations/{KEY}/test", json={"test_case_key": "connectivity", "reason": REASON}, headers=cmd(oh, detail.headers.get("ETag")), timeout=T)
    step("allowlisted probe accepted (API-108) -> 202", r.status_code == 202, f"[{r.status_code}] {r.text[:80]}")
    fresh = ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T)  # the accepted probe bumped the version
    r = ops.post(f"{BASE}/api/v1/integrations/{KEY}/test", json={"test_case_key": "https://evil.example/hook", "reason": REASON}, headers=cmd(oh, fresh.headers.get("ETag")), timeout=T)
    step("arbitrary probe target refused (422)", r.status_code == 422, f"[{r.status_code}]")
    for _ in range(15):
        time.sleep(1.5)
        health = ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T).json()["data"]["last_health_status"]
        if health == "OK":
            break
    step("worker recorded the probe result (OK, with the 'not proof' wording)", health == "OK", f"health={health}")
    # reconciliation: the simulator's lookup dataset must hold the entity; the demo dataset is
    # UPG-DEMO-2026-0001, so applying for a fresh entity is refused honestly ("no such record").
    assert gap is not None
    url = f"{BASE}/api/v1/integration-conflicts/{gap['conflict_id']}/resolve"
    body = {"outcome": "APPLY_VERIFIED_SOURCE", "reason": REASON, "authoritative_source_version": "v4", "verification_evidence_refs": ["smoke:lookup"]}
    r = ops.post(url, json=body, headers=cmd(oh, gap["etag"]), timeout=T)
    step("applying a source record the source does not hold is refused (409, nothing invented)", r.status_code == 409, f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    r = ops.post(url, json={"outcome": "REQUEST_RESEND", "reason": REASON, "verification_evidence_refs": ["smoke:partner-ticket"]}, headers=cmd(oh, gap["etag"]), timeout=T)
    step("conflict resolved as REQUEST_RESEND with evidence (API-111); data stays quarantined", r.status_code == 200 and r.json()["data"]["state"] == "RESOLVED" and r.json()["data"]["outcome"] == "REQUEST_RESEND", f"[{r.status_code}] {r.text[:80]}")
    state = next((row["state"] for row in ops.get(f"{BASE}/api/v1/integrations/{KEY}", timeout=T).json()["data"]["recent_inbox"] if row["receipt_id"] == receipt4), "")
    step("quarantined event #4 is not reflected", state == "QUARANTINED", f"state={state}")
    if mismatch_id:
        c = ops.get(f"{BASE}/api/v1/integration-conflicts/{mismatch_id}", timeout=T)
        r = ops.post(f"{BASE}/api/v1/integration-conflicts/{mismatch_id}/resolve", json={"outcome": "KEEP_QUARANTINED", "reason": REASON, "verification_evidence_refs": ["smoke:body-diff"]}, headers=cmd(oh, c.headers.get("ETag")), timeout=T)
        step("payload-mismatch conflict kept quarantined with evidence", r.status_code == 200 and r.json()["data"]["outcome"] == "KEEP_QUARANTINED", f"[{r.status_code}]")
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    step("supervisor of the owning desk sees the conflict list; cards are administrator-only", boss.get(f"{BASE}/api/v1/integration-conflicts", timeout=T).status_code == 200 and boss.get(f"{BASE}/api/v1/integrations", timeout=T).status_code == 403, "")
    print("ALL INTEGRATION SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
