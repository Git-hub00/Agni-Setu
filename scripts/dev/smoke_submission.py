"""Smoke-check B06 (atomic submission, routing, visibility) against a running local stack.

Self-contained applicant flow through nginx: fresh OTP applicant -> premises -> draft ->
declarations -> three uploads -> scan verdicts -> submit (receipt) -> replay same key -> detail
and timeline; a second premises in an unmapped ward proves the owned routing exception. With
`--oidc`, the seeded supervisor (anita, CENTRAL-PILOT) resolves the exception and starts scrutiny
through the real Keycloak sign-in, and the audience filter is checked (applicant never sees
internal notes).

Scanning: with the `full` profile (ClamAV) the worker produces the verdicts itself. Without it
(`--scan-via-demo`), this script runs one-off worker passes inside the api container with the
local demo scanner - a documented local sink, never a live provider.

Usage: uv run --directory backend python ../scripts/dev/smoke_submission.py [http://127.0.0.1:5173] [--scan-via-demo] [--oidc]
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
import uuid

import requests

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5173").rstrip("/")
SCAN_VIA_DEMO = "--scan-via-demo" in sys.argv
CONTACT = f"smoke-submit.{int(time.time())}@example.test"
PDF = b"%PDF-1.7\n" + b"synthetic submission evidence " * 40 + b"\n%%EOF\n"
JSON_TIMEOUT = 30


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def cmd(headers: dict[str, str], etag: str | None = None, key: str | None = None) -> dict[str, str]:
    h = {**headers, "Idempotency-Key": key or str(uuid.uuid4())}
    if etag:
        h["If-Match"] = etag
    return h


def sign_in_applicant() -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=JSON_TIMEOUT).json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    r = s.post(f"{BASE}/api/v1/auth/otp/challenges", json={"channel": "EMAIL", "contact": CONTACT}, headers=headers, timeout=JSON_TIMEOUT)
    step("otp challenge", r.status_code == 202, f"[{r.status_code}]")
    challenge_id = r.json()["data"]["challenge_id"]
    inbox = s.get(f"{BASE}/api/v1/demo/inbox", params={"channel": "EMAIL", "contact": CONTACT}, timeout=JSON_TIMEOUT)
    messages = inbox.json().get("data", {}).get("messages", [])
    match = re.search(r"\b(\d{6})\b", messages[0]["body"]) if messages else None
    step("demo inbox delivered a code", match is not None)
    r = s.post(f"{BASE}/api/v1/auth/otp/verify", json={"challenge_id": challenge_id, "code": match.group(1) if match else "", "channel": "EMAIL", "contact": CONTACT}, headers=headers, timeout=JSON_TIMEOUT)
    step("verify -> applicant session", r.status_code == 200, f"[{r.status_code}]")
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=JSON_TIMEOUT).json()["data"]["csrf_token"]
    return s, {"X-CSRFToken": token}


def upload(s: requests.Session, headers: dict[str, str], app_id: str, code: str) -> str:
    data = PDF + code.encode()
    digest = hashlib.sha256(data).hexdigest()
    r = s.post(f"{BASE}/api/v1/uploads", json={"target_type": "APPLICATION_DRAFT", "target_id": app_id, "original_name": f"{code}.pdf", "media_type": "application/pdf", "size_bytes": len(data), "sha256": digest, "requirement_code": code}, headers=cmd(headers), timeout=JSON_TIMEOUT)
    step(f"reserve upload {code}", r.status_code == 201, f"[{r.status_code}]")
    ticket = r.json()["data"]
    etag = r.headers.get("ETag", "")
    put = s.put(f"{BASE}{ticket['upload_url']}", data=data, headers={**headers, "Content-Type": "application/pdf"}, timeout=60)
    step(f"transfer {code}", put.status_code == 200, f"[{put.status_code}]")
    done = s.post(f"{BASE}/api/v1/uploads/{ticket['upload_id']}/complete", json={"sha256": digest, "size_bytes": len(data)}, headers=cmd(headers, etag), timeout=60)
    step(f"complete {code} -> QUARANTINED", done.status_code == 202, f"[{done.status_code}]")
    return str(done.json()["data"]["document_version_id"])


def wait_for_clean(s: requests.Session, doc_ids: list[str]) -> bool:
    for _ in range(18):  # up to ~3 minutes
        if SCAN_VIA_DEMO:
            subprocess.run(
                ["docker", "exec", "-e", "SCANNER_PROVIDER=demo_eicar", "agni-dev-api-1", "python", "manage.py", "process_jobs", "--once"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        states = [s.get(f"{BASE}/api/v1/documents/{d}", timeout=JSON_TIMEOUT).json()["data"]["scan_state"] for d in doc_ids]
        if all(state == "CLEAN" for state in states):
            return True
        if any(state == "REJECTED" for state in states):
            return False
        time.sleep(10)
    return False


def prepare_ready_draft(s: requests.Session, headers: dict[str, str], premises_body: dict[str, object]) -> dict[str, object]:
    r = s.post(f"{BASE}/api/v1/premises", json=premises_body, headers=cmd(headers), timeout=JSON_TIMEOUT)
    step("register premises", r.status_code == 201, f"[{r.status_code}] ward={premises_body['ward_key']}")
    premises_id = r.json()["data"]["premises_id"]
    services = s.get(f"{BASE}/api/v1/services", timeout=JSON_TIMEOUT).json()["data"]["items"]
    service = next(x for x in services if x["key"] == "demo-fire-noc")
    r = s.post(f"{BASE}/api/v1/applications", json={"premises_id": premises_id, "service_id": service["service_id"]}, headers=cmd(headers), timeout=JSON_TIMEOUT)
    step("create draft", r.status_code == 201, f"[{r.status_code}] {r.json()['data']['draft_reference']}")
    app_id = r.json()["data"]["application_id"]
    detail = s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=JSON_TIMEOUT)
    declarations = [{"code": d["code"], "version": d["version"], "accepted": True} for d in detail.json()["data"]["draft"]["declarations"]]
    r = s.patch(f"{BASE}/api/v1/applications/{app_id}/draft", json={"draft_revision": 1, "declaration_drafts": declarations}, headers=cmd(headers, detail.headers.get("ETag")), timeout=JSON_TIMEOUT)
    step("accept declarations -> revision 2", r.status_code == 200, f"[{r.status_code}]")
    etag = r.headers.get("ETag", "")
    doc_ids = [upload(s, headers, app_id, code) for code in ("ownership", "plan", "electrical")]
    step("all three uploads scanned CLEAN", wait_for_clean(s, doc_ids), "(worker or demo one-off pass)")
    r = s.patch(f"{BASE}/api/v1/applications/{app_id}/draft", json={"draft_revision": 2, "attachment_links": doc_ids}, headers=cmd(headers, etag), timeout=JSON_TIMEOUT)
    step("link documents -> revision 3, no blockers", r.status_code == 200 and r.json()["data"]["blockers"] == [], f"[{r.status_code}] blockers={r.json().get('data', {}).get('blockers')}")
    detail = s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=JSON_TIMEOUT)
    body = detail.json()["data"]
    step("detail: submit allowed", next(a for a in body["allowed_actions"] if a["key"] == "submit")["enabled"] is True)
    return {"app_id": app_id, "etag": detail.headers.get("ETag", ""), "detail": body, "doc_ids": doc_ids}


def submission_body(ready: dict[str, object]) -> dict[str, object]:
    detail = ready["detail"]
    assert isinstance(detail, dict)
    return {
        "draft_revision": detail["draft"]["draft_revision"],
        "reviewed_policy_version_id": detail["policy"]["policy_version_id"],
        "declaration_acceptances": [{"code": d["code"], "version": d["version"], "accepted": True} for d in detail["draft"]["declarations"]],
        "document_version_ids": ready["doc_ids"],
    }


def applicant_phase() -> dict[str, object]:
    s, headers = sign_in_applicant()
    ready = prepare_ready_draft(s, headers, {"display_name": "Smoke Submit Restaurant", "address_line1": "1 Receipt Road (synthetic)", "locality": "Karol Bagh", "ward_key": "W-01", "postal_code": "110005", "category_key": "Restaurant", "area_sqm": "200.00", "height_m": "5.00", "floor_count": 1})
    app_id = str(ready["app_id"])
    key = str(uuid.uuid4())
    r = s.post(f"{BASE}/api/v1/applications/{app_id}/submit", json=submission_body(ready), headers=cmd(headers, str(ready["etag"]), key), timeout=60)
    step("submit (TR-01) -> receipt", r.status_code == 200, f"[{r.status_code}] {r.json().get('data', {}).get('public_reference')} queue={r.json().get('data', {}).get('owner_queue', {}).get('queue_key')}")
    receipt = r.json()["data"]
    step("routing resolved to a mapped queue; obligations created", receipt["routing"]["resolved"] is True and len(receipt["obligations"]) == 2, f"due={[o['due_at'] for o in receipt['obligations']]}")
    replay = s.post(f"{BASE}/api/v1/applications/{app_id}/submit", json=submission_body(ready), headers=cmd(headers, str(ready["etag"]), key), timeout=60)
    step("same key + payload -> same receipt replayed", replay.status_code == 200 and replay.json()["data"]["replayed"] is True and replay.json()["data"]["public_reference"] == receipt["public_reference"], f"[{replay.status_code}]")
    again = s.post(f"{BASE}/api/v1/applications/{app_id}/submit", json=submission_body(ready), headers=cmd(headers, r.headers.get("ETag")), timeout=60)
    step("second submit with a new key refused (INVALID_TRANSITION)", again.status_code == 409 and again.json().get("code") == "INVALID_TRANSITION", f"[{again.status_code}]")
    detail = s.get(f"{BASE}/api/v1/applications/{app_id}", timeout=JSON_TIMEOUT).json()["data"]
    step("detail: SUBMITTED, revision 1 pinned to policy v1, no draft", detail["status"] == "SUBMITTED" and detail["submission"]["number"] == 1 and detail["draft"] is None, f"policy=v{detail['submission']['policy_number']}")
    timeline = s.get(f"{BASE}/api/v1/applications/{app_id}/timeline", timeout=JSON_TIMEOUT).json()["data"]["items"]
    step("applicant timeline is public-only", [e["event_type"] for e in timeline] == ["application.draft_created.v1", "application.submitted.v1"] and all(e["audience"] == "PUBLIC_CASE" for e in timeline))
    revisions = s.get(f"{BASE}/api/v1/applications/{app_id}/revisions", timeout=JSON_TIMEOUT).json()["data"]["items"]
    step("revisions: one immutable submission with 3 documents", len(revisions) == 1 and len(revisions[0]["documents"]) == 3)

    # Routing exception path: an unmapped ward.
    ready2 = prepare_ready_draft(s, headers, {"display_name": "Smoke Unmapped Office", "address_line1": "9 Nowhere Road (synthetic)", "locality": "Outskirts", "ward_key": "W-99", "postal_code": "110099", "category_key": "Office", "area_sqm": "300.00", "height_m": "6.00", "floor_count": 2})
    app2 = str(ready2["app_id"])
    r2 = s.post(f"{BASE}/api/v1/applications/{app2}/submit", json=submission_body(ready2), headers=cmd(headers, str(ready2["etag"])), timeout=60)
    step("unmapped ward submits with a visible owned routing exception", r2.status_code == 200 and r2.json()["data"]["routing"]["resolved"] is False and r2.json()["data"]["routing"]["exception_code"] == "NO_MATCH", f"[{r2.status_code}] queue={r2.json().get('data', {}).get('owner_queue', {}).get('queue_key')}")
    detail2 = s.get(f"{BASE}/api/v1/applications/{app2}", timeout=JSON_TIMEOUT).json()["data"]
    step("applicant does not see the internal exception record", detail2["routing_exception"] is None)
    overview = s.get(f"{BASE}/api/v1/overview", timeout=JSON_TIMEOUT).json()["data"]
    step("applicant overview counts own cases", overview["role"] == "applicant" and overview["counts"]["open"] == 2, f"counts={overview['counts']['by_status']}")
    print("ALL APPLICANT SUBMISSION SMOKE STEPS PASSED")
    return {"app_id": app_id, "app2": app2, "exception_id": r2.json()["data"]["routing"]["exception_id"]}


def _keycloak_login(s: requests.Session, username: str, password: str) -> requests.Response:
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/overview"}, timeout=60, allow_redirects=False)
    step("oidc start redirects to the identity provider", start.status_code == 302, f"[{start.status_code}]")
    page = s.get(start.headers["Location"], timeout=60)
    form_action = re.search(r'action="([^"]+)"', page.text)
    step("identity provider login form", page.status_code == 200 and form_action is not None, f"[{page.status_code}]")
    action = form_action.group(1).replace("&amp;", "&") if form_action else ""
    for cookie in s.cookies:
        if cookie.domain.startswith("localhost"):
            cookie.secure = False
    return s.post(action, data={"username": username, "password": password, "credentialId": ""}, timeout=60, allow_redirects=True)


def staff_phase(refs: dict[str, object]) -> None:
    s = requests.Session()
    final = _keycloak_login(s, "anita", "demo-anita-password")
    step("anita (supervisor, CENTRAL-PILOT) signed in", "error=" not in final.url, final.url)
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=JSON_TIMEOUT).json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    app2 = str(refs["app2"])
    d = s.get(f"{BASE}/api/v1/applications/{app2}", timeout=JSON_TIMEOUT)
    body = d.json()["data"]
    step("supervisor sees the routing exception and cannot start scrutiny yet", d.status_code == 200 and body["routing_exception"]["code"] == "NO_MATCH" and next(a for a in body["allowed_actions"] if a["key"] == "start-scrutiny")["enabled"] is False, f"[{d.status_code}]")
    queues = s.get(f"{BASE}/api/v1/overview", timeout=JSON_TIMEOUT).json()["data"]
    step("supervisor overview counts the exception", queues["counts"]["routing_exceptions"] >= 1, f"exceptions={queues['counts']['routing_exceptions']}")
    # Resolve to the central scrutiny desk (the case's own accountable queue) with the demo routing artifact.
    resolution = {
        "target_jurisdiction_id": _lookup_jurisdiction_id(),
        "target_queue_id": _lookup_queue_id("central-scrutiny"),
        "routing_artifact_id": body["routing_exception"]["routing_artifact_id"],
        "reason": "Smoke: outskirts ward served by the central scrutiny desk until the map is updated",
        "exception_id": body["routing_exception"]["exception_id"],
    }
    r = s.post(f"{BASE}/api/v1/applications/{app2}/resolve-routing", json=resolution, headers=cmd(headers, d.headers.get("ETag")), timeout=JSON_TIMEOUT)
    step("resolve routing (API-028)", r.status_code == 200, f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    r = s.post(f"{BASE}/api/v1/applications/{app2}/start-scrutiny", json={"reason": "Smoke: routing resolved, starting completeness check (internal note)"}, headers=cmd(headers, r.headers.get("ETag")), timeout=JSON_TIMEOUT)
    step("start scrutiny (TR-02) -> SCRUTINY", r.status_code == 200 and r.json()["data"]["status"] == "SCRUTINY", f"[{r.status_code}]")
    theirs = s.get(f"{BASE}/api/v1/applications/{app2}/timeline", timeout=JSON_TIMEOUT).json()["data"]["items"]
    step("supervisor timeline includes internal routing + note events", {"routing.exception_opened.v1", "routing.resolved.v1", "scrutiny.note.v1"} <= {e["event_type"] for e in theirs})
    print("ALL STAFF SUBMISSION SMOKE STEPS PASSED")


def _lookup_jurisdiction_id() -> str:
    return _shell_query("from agni.policies.models import Jurisdiction; print(Jurisdiction.objects.get(code='CENTRAL-PILOT').pk)")


def _lookup_queue_id(key: str) -> str:
    return _shell_query(f"from agni.routing.models import DutyQueue; print(DutyQueue.objects.get(queue_key='{key}').pk)")


def _shell_query(code: str) -> str:
    out = subprocess.run(["docker", "exec", "agni-dev-api-1", "python", "manage.py", "shell", "-c", code], capture_output=True, text=True, timeout=120)
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""


if __name__ == "__main__":
    refs = applicant_phase()
    if "--oidc" in sys.argv:
        staff_phase(refs)
