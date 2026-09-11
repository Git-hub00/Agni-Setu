"""Smoke-check B13 (lifecycle, support, holds) against a running local stack.

anita (supervisor with the seeded `certificate.status` grant) suspends and reinstates the sample
certificate that `smoke_decisions.py` published (public verification follows each step); Rakesh
(the holder) starts a linked renewal draft that leaves the certificate's validity untouched;
anita records and releases an administrative hold on an open case (clock paused, transition
blocked); Rakesh opens a support ticket linked to a case, anita adds an internal note the
requester cannot see and resolves it, Rakesh reopens it; the appeal route answers with the
approved referral.

Usage: uv run --directory backend python ../scripts/dev/smoke_lifecycle.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_reports as reports  # noqa: E402  (shares BASE, login helpers)
import smoke_submission as base  # noqa: E402  (applicant OTP sign-in)

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd
REASON = "Smoke: synthetic demonstration drill; no legal effect."


def main() -> None:
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    holder, hh = base.sign_in_applicant()

    # ---- certificate lifecycle (API-071 / API-070) -------------------------------------------
    register = boss.get(f"{BASE}/api/v1/certificates", params={"effective_status": "ACTIVE"}, timeout=T).json()["data"]
    step("an ACTIVE sample certificate exists (run smoke_decisions.py first)", bool(register["items"]), f"count={len(register['items'])}")
    cert = register["items"][0]
    cid = cert["certificate_id"]
    detail = boss.get(f"{BASE}/api/v1/certificates/{cid}", timeout=T)
    allowed = {a["action"]: a for a in detail.json()["data"]["allowed_status_actions"]}
    step("allowed status actions: SUSPEND/REVOKE/SUPERSEDE enabled with the seeded grant, REINSTATE not admissible", allowed["SUSPEND"]["enabled"] and allowed["REVOKE"]["enabled"] and allowed["REINSTATE"]["reason_code"] == "NOT_ADMISSIBLE", f"{ {k: v['reason_code'] for k, v in allowed.items()} }")
    case = boss.get(f"{BASE}/api/v1/applications/{cert['application_id']}", timeout=T).json()["data"]
    evidence = next((d["document_version_id"] for d in (case.get("submission") or {}).get("documents", [])), None)
    step("a CLEAN case document is available as basis evidence", evidence is not None, f"{evidence}")
    url = f"{BASE}/api/v1/certificates/{cid}/status-actions"
    r = boss.post(url, json={"action": "SUSPEND", "reason": REASON, "public_reason": "Suspended during the demonstration drill."}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
    step("SUSPEND without evidence refused (422)", r.status_code == 422, f"[{r.status_code}]")
    r = boss.post(url, json={"action": "SUSPEND", "reason": REASON, "public_reason": "Suspended during the demonstration drill.", "evidence_document_id": evidence}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
    step("SUSPEND with cited evidence (API-071) -> 201", r.status_code == 201 and r.json()["data"]["certificate"]["recorded_status"] == "SUSPENDED", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    etag = r.headers.get("ETag", "")
    public = requests.get(f"{BASE}/api/v1/public/certificates/{cert['certificate_number']}", timeout=T)
    step("public verification shows SUSPENDED (never silently ACTIVE)", public.status_code == 200 and public.json()["data"]["effective_status"] == "SUSPENDED", f"[{public.status_code}]")
    r = boss.post(url, json={"action": "REINSTATE", "reason": REASON, "public_reason": "Deficiency cleared; certificate back in force."}, headers=cmd(bh, etag), timeout=T)
    step("REINSTATE of a still-in-force suspension -> 201 ACTIVE", r.status_code == 201 and r.json()["data"]["certificate"]["recorded_status"] == "ACTIVE", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    history = boss.get(f"{BASE}/api/v1/certificates/{cid}", timeout=T).json()["data"]["status_history"]
    step("status history carries both instruments with public reasons", [h["action"] for h in history][-2:] == ["SUSPEND", "REINSTATE"], f"{[h['action'] for h in history]}")

    holder_detail = holder.get(f"{BASE}/api/v1/certificates/{cid}", timeout=T)
    if holder_detail.status_code == 200:
        valid_until = holder_detail.json()["data"]["valid_until"]
        renew = holder.post(f"{BASE}/api/v1/certificates/{cid}/renewals", json={"declaration_of_current_details": True}, headers=cmd(hh), timeout=T)
        step("holder starts a linked renewal draft (API-070)", renew.status_code in (201, 409), f"[{renew.status_code}] {renew.json().get('detail', '')[:80]}")
        after = holder.get(f"{BASE}/api/v1/certificates/{cid}", timeout=T).json()["data"]
        step("renewal does not extend the source validity", after["valid_until"] == valid_until and len(after["renewals"]) >= 1, f"valid_until={after['valid_until']}")
    else:
        step("holder is not the applicant of this sample certificate; renewal step skipped (NOT_RUN)", True, f"[{holder_detail.status_code}]")

    # ---- holds (API-031 / API-032) -----------------------------------------------------------
    open_cases = [c for c in boss.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"] if c["status"] in ("SCRUTINY", "INSPECTION_PENDING", "COMPLIANCE_PENDING", "REVIEW_PENDING")]
    step("an open case exists for the hold drill", bool(open_cases), f"count={len(open_cases)}")
    target = boss.get(f"{BASE}/api/v1/applications/{open_cases[0]['application_id']}", timeout=T)
    tcase = target.json()["data"]
    active = [o["obligation_id"] for o in tcase["obligations"] if o["state"] == "ACTIVE"]
    if tcase["on_hold"]:
        release_first = boss.post(f"{BASE}/api/v1/holds/{tcase['holds'][0]['hold_id']}/release", json={"reason": REASON}, headers=cmd(bh, tcase["holds"][0]["etag"]), timeout=T)
        step("released a hold left by an earlier drill", release_first.status_code == 200, f"[{release_first.status_code}]")
        target = boss.get(f"{BASE}/api/v1/applications/{tcase['application_id']}", timeout=T)
        tcase = target.json()["data"]
        active = [o["obligation_id"] for o in tcase["obligations"] if o["state"] == "ACTIVE"]
    r = boss.post(f"{BASE}/api/v1/applications/{tcase['application_id']}/holds", json={"kind": "ADMINISTRATIVE", "reason": REASON, "affected_obligation_ids": active, "command_block_scope": ["TRANSITIONS"]}, headers=cmd(bh, target.headers.get("ETag")), timeout=T)
    step("administrative hold recorded (API-031) pausing the listed clocks", r.status_code == 201 and r.json()["data"]["state"] == "ACTIVE", f"[{r.status_code}] {r.json().get('detail', '')[:100]} obligations={len(active)}")
    hold = r.json()["data"]
    held = boss.get(f"{BASE}/api/v1/applications/{tcase['application_id']}", timeout=T).json()["data"]
    step("case shows on_hold; listed obligations PAUSED; transition actions disabled with ON_HOLD", held["on_hold"] is True and all(o["state"] == "PAUSED" for o in held["obligations"] if o["obligation_id"] in active) and any(a["reason_code"] == "ON_HOLD" for a in held["allowed_actions"]), f"{[(a['key'], a['reason_code']) for a in held['allowed_actions'] if a['reason_code'] == 'ON_HOLD'][:3]}")
    r = boss.post(f"{BASE}/api/v1/holds/{hold['hold_id']}/release", json={"reason": REASON}, headers=cmd(bh, hold["etag"]), timeout=T)
    step("hold released (API-032); clocks resume", r.status_code == 200 and r.json()["data"]["state"] == "RELEASED", f"[{r.status_code}]")
    resumed = boss.get(f"{BASE}/api/v1/applications/{tcase['application_id']}", timeout=T).json()["data"]
    step("case no longer on hold; obligations ACTIVE again", resumed["on_hold"] is False and all(o["state"] == "ACTIVE" for o in resumed["obligations"] if o["obligation_id"] in active), "")

    # ---- support (API-112..118) ---------------------------------------------------------------
    routes = holder.get(f"{BASE}/api/v1/support/routes", timeout=T).json()["data"]
    step("conditional routes: appeals disabled with referral text", routes["appeals"]["enabled"] is False and bool(routes["appeals"]["referral_text"]), routes["appeals"]["referral_text"][:60])
    appeal = holder.post(f"{BASE}/api/v1/appeals", json={"challenged_decision_id": str(uuid.uuid4()), "grounds": "x" * 40}, headers=cmd(hh), timeout=T)
    step("appeal route answers 409 SERVICE_DISABLED with the referral (no fake filing)", appeal.status_code == 409 and appeal.json().get("code") == "SERVICE_DISABLED", f"[{appeal.status_code}]")
    mine = holder.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"]
    ticket_body = {"category": "TECHNICAL", "subject": "Smoke: appointment page error", "description": "The appointment page shows an error when opened from my phone during the drill."}
    if mine:
        ticket_body["application_id"] = mine[0]["application_id"]
    r = holder.post(f"{BASE}/api/v1/tickets", json=ticket_body, headers=cmd(hh), timeout=T)
    step("applicant opens a support ticket (API-113)", r.status_code == 201 and r.json()["data"]["state"] == "OPEN", f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    ticket = r.json()["data"]
    tid = ticket["ticket_id"]
    staff_view = boss.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T)
    step("supervisor of the queue reads the ticket with support scope", staff_view.status_code == 200 and staff_view.json()["data"]["support_scope"] is True, f"[{staff_view.status_code}]")
    r = boss.post(f"{BASE}/api/v1/tickets/{tid}/messages", json={"body": "Internal: checked the appointment record; slot is valid.", "audience": "INTERNAL"}, headers=cmd(bh, staff_view.headers.get("ETag")), timeout=T)
    step("internal note recorded (API-115)", r.status_code == 201, f"[{r.status_code}]")
    requester_view = holder.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T)
    step("requester never sees INTERNAL notes", all(m["audience"] == "REQUESTER" for m in requester_view.json()["data"]["messages"]), f"messages={len(requester_view.json()['data']['messages'])}")
    r = boss.post(f"{BASE}/api/v1/tickets/{tid}/messages", json={"body": "Please clear the app cache and retry.", "audience": "REQUESTER"}, headers=cmd(bh, boss.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T).headers.get("ETag")), timeout=T)
    step("staff reply moves the ticket to IN_PROGRESS", r.status_code == 201 and r.json()["data"]["ticket_state"] == "IN_PROGRESS", f"[{r.status_code}]")
    r = boss.post(f"{BASE}/api/v1/tickets/{tid}/status", json={"state": "RESOLVED", "reason": "Cache cleared; the page opens. Resolving."}, headers=cmd(bh, boss.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T).headers.get("ETag")), timeout=T)
    step("staff resolves (API-116)", r.status_code == 200 and r.json()["data"]["state"] == "RESOLVED", f"[{r.status_code}]")
    r = holder.post(f"{BASE}/api/v1/tickets/{tid}/status", json={"state": "IN_PROGRESS", "reason": "It failed again this morning, please look once more."}, headers=cmd(hh, holder.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T).headers.get("ETag")), timeout=T)
    step("requester reopens a resolved ticket", r.status_code == 200 and r.json()["data"]["state"] == "IN_PROGRESS", f"[{r.status_code}]")
    forbidden = holder.post(f"{BASE}/api/v1/tickets/{tid}/status", json={"state": "RESOLVED", "reason": "Trying to close it myself for the drill."}, headers=cmd(hh, holder.get(f"{BASE}/api/v1/tickets/{tid}", timeout=T).headers.get("ETag")), timeout=T)
    step("requester cannot resolve (403)", forbidden.status_code == 403, f"[{forbidden.status_code}]")
    if mine:
        after_case = holder.get(f"{BASE}/api/v1/applications/{mine[0]['application_id']}", timeout=T).json()["data"]
        step("the linked case is untouched by the support conversation", after_case["status"] == mine[0]["status"] and after_case["version"] == mine[0]["version"], f"{after_case['status']} v{after_case['version']}")
    print("ALL LIFECYCLE SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
