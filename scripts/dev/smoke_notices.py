"""Smoke-check B09 (notices, responses and correction cycles) against a running local stack.

Creates a fresh OTP applicant case, submits it, lets `anita` (Keycloak) start scrutiny and
publish an itemised INFORMATION notice (TR-03), proves the guard rails, lets the applicant upload
response evidence through the NOTICE_RESPONSE target (scanned by a one-off demo-scanner pass),
submit a per-item reply (never a transition), and lets anita review the item and accept the
information round (TR-04) back to SCRUTINY.

Usage: uv run --directory backend python ../scripts/dev/smoke_notices.py [http://127.0.0.1:5173] --scan-via-demo
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_submission as base  # noqa: E402  (shares BASE / --scan-via-demo parsing)

BASE = base.BASE
T = 60
PDF = b"%PDF-1.7\n" + b"synthetic notice reply evidence " * 30 + b"\n%%EOF\n"
step = base.step
cmd = base.cmd


def scan_via_demo() -> None:
    subprocess.run(
        ["docker", "exec", "-e", "SCANNER_PROVIDER=demo_eicar", "agni-dev-api-1", "python", "manage.py", "process_jobs", "--once"],
        capture_output=True,
        text=True,
        timeout=180,
    )


def keycloak(username: str, password: str) -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    final = base._keycloak_login(s, username, password)
    step(f"{username} signed in", "error=" not in final.url, final.url)
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=T).json()["data"]["csrf_token"]
    return s, {"X-CSRFToken": token}


def upload_response_evidence(s: requests.Session, h: dict[str, str], notice_id: str, code: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    r = s.post(
        f"{BASE}/api/v1/uploads",
        json={"target_type": "NOTICE_RESPONSE", "target_id": notice_id, "original_name": f"{code}.pdf", "media_type": "application/pdf", "size_bytes": len(data), "sha256": digest, "requirement_code": code},
        headers=cmd(h),
        timeout=T,
    )
    step(f"reserve response evidence {code} (NOTICE_RESPONSE)", r.status_code == 201, f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    ticket = r.json()["data"]
    put = s.put(f"{BASE}{ticket['upload_url']}", data=data, headers={**h, "Content-Type": "application/pdf"}, timeout=T)
    step(f"PUT bytes {code}", put.status_code == 200 and put.json()["data"]["sha256"] == digest, f"[{put.status_code}]")
    done = s.post(f"{BASE}/api/v1/uploads/{ticket['upload_id']}/complete", json={"sha256": digest, "size_bytes": len(data)}, headers=cmd(h, r.headers.get("ETag")), timeout=T)
    step(f"complete {code} -> QUARANTINED", done.status_code == 202 and done.json()["data"]["scan_state"] == "QUARANTINED", f"[{done.status_code}]")
    return str(done.json()["data"]["document_version_id"])


INFO_ITEMS = [
    {"code": "INFO-01", "title": "Ownership proof is illegible", "description": "Upload a legible copy of the ownership document (all pages).", "required": True, "acceptable_evidence_types": ["DOCUMENT"]},
    {"code": "INFO-02", "title": "Optional floor plan clarification", "description": "If available, mark the assembly points on the floor plan.", "required": False, "acceptable_evidence_types": ["WRITTEN_EXPLANATION"]},
]


def main() -> None:
    # 1. Fresh applicant case through the real submission path.
    s, ah = base.sign_in_applicant()
    ready = base.prepare_ready_draft(s, ah, {"display_name": "Smoke Notice Restaurant", "address_line1": "3 Notice Road (synthetic)", "locality": "Karol Bagh", "ward_key": "W-01", "postal_code": "110005", "category_key": "Restaurant", "area_sqm": "180.00", "height_m": "4.50", "floor_count": 1})
    app_id = str(ready["app_id"])
    r = s.post(f"{BASE}/api/v1/applications/{app_id}/submit", json=base.submission_body(ready), headers=cmd(ah, str(ready["etag"])), timeout=T)
    step("submit (TR-01) -> receipt", r.status_code == 200, f"[{r.status_code}] {r.json().get('data', {}).get('public_reference')}")

    # 2. anita starts scrutiny.
    boss, bh = keycloak("anita", "demo-anita-password")
    detail = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T)
    r = boss.post(f"{BASE}/api/v1/applications/{app_id}/start-scrutiny", json={"reason": "Smoke: completeness check started (internal note)"}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
    step("start scrutiny (TR-02) -> SCRUTINY", r.status_code == 200 and r.json()["data"]["status"] == "SCRUTINY", f"[{r.status_code}]")
    case_etag = r.headers.get("ETag", "")
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    step("supervisor may request information (allowed_actions)", next(a for a in case["allowed_actions"] if a["key"] == "request-information")["enabled"] is True)

    # 3. TR-03: itemised information notice.
    body = {"type": "INFORMATION", "public_reason": "The submitted ownership proof cannot be read; one clarification is needed.", "internal_note": "Smoke: applicant called the desk; second copy expected.", "items": INFO_ITEMS}
    r = boss.post(f"{BASE}/api/v1/applications/{app_id}/notices", json=body, headers=cmd(bh, case_etag), timeout=T)
    step("publish INFORMATION notice (API-054, TR-03) -> 201", r.status_code == 201 and r.json()["data"]["application_status"] == "INFO_REQUIRED" and r.json()["data"]["round_number"] == 1, f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    notice = r.json()["data"]
    case_etag = r.headers.get("ETag", "")
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    obligations = {o["kind"]: o for o in case["obligations"]}
    step("case INFO_REQUIRED; APPLICANT_RESPONSE ACTIVE; SCRUTINY_TASK SATISFIED", case["status"] == "INFO_REQUIRED" and obligations["APPLICANT_RESPONSE"]["state"] == "ACTIVE" and obligations["SCRUTINY_TASK"]["state"] == "SATISFIED", f"respond by {obligations['APPLICANT_RESPONSE']['due_at']}")

    # 4. Guard rails.
    again = boss.post(f"{BASE}/api/v1/applications/{app_id}/notices", json=body, headers=cmd(bh, case_etag), timeout=T)
    step("second notice without supersedes from INFO_REQUIRED refused (409)", again.status_code == 409 and again.json().get("code") == "INVALID_TRANSITION", f"[{again.status_code}]")
    empty = boss.post(f"{BASE}/api/v1/applications/{app_id}/notices", json={**body, "items": []}, headers=cmd(bh, case_etag), timeout=T)
    step("empty item list refused (422)", empty.status_code == 422, f"[{empty.status_code}]")

    # 5. Applicant reads the notice and replies with scanned evidence.
    view = s.get(f"{BASE}/api/v1/notices/{notice['notice_id']}", timeout=T)
    applicant_notice = view.json()["data"]
    step("applicant view hides the internal note and may respond", "internal_note" not in applicant_notice and next(a for a in applicant_notice["allowed_actions"] if a["key"] == "respond")["enabled"] is True)
    doc = upload_response_evidence(s, ah, notice["notice_id"], "response-info-01", PDF)
    scan_via_demo()
    state = s.get(f"{BASE}/api/v1/documents/{doc}", timeout=T).json()["data"]["scan_state"]
    step("response evidence CLEAN after the demo scan pass", state == "CLEAN", state)
    info1 = next(i for i in applicant_notice["items"] if i["code"] == "INFO-01")
    r = s.post(
        f"{BASE}/api/v1/notices/{notice['notice_id']}/responses",
        json={"application_version": applicant_notice["application_version"], "responses": [{"notice_item_id": info1["notice_item_id"], "explanation": "Attached a scanned, legible copy of all three pages.", "document_version_ids": [doc]}], "declaration_accepted": True},
        headers=cmd(ah, view.headers.get("ETag")),
        timeout=T,
    )
    step("submit reply (API-056) -> 201, item RESPONSE_RECEIVED", r.status_code == 201 and r.json()["data"]["responses"][0]["item_state"] == "RESPONSE_RECEIVED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    case = s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    step("a reply never transitions the case (still INFO_REQUIRED)", case["status"] == "INFO_REQUIRED")

    # 6. Review and TR-04.
    current = boss.get(f"{BASE}/api/v1/notices/{notice['notice_id']}", timeout=T)
    early = boss.post(f"{BASE}/api/v1/notices/{notice['notice_id']}/accept-information", json={"reason": "Smoke: trying to accept before review"}, headers=cmd(bh, current.headers.get("ETag")), timeout=T)
    step("accept-information before review refused (409 RESPONSE_NOT_VERIFIED)", early.status_code == 409 and early.json().get("code") == "RESPONSE_NOT_VERIFIED", f"[{early.status_code}] pending={early.json().get('pending_items')}")
    item = next(i for i in current.json()["data"]["items"] if i["code"] == "INFO-01")
    r = boss.post(
        f"{BASE}/api/v1/notice-items/{item['notice_item_id']}/review",
        json={"application_version": current.json()["data"]["application_version"], "response_revision_id": item["current_response_id"], "outcome": "ACCEPTED", "reason": "Smoke: legible copy received and matches the registry"},
        headers=cmd(bh, f'"notice_item:{item["notice_item_id"]}:v{item["version"]}"'),
        timeout=T,
    )
    step("review item ACCEPTED (API-058)", r.status_code == 200 and r.json()["data"]["state"] == "ACCEPTED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    current = boss.get(f"{BASE}/api/v1/notices/{notice['notice_id']}", timeout=T)
    r = boss.post(f"{BASE}/api/v1/notices/{notice['notice_id']}/accept-information", json={"reason": "Smoke: all required information now on file"}, headers=cmd(bh, current.headers.get("ETag")), timeout=T)
    step("accept-information (API-057, TR-04) -> SCRUTINY, notice SATISFIED", r.status_code == 200 and r.json()["data"]["application_status"] == "SCRUTINY" and r.json()["data"]["state"] == "SATISFIED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    case = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    kinds = [o["kind"] + ":" + o["state"] for o in case["obligations"]]
    step("case SCRUTINY with a fresh SCRUTINY_TASK and the response obligation satisfied", case["status"] == "SCRUTINY" and "SCRUTINY_TASK:ACTIVE" in kinds and "APPLICANT_RESPONSE:SATISFIED" in kinds, f"{kinds}")
    timeline = [e["event_type"] for e in s.get(f"{BASE}/api/v1/applications/{app_id}/timeline", timeout=T).json()["data"]["items"]]
    step("applicant timeline: notice.published, notice.response_received, notice.item_reviewed, information.accepted", {"notice.published.v1", "notice.response_received.v1", "notice.item_reviewed.v1", "information.accepted.v1"} <= set(timeline), "")
    print(f"ALL NOTICE SMOKE STEPS PASSED (case {app_id} left in SCRUTINY)")


if __name__ == "__main__":
    main()
