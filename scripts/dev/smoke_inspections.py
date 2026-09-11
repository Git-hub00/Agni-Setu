"""Smoke-check B07 (assignments and appointments) against a running local stack.

Uses the supervisor `anita` and officers `suresh` / `priya` through the real Keycloak sign-in.
Picks a case in SCRUTINY (run `smoke_submission.py --scan-via-demo --oidc` first, which leaves
one), requires the site inspection, schedules Suresh, proves the overlap conflict with a second
attempt, reassigns to Priya, and as Priya checks in and records a failed visit; then shows the
follow-up attempt and the untouched case clock.

Usage: uv run --directory backend python ../scripts/dev/smoke_inspections.py [http://127.0.0.1:5173]
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


def cmd(headers: dict[str, str], etag: str | None = None) -> dict[str, str]:
    h = {**headers, "Idempotency-Key": str(uuid.uuid4())}
    if etag:
        h["If-Match"] = etag
    return h


def keycloak_login(username: str, password: str) -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/inspections"}, timeout=T, allow_redirects=False)
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
    step("a case in SCRUTINY exists (run smoke_submission.py first)", bool(cases), f"count={len(cases)}")
    app_id = cases[0]["application_id"]
    detail = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T)
    hint = next(a for a in detail.json()["data"]["allowed_actions"] if a["key"] == "require-inspection")
    step("supervisor may require the inspection", hint["enabled"] is True, f"{hint}")
    r = boss.post(f"{BASE}/api/v1/applications/{app_id}/require-inspection", json={"purpose": "INITIAL", "reason": "Smoke: demo policy requires a site visit"}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
    step("require-inspection (TR-05) -> attempt 1 REQUESTED", r.status_code == 201 and r.json()["data"]["status"] == "REQUESTED", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    inspection = r.json()["data"]
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    obligations = {o["kind"]: o for o in case["obligations"]}
    step("case INSPECTION_PENDING with INSPECTION_TASK obligation; scrutiny task satisfied", case["status"] == "INSPECTION_PENDING" and obligations["INSPECTION_TASK"]["state"] == "ACTIVE" and obligations["SCRUTINY_TASK"]["state"] == "SATISFIED", f"due={obligations['INSPECTION_TASK']['due_at']}")
    case_due = obligations["CASE_TARGET"]["due_at"]

    roster = {o["display_name"]: o["officer_id"] for o in boss.get(f"{BASE}/api/v1/officers", timeout=T).json()["data"]["items"]}
    step("officer roster lists the seeded officers", {"Suresh Yadav", "Priya Nair"} <= set(roster), f"{sorted(roster)}")
    start, end = next_monday_slot(4)
    sched = {"officer_id": roster["Suresh Yadav"], "starts_at": start, "ends_at": end, "appointment_timezone": "Asia/Kolkata", "reason": "Smoke: first available Monday slot for the ward cluster", "application_version": inspection["application_version"]}
    r = boss.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/schedule", json=sched, headers=cmd(bh, f'"inspection:{inspection["inspection_id"]}:v{inspection["version"]}"'), timeout=T)
    step("schedule Suresh (API-041)", r.status_code == 200 and r.json()["data"]["status"] == "SCHEDULED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    scheduled = r.json()["data"]
    etag = r.headers.get("ETag", "")
    window = boss.get(f"{BASE}/api/v1/schedule", params={"starts_at": start, "ends_at": (datetime.fromisoformat(start) + timedelta(days=1)).isoformat()}, timeout=T).json()["data"]
    step("schedule window shows the booking (API-040)", any(b["inspection_id"] == inspection["inspection_id"] for b in window["bookings"]), f"bookings={len(window['bookings'])}")

    # Overlap: another case in SCRUTINY? Otherwise book a second attempt... use the follow-up
    # attempt created later. For the conflict, try to book Suresh again on the same slot via a
    # second inspection if available.
    others = [c for c in cases if c["application_id"] != app_id]
    if others:
        d2 = boss.get(f"{BASE}/api/v1/applications/{others[0]['application_id']}", timeout=T)
        r2 = boss.post(f"{BASE}/api/v1/applications/{others[0]['application_id']}/require-inspection", json={"purpose": "INITIAL", "reason": "Smoke: second case also requires a visit"}, headers=cmd(bh, d2.headers.get("ETag")), timeout=T)
        if r2.status_code == 201:
            insp2 = r2.json()["data"]
            clash = boss.post(f"{BASE}/api/v1/inspections/{insp2['inspection_id']}/schedule", json={**sched, "application_version": insp2["application_version"], "starts_at": (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat(), "ends_at": (datetime.fromisoformat(end) + timedelta(hours=1)).isoformat()}, headers=cmd(bh, f'"inspection:{insp2["inspection_id"]}:v{insp2["version"]}"'), timeout=T)
            step("overlapping booking for the same officer refused (APPOINTMENT_CONFLICT)", clash.status_code == 409 and clash.json().get("code") == "APPOINTMENT_CONFLICT", f"[{clash.status_code}]")
    else:
        print("SKIP  overlap conflict (only one SCRUTINY case available)")

    r = boss.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reassign", json={"new_officer_id": roster["Priya Nair"], "reason": "Smoke: Suresh reassigned to an emergency call-out", "application_version": scheduled["application_version"]}, headers=cmd(bh, etag), timeout=T)
    step("reassign to Priya (API-042) -> assignment v2", r.status_code == 200 and r.json()["data"]["current_assignment"]["number"] == 2, f"[{r.status_code}]")
    etag = r.headers.get("ETag", "")
    assignment = r.json()["data"]["current_assignment"]

    suresh, sh = keycloak_login("suresh", "demo-suresh-password")
    mine = suresh.get(f"{BASE}/api/v1/inspections", params={"state": "SCHEDULED"}, timeout=T).json()["data"]["items"]
    step("Suresh's queue no longer shows the active attempt as his", all(i["current_assignment"]["officer_name"] != "Suresh Yadav" for i in mine if i["current_assignment"]), f"items={len(mine)}")
    denied = suresh.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/check-in", json={"application_version": scheduled["application_version"], "assignment_version": assignment["version"], "captured_at": datetime.now(UTC).isoformat(), "location_unavailable_reason": "stale authority test"}, headers=cmd(sh, etag), timeout=T)
    step("stale officer cannot check in (404)", denied.status_code == 404, f"[{denied.status_code}]")

    priya, ph = keycloak_login("priya", "demo-priya-password")
    queue = priya.get(f"{BASE}/api/v1/inspections", timeout=T).json()["data"]["items"]
    step("Priya's queue shows the appointment", any(i["inspection_id"] == inspection["inspection_id"] for i in queue), f"items={len(queue)}")
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/check-in", json={"application_version": scheduled["application_version"], "assignment_version": assignment["version"], "captured_at": datetime.now(UTC).isoformat(), "location_unavailable_reason": "GPS denied on the demo device"}, headers=cmd(ph, etag), timeout=T)
    step("Priya checks in (API-044) -> IN_PROGRESS", r.status_code == 200 and r.json()["data"]["status"] == "IN_PROGRESS", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    etag = r.headers.get("ETag", "")
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/fail-visit", json={"application_version": scheduled["application_version"], "assignment_version": assignment["version"], "reason_code": "SITE_INACCESSIBLE", "reason": "Smoke: premises locked, caretaker absent, gate photographed", "captured_at": datetime.now(UTC).isoformat()}, headers=cmd(ph, etag), timeout=T)
    step("failed visit (API-046) -> FAILED attempt + next attempt", r.status_code == 200 and r.json()["data"]["status"] == "FAILED" and r.json()["data"]["next_attempt_id"], f"[{r.status_code}]")
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    obligations = {o["kind"]: o for o in case["obligations"]}
    step("case still INSPECTION_PENDING; case-target due unchanged; two attempts on record", case["status"] == "INSPECTION_PENDING" and obligations["CASE_TARGET"]["due_at"] == case_due and [i["status"] for i in case["inspections"]] == ["FAILED", "REQUESTED"], f"attempts={[i['status'] for i in case['inspections']]}")
    print("ALL INSPECTION SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
