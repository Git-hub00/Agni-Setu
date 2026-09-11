"""Smoke-check B05 (drafts, uploads, scanning) against a running local stack (demo mode only).

Self-contained: signs in a fresh synthetic applicant by OTP through nginx, registers premises,
creates a draft, autosaves with the version precondition (and proves the stale-tab 412), uploads
a PDF through reserve -> PUT -> complete, waits for the worker's scan verdict, links the clean
version, opens it through an access ticket and detaches it again. Prints PASS/FAIL per step and
exits non-zero on the first failure; codes and secrets are never echoed.

Usage:  uv run --directory backend python ../scripts/dev/smoke_drafts.py [http://127.0.0.1:5173]
        [--expect-scan CLEAN|QUARANTINED]   (default CLEAN; use QUARANTINED when no scanner runs)
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
import uuid

import requests

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5173").rstrip("/")
EXPECT_SCAN = "QUARANTINED" if "--expect-scan" in sys.argv and "QUARANTINED" in sys.argv else "CLEAN"
CONTACT = f"smoke-draft.{int(time.time())}@example.test"
PDF = b"%PDF-1.7\n" + b"synthetic smoke layout " * 64 + b"\n%%EOF\n"


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def sign_in() -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=15).json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    r = s.post(f"{BASE}/api/v1/auth/otp/challenges", json={"channel": "EMAIL", "contact": CONTACT}, headers=headers, timeout=15)
    step("otp challenge", r.status_code == 202, f"[{r.status_code}]")
    challenge_id = r.json()["data"]["challenge_id"]
    inbox = s.get(f"{BASE}/api/v1/demo/inbox", params={"channel": "EMAIL", "contact": CONTACT}, timeout=15)
    messages = inbox.json().get("data", {}).get("messages", [])
    match = re.search(r"\b(\d{6})\b", messages[0]["body"]) if messages else None
    step("demo inbox delivered a code", match is not None)
    r = s.post(f"{BASE}/api/v1/auth/otp/verify", json={"challenge_id": challenge_id, "code": match.group(1) if match else "", "channel": "EMAIL", "contact": CONTACT}, headers=headers, timeout=15)
    step("verify -> applicant session", r.status_code == 200, f"[{r.status_code}]")
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=15).json()["data"]["csrf_token"]
    return s, {"X-CSRFToken": token}


def cmd_headers(headers: dict[str, str], etag: str | None = None) -> dict[str, str]:
    h = {**headers, "Idempotency-Key": str(uuid.uuid4())}
    if etag:
        h["If-Match"] = etag
    return h


def main() -> None:
    s, headers = sign_in()
    r = s.post(
        f"{BASE}/api/v1/premises",
        json={"display_name": "Smoke Draft Cafe", "address_line1": "1 Smoke Lane (synthetic)", "locality": "Karol Bagh", "ward_key": "W-01", "postal_code": "110005", "category_key": "Restaurant", "area_sqm": "120.00", "height_m": "4.50", "floor_count": 1},
        headers=cmd_headers(headers),
        timeout=15,
    )
    step("register premises", r.status_code == 201, f"[{r.status_code}]")
    premises_id = r.json()["data"]["premises_id"]
    services = s.get(f"{BASE}/api/v1/services", timeout=15).json()["data"]["items"]
    service = next((x for x in services if x["key"] == "demo-fire-noc" and x["available"]), None)
    step("demo-fire-noc available in the catalogue", service is not None)
    assert service is not None

    r = s.post(f"{BASE}/api/v1/applications", json={"premises_id": premises_id, "service_id": service["service_id"]}, headers=cmd_headers(headers), timeout=15)
    step("create draft (API-021)", r.status_code == 201, f"[{r.status_code}] {r.json().get('data', {}).get('draft_reference')}")
    app_id = r.json()["data"]["application_id"]
    etag_v1 = r.headers.get("ETag", "")

    d = s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=15)
    detail = d.json()["data"]
    reqs = {x["code"]: x for x in detail["draft"]["requirements"]}
    step("detail: revision 1, prefilled premises, requirements from policy v1", d.status_code == 200 and detail["draft"]["draft_revision"] == 1 and detail["draft"]["fields"]["display_name"] == "Smoke Draft Cafe" and {"ownership", "plan", "electrical"} <= set(reqs), f"[{d.status_code}] requirements={sorted(reqs)}")

    r = s.patch(f"{BASE}/api/v1/applications/{app_id}/draft", json={"draft_revision": 1, "fields": {"beneficiary_name": "Smoke Applicant", "occupancy_count": 40}, "declaration_drafts": [{"code": c, "version": "1", "accepted": True} for c in ("D01", "D02", "D03")]}, headers=cmd_headers(headers, etag_v1), timeout=15)
    step("autosave -> revision 2", r.status_code == 200 and r.json()["data"]["draft_revision"] == 2, f"[{r.status_code}] ETag={r.headers.get('ETag')}")
    etag_v2 = r.headers.get("ETag", "")
    stale = s.patch(f"{BASE}/api/v1/applications/{app_id}/draft", json={"draft_revision": 1, "fields": {"beneficiary_name": "Second Tab"}}, headers=cmd_headers(headers, etag_v1), timeout=15)
    step("stale second-tab save -> 412 VERSION_CONFLICT", stale.status_code == 412 and stale.json().get("code") == "VERSION_CONFLICT", f"[{stale.status_code}] current_draft_revision={stale.json().get('current_draft_revision')}")

    digest = hashlib.sha256(PDF).hexdigest()
    r = s.post(f"{BASE}/api/v1/uploads", json={"target_type": "APPLICATION_DRAFT", "target_id": app_id, "original_name": "layout.pdf", "media_type": "application/pdf", "size_bytes": len(PDF), "sha256": digest, "requirement_code": "plan"}, headers=cmd_headers(headers), timeout=15)
    step("reserve upload (API-033)", r.status_code == 201, f"[{r.status_code}]")
    ticket = r.json()["data"]
    upload_etag = r.headers.get("ETag", "")
    put = s.put(f"{BASE}{ticket['upload_url']}", data=PDF, headers={**headers, "Content-Type": "application/pdf"}, timeout=30)
    step("PUT bytes through the API (bounded, hashed server-side)", put.status_code == 200 and put.json()["data"]["sha256"] == digest, f"[{put.status_code}]")
    done = s.post(f"{BASE}/api/v1/uploads/{ticket['upload_id']}/complete", json={"sha256": digest, "size_bytes": len(PDF)}, headers=cmd_headers(headers, upload_etag), timeout=30)
    step("complete upload -> QUARANTINED version (API-034)", done.status_code == 202 and done.json()["data"]["scan_state"] == "QUARANTINED", f"[{done.status_code}]")
    doc_id = done.json()["data"]["document_version_id"]

    r = s.patch(f"{BASE}/api/v1/applications/{app_id}/draft", json={"draft_revision": 2, "attachment_links": [doc_id]}, headers=cmd_headers(headers, etag_v2), timeout=15)
    step("link document to the draft -> revision 3, plan PENDING_SCAN", r.status_code == 200 and next(x for x in r.json()["data"]["requirements"] if x["code"] == "plan")["status"] == "PENDING_SCAN", f"[{r.status_code}]")
    etag_v3 = r.headers.get("ETag", "")

    state = "QUARANTINED"
    for _ in range(40):  # up to ~2 minutes: the worker polls every 5 s
        state = s.get(f"{BASE}/api/v1/documents/{doc_id}", timeout=15).json()["data"]["scan_state"]
        if state != "QUARANTINED":
            break
        time.sleep(3)
    if EXPECT_SCAN == "CLEAN":
        step("worker scanned the exact object -> CLEAN", state == "CLEAN", f"state={state}")
        plan = next(x for x in s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=15).json()["data"]["draft"]["requirements"] if x["code"] == "plan")
        step("requirement plan SATISFIED by the clean version", plan["status"] == "SATISFIED" and plan["document_version_id"] == doc_id)
        access = s.post(f"{BASE}/api/v1/documents/{doc_id}/access", json={"purpose": "DOWNLOAD"}, headers=cmd_headers(headers), timeout=15)
        step("access ticket issued (API-036)", access.status_code == 200, f"[{access.status_code}]")
        content = s.get(f"{BASE}{access.json()['data']['url']}", timeout=30)
        step("ticketed download returns the exact bytes with nosniff", content.status_code == 200 and content.content == PDF and content.headers.get("X-Content-Type-Options") == "nosniff", f"[{content.status_code}] {len(content.content)} bytes")
    else:
        step("no scanner available -> version stays QUARANTINED (never CLEAN)", state == "QUARANTINED", f"state={state}")
        access = s.post(f"{BASE}/api/v1/documents/{doc_id}/access", json={"purpose": "DOWNLOAD"}, headers=cmd_headers(headers), timeout=15)
        step("quarantined file cannot be opened (409 FILE_QUARANTINED)", access.status_code == 409 and access.json().get("code") == "FILE_QUARANTINED", f"[{access.status_code}]")

    r = s.post(f"{BASE}/api/v1/documents/{doc_id}/detach", json={"reason": "smoke: detach the draft reference"}, headers=cmd_headers(headers, etag_v3), timeout=15)
    step("detach keeps the version, drops the draft link (API-037)", r.status_code == 200 and doc_id not in r.json()["data"]["attachment_links"] and any(x["document_version_id"] == doc_id for x in r.json()["data"]["documents"]), f"[{r.status_code}]")
    listing = s.get(f"{BASE}/api/v1/applications?status=DRAFT", timeout=15).json()["data"]["items"]
    step("application list shows the draft (API-020)", any(x["application_id"] == app_id for x in listing), f"items={len(listing)}")
    s.post(f"{BASE}/api/v1/auth/logout", headers=headers, timeout=15)
    print("ALL DRAFT/UPLOAD SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
