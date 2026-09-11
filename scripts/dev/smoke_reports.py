"""Smoke-check B08 (inspection reports and checklist evaluation) against a running local stack.

Uses the supervisor `anita` and the officer `priya` through the real Keycloak sign-in. Picks the
follow-up REQUESTED attempt that `smoke_inspections.py` leaves behind (or requires a visit on a
SCRUTINY case), schedules Priya, checks in, uploads evidence through the API (scanned by a
one-off demo-scanner worker pass inside the api container), saves a draft, proves the guard
rails (unauthorised NA, missing notes, foreign evidence), submits the report and shows TR-06:
COMPLETED attempt, FULFILLED assignment, case REVIEW_PENDING with a REVIEW_TASK obligation and
the deterministic evaluation (no score).

Usage: uv run --directory backend python ../scripts/dev/smoke_reports.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

import requests

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5173").rstrip("/")
T = 60
PDF = b"%PDF-1.7\n" + b"synthetic site photo placeholder " * 30 + b"\n%%EOF\n"


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


def scan_via_demo() -> str:
    run = subprocess.run(
        ["docker", "exec", "-e", "SCANNER_PROVIDER=demo_eicar", "agni-dev-api-1", "python", "manage.py", "process_jobs", "--once"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    return (run.stdout + run.stderr).strip()[-160:]


def upload_evidence(s: requests.Session, h: dict[str, str], inspection_id: str, code: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    r = s.post(
        f"{BASE}/api/v1/uploads",
        json={"target_type": "INSPECTION_EVIDENCE", "target_id": inspection_id, "original_name": f"{code}.pdf", "media_type": "application/pdf", "size_bytes": len(data), "sha256": digest, "requirement_code": code},
        headers=cmd(h),
        timeout=T,
    )
    step(f"reserve evidence upload {code} (API-033 INSPECTION_EVIDENCE)", r.status_code == 201, f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    ticket = r.json()["data"]
    put = s.put(f"{BASE}{ticket['upload_url']}", data=data, headers={**h, "Content-Type": "application/pdf"}, timeout=T)
    step(f"PUT bytes {code}", put.status_code == 200 and put.json()["data"]["sha256"] == digest, f"[{put.status_code}]")
    done = s.post(f"{BASE}/api/v1/uploads/{ticket['upload_id']}/complete", json={"sha256": digest, "size_bytes": len(data)}, headers=cmd(h, r.headers.get("ETag")), timeout=T)
    step(f"complete {code} -> QUARANTINED", done.status_code == 202 and done.json()["data"]["scan_state"] == "QUARANTINED", f"[{done.status_code}]")
    return done.json()["data"]["document_version_id"]


def main() -> None:
    boss, bh = keycloak_login("anita", "demo-anita-password")
    pending = boss.get(f"{BASE}/api/v1/inspections", params={"unassigned": "true"}, timeout=T).json()["data"]["items"]
    if pending:
        inspection = pending[0]
        step("found a REQUESTED attempt to schedule", True, f"attempt {inspection['attempt_number']} of {inspection['public_reference']}")
    else:
        cases = boss.get(f"{BASE}/api/v1/applications", params={"status": "SCRUTINY"}, timeout=T).json()["data"]["items"]
        step("a case in SCRUTINY exists (run smoke_submission.py / smoke_inspections.py first)", bool(cases), f"count={len(cases)}")
        detail = boss.get(f"{BASE}/api/v1/applications/{cases[0]['application_id']}", timeout=T)
        r = boss.post(f"{BASE}/api/v1/applications/{cases[0]['application_id']}/require-inspection", json={"purpose": "INITIAL", "reason": "Smoke: demo policy requires a site visit"}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
        step("require-inspection (TR-05)", r.status_code == 201, f"[{r.status_code}]")
        inspection = r.json()["data"]
    app_id = inspection["application_id"]
    roster = {o["display_name"]: o["officer_id"] for o in boss.get(f"{BASE}/api/v1/officers", timeout=T).json()["data"]["items"]}
    start, end = next_monday_slot(8)
    r = boss.post(
        f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/schedule",
        json={"officer_id": roster["Priya Nair"], "starts_at": start, "ends_at": end, "appointment_timezone": "Asia/Kolkata", "reason": "Smoke: Priya takes the follow-up visit", "application_version": inspection["application_version"]},
        headers=cmd(bh, f'"inspection:{inspection["inspection_id"]}:v{inspection["version"]}"'),
        timeout=T,
    )
    step("schedule Priya (API-041)", r.status_code == 200 and r.json()["data"]["status"] == "SCHEDULED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    scheduled, etag = r.json()["data"], r.headers.get("ETag", "")

    priya, ph = keycloak_login("priya", "demo-priya-password")
    detail = priya.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}", timeout=T).json()["data"]
    actions = {a["key"]: a for a in detail["allowed_actions"]}
    step("before check-in: draft allowed, submit blocked with CHECK_IN_REQUIRED", actions["save-draft"]["enabled"] and actions["submit-report"]["reason_code"] == "CHECK_IN_REQUIRED", f"{actions['submit-report']}")
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/check-in", json={"application_version": scheduled["application_version"], "assignment_version": scheduled["current_assignment"]["version"], "captured_at": datetime.now(UTC).isoformat(), "location_unavailable_reason": "GPS denied on the demo device"}, headers=cmd(ph, etag), timeout=T)
    step("Priya checks in (API-044)", r.status_code == 200 and r.json()["data"]["status"] == "IN_PROGRESS", f"[{r.status_code}]")
    etag = r.headers.get("ETag", "")
    detail = priya.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}", timeout=T).json()["data"]
    items = detail["checklist_items"]
    step("pinned checklist has the eight docs/24 items", [i["code"] for i in items] == [f"C0{n}" for n in range(1, 9)] or len(items) == 8, f"{detail['checklist_ref']} {[i['code'] for i in items]}")
    base = {"application_version": detail["application_version"], "assignment_version": detail["current_assignment"]["version"], "checklist_version": detail["checklist_ref"]}

    evidence = {code: upload_evidence(priya, ph, inspection["inspection_id"], f"inspection-{code.lower()}", PDF + code.encode()) for code in ("C01", "C02")}
    out = scan_via_demo()
    step("one-off demo-scanner worker pass inside the api container", "error" not in out.lower(), out[-100:])
    states = {code: priya.get(f"{BASE}/api/v1/documents/{doc}", timeout=T).json()["data"]["scan_state"] for code, doc in evidence.items()}
    step("evidence CLEAN after the scan", all(s == "CLEAN" for s in states.values()), f"{states}")

    def obs(code: str, result: str, note: str = "", docs: list[str] | None = None) -> dict[str, object]:
        return {"item_code": code, "result": result, "note": note, "document_version_ids": docs or []}

    draft = priya.put(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/draft", json={**base, "observations": [obs("C01", "PASS", docs=[evidence["C01"]])], "summary": "in progress", "local_revision": 1}, headers=cmd(ph, etag), timeout=T)
    step("save draft (API-045) keeps the inspection version", draft.status_code == 200 and draft.json()["data"]["inspection_version"] == detail["version"] and draft.headers.get("ETag", "").startswith('"draft:'), f"[{draft.status_code}] {draft.json().get('detail', '')[:100]}")
    again = priya.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}", timeout=T).json()["data"]
    step("draft restored on re-read", again["draft"] is not None and again["draft"]["observations"][0]["item_code"] == "C01", "")

    by_code = {i["code"]: i for i in items}
    full = [
        obs("C01", "PASS", docs=[evidence["C01"]]),
        obs("C02", "PASS", "Six extinguishers, all in date", docs=[evidence["C02"]]),
        obs("C03", "PASS", "Alarm sounded on test; detectors responded", docs=[evidence["C02"]]),
        obs("C04", "NOT_APPLICABLE", "Single-storey premises below the fire-water threshold in the demo policy") if by_code["C04"]["na_permitted"] else obs("C04", "PASS", docs=[evidence["C01"]]),
        obs("C05", "PASS", "Electrical test certificate sighted", docs=[evidence["C01"]]),
        obs("C06", "FAIL", "Two exit signs unlit; emergency lighting battery failed on test", docs=[evidence["C02"]]),
        obs("C07", "PASS", "Two access points clear"),
        obs("C08", "NOT_VERIFIED", "Training register not available at the time of the visit"),
    ]
    summary = "Escape routes and extinguishers fine; emergency lighting failed; training records not produced."
    bad = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json={**base, "observations": [obs("C01", "NOT_APPLICABLE", "not applicable in my opinion"), *full[1:]], "summary": summary, "captured_at": datetime.now(UTC).isoformat(), "declaration_accepted": True}, headers=cmd(ph, etag), timeout=T)
    step("NA on a non-permitted item refused (422)", bad.status_code == 422 and any(v["code"] == "na_not_permitted" for v in bad.json()["violations"]), f"[{bad.status_code}]")
    short = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json={**base, "observations": full[:7], "summary": summary, "captured_at": datetime.now(UTC).isoformat(), "declaration_accepted": True}, headers=cmd(ph, etag), timeout=T)
    step("incomplete observation set refused (422 missing)", short.status_code == 422 and any(v["code"] == "missing" for v in short.json()["violations"]), f"[{short.status_code}]")
    foreign = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json={**base, "observations": [obs("C01", "PASS", docs=[str(uuid.uuid4())]), *full[1:]], "summary": summary, "captured_at": datetime.now(UTC).isoformat(), "declaration_accepted": True}, headers=cmd(ph, etag), timeout=T)
    step("unknown / foreign evidence refused (422)", foreign.status_code == 422 and any(v["code"] == "not_clean_case_evidence" for v in foreign.json()["violations"]), f"[{foreign.status_code}]")

    key = str(uuid.uuid4())
    body = {**base, "observations": full, "summary": summary, "captured_at": datetime.now(UTC).isoformat(), "declaration_accepted": True, "source_operation_id": key}
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json=body, headers=cmd(ph, etag, key=key), timeout=T)
    step("submit report (API-047) -> 201 receipt", r.status_code == 201, f"[{r.status_code}] {r.json().get('detail', '')[:120]}")
    data = r.json()["data"]
    evaluation = data["report"]["evaluation"]
    step("attempt COMPLETED, case REVIEW_PENDING (TR-06)", data["status"] == "COMPLETED" and data["receipt"]["application_status"] == "REVIEW_PENDING", f"revision={data['receipt']['revision_number']} sha={data['receipt']['sha256'][:12]}")
    step("evaluation: mandatory FAIL (C06) blocks eligibility; no score", evaluation["eligible_for_review"] is False and any(b["item_code"] == "C06" and b["code"] == "MANDATORY_FAIL" for b in evaluation["blockers"]) and "score" not in evaluation, f"blockers={[b['code'] + ':' + b['item_code'] for b in evaluation['blockers']]}")
    replay = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json=body, headers=cmd(ph, etag, key=key), timeout=T)
    step("same command key replays the same receipt", replay.status_code == 201 and replay.json()["data"]["replayed"] is True and replay.json()["data"]["receipt"]["report_id"] == data["receipt"]["report_id"], f"[{replay.status_code}]")
    closed = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json=body, headers=cmd(ph, r.headers.get("ETag")), timeout=T)
    step("second report on the closed attempt refused (409)", closed.status_code == 409, f"[{closed.status_code}] {closed.json().get('code')}")

    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    obligations = {o["kind"]: o for o in case["obligations"]}
    step("supervisor view: REVIEW_TASK ACTIVE, INSPECTION_TASK SATISFIED, report blockers visible", case["status"] == "REVIEW_PENDING" and obligations["REVIEW_TASK"]["state"] == "ACTIVE" and obligations["INSPECTION_TASK"]["state"] == "SATISFIED" and any(i.get("report") and i["report"].get("eligible_for_review") is False for i in case["inspections"]), f"review due={obligations['REVIEW_TASK']['due_at']}")
    boss_view = boss.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}", timeout=T).json()["data"]
    step("supervisor reads the accepted report with evidence hashes", boss_view["report"] is not None and len(boss_view["report"]["evidence"]) >= 2 and boss_view["draft"] is None, f"evidence={len(boss_view['report']['evidence'])}")
    timeline = [e["event_type"] for e in boss.get(f"{BASE}/api/v1/applications/{app_id}/timeline", timeout=T).json()["data"]["items"]]
    step("timeline carries inspection.report_accepted.v1 (+ internal evaluated event)", "inspection.report_accepted.v1" in timeline and "inspection.report_evaluated.v1" in timeline, "")
    print("ALL REPORT SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
