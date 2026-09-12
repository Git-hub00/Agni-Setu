"""Smoke-check B12 (guarded decision, issuance, registry, public verification) against a running
local stack.

anita (Keycloak, supervisor with the seeded `case.decide` grant) schedules Priya on an unassigned
REQUESTED attempt; Priya checks in, uploads evidence (scanned by a one-off demo-scanner pass in
the api container) and submits an all-PASS report -> REVIEW_PENDING. anita reads the decision
readiness (API-064), proves the guard rails, approves (API-065, TR-10) -> APPROVED_PENDING_ISSUE
with a reserved number; a one-off worker pass in the api container renders the real WeasyPrint
sample PDF, obtains the demo-watermark receipt and publishes (TR-11) -> COMPLETED; the register
(API-067/068), the ticketed artifact download (API-069) and the anonymous public verification
(API-073, token and demo number lookup, unknown -> 404) are checked through nginx.

Usage: uv run --directory backend python ../scripts/dev/smoke_decisions.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_reports as reports  # noqa: E402  (shares BASE, login, evidence upload, scan pass)

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd


def worker_pass() -> str:
    run = subprocess.run(
        ["docker", "exec", "agni-dev-api-1", "python", "manage.py", "process_jobs", "--once"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return (run.stdout + run.stderr).strip()[-200:]


def wait_for_publication(boss: requests.Session, app_id: str, seconds: int = 120) -> dict[str, object]:
    """The LIVE worker may already hold the certificate.issue claim when the one-off pass runs
    (two legitimate workers, one lease); poll the case until TR-11 lands or the issuance settles
    in a state that will not publish, so the assertion judges the outcome, not the race."""
    deadline = time.monotonic() + seconds
    while True:
        detail: dict[str, object] = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
        issuance = detail.get("issuance") or {}
        state = issuance.get("state") if isinstance(issuance, dict) else None
        if detail.get("status") == "COMPLETED" or state in ("FAILED", "RECONCILIATION_REQUIRED") or time.monotonic() > deadline:
            return detail
        time.sleep(3)


def obs(code: str, result: str, note: str = "", docs: list[str] | None = None) -> dict[str, object]:
    return {"item_code": code, "result": result, "note": note, "document_version_ids": docs or []}


def eligible_review_case(boss: requests.Session) -> dict[str, object] | None:
    for case in boss.get(f"{BASE}/api/v1/applications", params={"status": "REVIEW_PENDING"}, timeout=T).json()["data"]["items"]:
        detail = boss.get(f"{BASE}/api/v1/applications/{case['application_id']}", timeout=T).json()["data"]
        reports_ = [i.get("report") for i in detail["inspections"] if i.get("report")]
        if reports_ and reports_[-1].get("eligible_for_review") is True and detail.get("decision") is None:
            return detail
    return None


def produce_eligible_case(boss: requests.Session, bh: dict[str, str]) -> str:
    pending = boss.get(f"{BASE}/api/v1/inspections", params={"unassigned": "true"}, timeout=T).json()["data"]["items"]
    step("an unassigned REQUESTED attempt exists (run smoke_offline.py / smoke_inspections.py first)", bool(pending), f"count={len(pending)}")
    inspection = pending[0]
    roster = {o["display_name"]: o["officer_id"] for o in boss.get(f"{BASE}/api/v1/officers", timeout=T).json()["data"]["items"]}
    start, end = reports.next_monday_slot(12)
    r = boss.post(
        f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/schedule",
        json={"officer_id": roster["Priya Nair"], "starts_at": start, "ends_at": end, "appointment_timezone": "Asia/Kolkata", "reason": "Smoke: Priya takes the decision-drill visit", "application_version": inspection["application_version"]},
        headers=cmd(bh, f'"inspection:{inspection["inspection_id"]}:v{inspection["version"]}"'),
        timeout=T,
    )
    step("schedule Priya (API-041)", r.status_code == 200, f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    scheduled, etag = r.json()["data"], r.headers.get("ETag", "")
    priya, ph = reports.keycloak_login("priya", "demo-priya-password")
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/check-in", json={"application_version": scheduled["application_version"], "assignment_version": scheduled["current_assignment"]["version"], "captured_at": datetime.now(UTC).isoformat(), "location_unavailable_reason": "GPS denied on the demo device"}, headers=cmd(ph, etag), timeout=T)
    step("Priya checks in (API-044)", r.status_code == 200, f"[{r.status_code}]")
    etag = r.headers.get("ETag", "")
    detail = priya.get(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}", timeout=T).json()["data"]
    items = {i["code"]: i for i in detail["checklist_items"]}
    base = {"application_version": detail["application_version"], "assignment_version": detail["current_assignment"]["version"], "checklist_version": detail["checklist_ref"]}
    evidence = {code: reports.upload_evidence(priya, ph, inspection["inspection_id"], f"inspection-{code.lower()}", reports.PDF + code.encode()) for code in ("C01", "C02")}
    out = reports.scan_via_demo()
    step("one-off demo-scanner worker pass", "error" not in out.lower(), out[-100:])
    doc = evidence["C01"]
    observations = [
        obs(code, "NOT_APPLICABLE", "Not applicable to this demonstration premises per the pinned checklist") if code == "C04" and item["na_permitted"] else obs(code, "PASS", "Verified on site during the decision drill", docs=[doc] if item["evidence_required"] else [])
        for code, item in items.items()
    ]
    body = {**base, "observations": observations, "summary": "All checklist items verified on site; no deficiencies recorded.", "captured_at": datetime.now(UTC).isoformat(), "declaration_accepted": True}
    r = priya.post(f"{BASE}/api/v1/inspections/{inspection['inspection_id']}/reports", json=body, headers=cmd(ph, etag), timeout=T)
    step("Priya submits an all-PASS report (API-047) -> REVIEW_PENDING", r.status_code == 201 and r.json()["data"]["report"]["evaluation"]["eligible_for_review"] is True, f"[{r.status_code}] {r.json().get('detail', '')[:120]}")
    return str(inspection["application_id"])


def main() -> None:
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    case = eligible_review_case(boss)
    app_id = str(case["application_id"]) if case else produce_eligible_case(boss, bh)
    detail_resp = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T)
    detail, etag = detail_resp.json()["data"], detail_resp.headers.get("ETag", "")
    step("case REVIEW_PENDING with an eligible accepted report", detail["status"] == "REVIEW_PENDING", detail["public_reference"])

    ready = boss.get(f"{BASE}/api/v1/applications/{app_id}/decision-readiness", timeout=T)
    step("decision readiness (API-064) - approve and reject available with the seeded grant", ready.status_code == 200 and ready.json()["data"]["approve"]["eligible"] is True and ready.json()["data"]["reject"]["eligible"] is True and ready.headers.get("Cache-Control") == "no-store", f"[{ready.status_code}] approve={ready.json().get('data', {}).get('approve')}")
    evidence = ready.json()["data"]["evidence"]
    payload = {"kind": "APPROVE", "submission_revision_id": evidence["submission_revision_id"], "report_id": evidence["report_id"], "reason": "Smoke: reviewed the submitted record and the all-PASS accepted report; nothing outstanding.", "public_reason": "The demonstration review is complete. Sample certificate processing has started.", "review_acknowledged": True}
    url = f"{BASE}/api/v1/applications/{app_id}/decisions"
    r = boss.post(url, json={**payload, "review_acknowledged": False}, headers=cmd(bh, etag), timeout=T)
    step("no explicit acknowledgment -> 422", r.status_code == 422, f"[{r.status_code}]")
    r = boss.post(url, json={**payload, "submission_revision_id": str(uuid.uuid4())}, headers=cmd(bh, etag), timeout=T)
    step("stale evidence -> 412 VERSION_CONFLICT (changed=submission_revision)", r.status_code == 412 and r.json().get("code") == "VERSION_CONFLICT" and r.json().get("changed") == "submission_revision", f"[{r.status_code}]")
    r = boss.post(url, json={**payload, "status": "COMPLETED"}, headers=cmd(bh, etag), timeout=T)
    step("caller-specified status refused (422 unknown field)", r.status_code == 422, f"[{r.status_code}]")
    key = str(uuid.uuid4())
    r = boss.post(url, json=payload, headers=cmd(bh, etag, key), timeout=T)
    step("approve (API-065, TR-10) -> 201 APPROVED_PENDING_ISSUE with a reserved number", r.status_code == 201 and r.json()["data"]["status"] == "APPROVED_PENDING_ISSUE" and r.json()["data"]["issuance"]["state"] == "READY", f"[{r.status_code}] {r.json().get('detail', '')[:120]}")
    receipt = r.json()["data"]
    number = receipt["issuance"]["certificate_number"]
    replay = boss.post(url, json=payload, headers=cmd(bh, etag, key), timeout=T)
    step("same key replays the same decision", replay.status_code == 201 and replay.json()["data"]["replayed"] is True and replay.json()["data"]["decision_id"] == receipt["decision_id"], f"[{replay.status_code}]")
    fresh_etag = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).headers.get("ETag", "")
    twice = boss.post(url, json=payload, headers=cmd(bh, fresh_etag), timeout=T)
    step("a second decision is refused (409)", twice.status_code == 409, f"[{twice.status_code}] {twice.json().get('code')}")
    register = boss.get(f"{BASE}/api/v1/certificates", timeout=T).json()["data"]
    step("register shows the reserved number as pending issuance, not as issued", any(p["certificate_number"] == number for p in register["pending_issuance"]) and not any(c["certificate_number"] == number for c in register["items"]), f"pending={len(register['pending_issuance'])}")

    out = worker_pass()
    step("one-off worker pass in the api container (certificate.issue with WeasyPrint + demo watermark)", "error" not in out.lower(), out[-120:])
    case_after = wait_for_publication(boss, app_id)
    step("TR-11 published: case COMPLETED, certificate ACTIVE (one-off pass or the live worker; polled up to 120 s)", case_after["status"] == "COMPLETED" and case_after["certificate"] is not None and case_after["certificate"]["effective_status"] == "ACTIVE", f"status={case_after['status']} issuance={case_after.get('issuance')}")
    certificate_id = case_after["certificate"]["certificate_id"]
    obligations = {o["kind"]: o["state"] for o in case_after["obligations"]}
    step("ISSUANCE_TASK and CASE_TARGET satisfied", obligations.get("ISSUANCE_TASK") == "SATISFIED" and obligations.get("CASE_TARGET") == "SATISFIED", f"{obligations}")
    timeline = [e["event_type"] for e in boss.get(f"{BASE}/api/v1/applications/{app_id}/timeline", timeout=T).json()["data"]["items"]]
    step("timeline: decision.approved.v1 + certificate.published.v1 (+ internal rationale)", "decision.approved.v1" in timeline and "certificate.published.v1" in timeline and "decision.rationale.v1" in timeline, "")

    detail_c = boss.get(f"{BASE}/api/v1/certificates/{certificate_id}", timeout=T)
    step("certificate detail (API-068) with artifact provenance and DEMO notice", detail_c.status_code == 200 and detail_c.json()["data"]["artifact"]["mode"] == "DEMO_WATERMARK" and detail_c.json()["data"]["artifact"]["renderer"] == "weasyprint" and detail_c.json()["data"]["is_demo"] is True, f"[{detail_c.status_code}] renderer={detail_c.json().get('data', {}).get('artifact')}")
    verification_url = detail_c.json()["data"]["verification_url"]
    access = boss.post(f"{BASE}/api/v1/certificates/{certificate_id}/access", json={}, headers=cmd(bh), timeout=T)
    step("artifact access ticket (API-069)", access.status_code == 200 and access.json()["data"]["mode"] == "DEMO_WATERMARK", f"[{access.status_code}]")
    download = boss.get(f"{BASE}{access.json()['data']['url']}", timeout=T)
    step("ticketed download is a PDF labelled DEMO_WATERMARK", download.status_code == 200 and download.headers.get("Content-Type", "").startswith("application/pdf") and download.content.startswith(b"%PDF") and download.headers.get("X-Agni-Artifact-Mode") == "DEMO_WATERMARK", f"[{download.status_code}] {len(download.content)} bytes")
    token = verification_url.rstrip("/").rsplit("/", 1)[-1]
    public = requests.get(f"{BASE}/api/v1/public/certificates/{token}", timeout=T)
    step("public verification by token (API-073): ACTIVE, demo, approved fields only, no-store", public.status_code == 200 and public.json()["data"]["effective_status"] == "ACTIVE" and public.json()["data"]["is_demo"] is True and public.headers.get("Cache-Control") == "no-store" and "applicant" not in public.text.lower(), f"[{public.status_code}] {sorted(public.json().get('data', {}).keys())}")
    by_number = requests.get(f"{BASE}/api/v1/public/certificates/{number}", timeout=T)
    step("public verification by exact number (demo TOKEN_OR_NUMBER profile)", by_number.status_code == 200 and by_number.json()["data"]["certificate_number"] == number, f"[{by_number.status_code}]")
    unknown = requests.get(f"{BASE}/api/v1/public/certificates/no-such-token-value", timeout=T)
    step("unknown lookup -> 404 without hints", unknown.status_code == 404 and "certificate_number" not in unknown.text, f"[{unknown.status_code}]")
    listing = boss.get(f"{BASE}/api/v1/certificates", params={"effective_status": "ACTIVE"}, timeout=T).json()["data"]
    step("register lists the published certificate as ACTIVE", any(c["certificate_number"] == number and c["effective_status"] == "ACTIVE" for c in listing["items"]), f"items={len(listing['items'])}")
    print("ALL DECISION SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
