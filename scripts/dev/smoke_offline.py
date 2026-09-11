"""Smoke-check B11 (offline package + explicit synchronisation) against a running local stack.

anita (Keycloak) requires and schedules an inspection for priya on a SCRUTINY case; priya
downloads the offline package (API-048), then synchronises a RECORD_FAILED_VISIT operation
captured "offline" (API-049): accepted once, the same manifest replays the receipt, the same id
with other content is refused, the receipt is readable (API-050) and a stale re-submission
after the attempt closed is recorded as a structured conflict; the former assignee files a
reviewed proposal (API-051) and anita resolves it (API-052).

Usage: uv run --directory backend python ../scripts/dev/smoke_offline.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import re
import sys
import uuid
from datetime import UTC, datetime, timedelta

import requests

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5173").rstrip("/")
T = 60


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def cmd(headers: dict[str, str], etag: str | None = None, key: str | None = None) -> dict[str, str]:
    h = {**headers, "Idempotency-Key": key or str(uuid.uuid4())}
    if etag:
        h["If-Match"] = etag
    return h


def keycloak_login(username: str, password: str) -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/sync"}, timeout=T, allow_redirects=False)
    page = s.get(start.headers["Location"], timeout=T)
    form_action = re.search(r'action="([^"]+)"', page.text)
    step(f"identity provider login form for {username}", form_action is not None, f"[{page.status_code}]")
    action = form_action.group(1).replace("&amp;", "&") if form_action else ""
    for cookie in s.cookies:
        if cookie.domain.startswith("localhost"):
            cookie.secure = False
    final = s.post(action, data={"username": username, "password": password, "credentialId": ""}, timeout=T, allow_redirects=True)
    step(f"{username} signed in", "error=" not in final.url, final.url)
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=T).json()["data"]["csrf_token"]
    return s, {"X-CSRFToken": token}


def next_monday_slot(hour_utc: int) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    start = datetime(monday.year, monday.month, monday.day, hour_utc, 30, tzinfo=UTC)
    return start.isoformat(), (start + timedelta(hours=2)).isoformat()


def main() -> None:
    boss, bh = keycloak_login("anita", "demo-anita-password")
    cases = boss.get(f"{BASE}/api/v1/applications", params={"status": "SCRUTINY"}, timeout=T).json()["data"]["items"]
    step("a case in SCRUTINY exists (run smoke_notices.py / smoke_submission.py first)", bool(cases), f"count={len(cases)}")
    app_id = cases[0]["application_id"]
    detail = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T)
    r = boss.post(f"{BASE}/api/v1/applications/{app_id}/require-inspection", json={"purpose": "INITIAL", "reason": "Smoke: offline package needs an open attempt"}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
    step("require-inspection (TR-05) -> attempt REQUESTED", r.status_code == 201, f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    inspection = r.json()["data"]
    roster = {o["display_name"]: o["officer_id"] for o in boss.get(f"{BASE}/api/v1/officers", timeout=T).json()["data"]["items"]}
    start, end = next_monday_slot(10)
    r = boss.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/schedule", json={"officer_id": roster["Priya Nair"], "starts_at": start, "ends_at": end, "appointment_timezone": "Asia/Kolkata", "reason": "Smoke: Priya takes the offline-package attempt", "application_version": inspection["application_version"]}, headers=cmd(bh, f'"inspection:{inspection["inspection_id"]}:v{inspection["version"]}"'), timeout=T)
    step("schedule Priya (API-041)", r.status_code == 200, f"[{r.status_code}] {r.json().get('detail', '')[:80]}")

    priya, ph = keycloak_login("priya", "demo-priya-password")
    pkg = priya.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/offline-package", timeout=T)
    step("offline package (API-048) with expiry and versions", pkg.status_code == 200 and "versions" in pkg.json()["data"] and pkg.headers.get("Cache-Control") == "no-store", f"[{pkg.status_code}] expires={pkg.json().get('data', {}).get('expires_at')}")
    package = pkg.json()["data"]
    denied = boss.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/offline-package", timeout=T)
    step("supervisor cannot download the officer package (404)", denied.status_code == 404, f"[{denied.status_code}]")
    versions = package["versions"]
    manifest = {
        "operation_id": str(uuid.uuid4()),
        "operation_type": "RECORD_FAILED_VISIT",
        "inspection_id": inspection["inspection_id"],
        "application_version": versions["application_version"],
        "base_inspection_version": versions["inspection_version"],
        "assignment_version": versions["assignment_version"],
        "schema_version": "1.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "reason_code": "SITE_INACCESSIBLE",
        "reason": "Smoke: captured offline - premises locked, caretaker absent",
    }
    etag = pkg.headers.get("ETag", "")
    old = priya.post(f"{BASE}/api/v1/sync/operations", json={**manifest, "schema_version": "0.9"}, headers=cmd(ph, etag, manifest["operation_id"]), timeout=T)
    step("unsupported client schema paused (422 SYNC_SCHEMA_UNSUPPORTED)", old.status_code == 422 and old.json().get("code") == "SYNC_SCHEMA_UNSUPPORTED", f"[{old.status_code}]")
    r = priya.post(f"{BASE}/api/v1/sync/operations", json=manifest, headers=cmd(ph, etag, manifest["operation_id"]), timeout=T)
    step("sync RECORD_FAILED_VISIT (API-049) -> receipt VISIT_OUTCOME", r.status_code == 200 and r.json()["data"]["accepted_entity_kind"] == "VISIT_OUTCOME", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    receipt = r.json()["data"]
    replay = priya.post(f"{BASE}/api/v1/sync/operations", json=manifest, headers=cmd(ph, etag, manifest["operation_id"]), timeout=T)
    step("same manifest replays the same receipt", replay.status_code == 200 and replay.json()["data"]["replayed"] is True and replay.json()["data"]["command_id"] == receipt["command_id"], f"[{replay.status_code}]")
    tampered = priya.post(f"{BASE}/api/v1/sync/operations", json={**manifest, "reason": "Smoke: edited behind the same operation id"}, headers=cmd(ph, etag, manifest["operation_id"]), timeout=T)
    step("same id with other content refused (409 SYNC_PAYLOAD_CONFLICT)", tampered.status_code == 409 and tampered.json().get("code") == "SYNC_PAYLOAD_CONFLICT", f"[{tampered.status_code}]")
    lookup = priya.get(f"{BASE}/api/v1/sync/operations/{manifest['operation_id']}", timeout=T)
    step("receipt lookup (API-050) owner-scoped", lookup.status_code == 200 and lookup.json()["data"]["state"] == "ACCEPTED" and boss.get(f"{BASE}/api/v1/sync/operations/{manifest['operation_id']}", timeout=T).status_code == 404, f"[{lookup.status_code}]")
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    step("case still INSPECTION_PENDING with FAILED + follow-up attempts", case["status"] == "INSPECTION_PENDING" and [i["status"] for i in case["inspections"]][-2:] == ["FAILED", "REQUESTED"], f"attempts={[i['status'] for i in case['inspections']]}")
    # A report captured against the now-closed attempt is a structured conflict, never a report.
    stale = {**manifest, "operation_id": str(uuid.uuid4()), "operation_type": "SUBMIT_INSPECTION_REPORT", "checklist_version": versions["checklist_version"], "observations": [{"item_code": i["code"], "result": "PASS", "note": "Smoke offline observation", "document_version_ids": []} for i in package["checklist_items"]], "summary": "Smoke: report captured offline after the visit was already recorded as failed", "declaration_accepted": True}
    for k in ("reason_code", "reason"):
        stale.pop(k)
    conflict = priya.post(f"{BASE}/api/v1/sync/operations", json=stale, headers=cmd(ph, etag, stale["operation_id"]), timeout=T)
    step("report after the failed visit -> structured conflict, recorded", conflict.status_code in (409, 412) and conflict.json().get("sync_state") == "CONFLICT", f"[{conflict.status_code}] {conflict.json().get('code')}")
    proposal = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/conflicts", json={"application_version": versions["application_version"], "operation_id": stale["operation_id"], "local_manifest": stale, "safe_local_summary": "Smoke: eight PASS observations captured on site before the failure was recorded", "reason": "Smoke: device synchronised after the attempt was closed"}, headers=cmd(ph), timeout=T)
    step("conflict proposal (API-051) recorded OPEN", proposal.status_code == 201 and proposal.json()["data"]["state"] == "OPEN", f"[{proposal.status_code}] {proposal.json().get('detail', '')[:80]}")
    listing = boss.get(f"{BASE}/api/v1/conflicts", params={"state": "OPEN"}, timeout=T).json()["data"]["items"]
    mine = next(c for c in listing if c["conflict_id"] == proposal.json()["data"]["conflict_id"])
    resolved = boss.post(f"{BASE}/api/v1/conflicts/{mine['conflict_id']}/resolve", json={"outcome": "DECLINE", "reason": "Smoke: the follow-up attempt will be scheduled; the local report is reference only"}, headers=cmd(bh, mine["etag"]), timeout=T)
    step("supervisor resolves the conflict (API-052)", resolved.status_code == 200 and resolved.json()["data"]["state"] == "RESOLVED", f"[{resolved.status_code}] {resolved.json().get('detail', '')[:80]}")
    print("ALL OFFLINE SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
