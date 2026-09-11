"""Smoke-check B14 (reporting, exports, audit reader, job recovery, team governance) against a
running local stack.

anita (supervisor) reads reconciled metrics at the current cutoff and at an earlier one,
requests a CASES export with a purpose, waits for the worker to generate it, reauthorises access
and downloads the CSV (header, neutralised cells, no applicant identity); the demo applicant
cannot see it. anita searches the audit trail of one case (the search itself lands on her audit
chain) and opens a row with its integrity check. arjun (operations administrator) reads the
roster, proposes an `export.sensitive` grant for anita, cannot approve his own proposal; meera
(grant approver in the seed) approves it with the grant ETag, then revokes it. arjun retries or
reconciles a job only if one is waiting (otherwise recorded as NOT_RUN).

Usage: uv run --directory backend python ../scripts/dev/smoke_reporting.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_reports as reports  # noqa: E402  (shares BASE, login helpers)
import smoke_submission as base  # noqa: E402  (applicant OTP sign-in)

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd
PURPOSE = "Smoke: circle review pack; synthetic demonstration data only."
REASON = "Smoke: synthetic demonstration drill; no legal effect."


def main() -> None:
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    applicant, _ah = base.sign_in_applicant()

    # ---- metrics (API-081) --------------------------------------------------------------------
    r = boss.get(f"{BASE}/api/v1/reports/summary", timeout=T)
    step("supervisor metrics at the current cutoff (API-081)", r.status_code == 200, f"[{r.status_code}]")
    m = r.json()["data"]
    step("totals reconcile with the population and carry the definition version", m["reconciled"] is True and m["definition_version"] == "metrics-v1" and m["metrics"]["received"] == m["population"] >= 1, f"received={m['metrics']['received']} by_status={m['by_status']}")
    step("resolution sample marked insufficient when under 5 closed cases", m["metrics"]["resolution_hours"]["insufficient_sample"] is (m["metrics"]["resolution_hours"]["sample_size"] < 5), f"n={m['metrics']['resolution_hours']['sample_size']}")
    early = boss.get(f"{BASE}/api/v1/reports/summary", params={"as_of": "2026-01-01T00:00:00+00:00"}, timeout=T).json()["data"]
    step("an earlier cutoff sees fewer (or no) received cases", early["metrics"]["received"] <= m["metrics"]["received"] and early["reconciled"] is True, f"received@2026-01-01={early['metrics']['received']}")
    future = boss.get(f"{BASE}/api/v1/reports/summary", params={"as_of": (datetime.now(UTC) + timedelta(days=2)).isoformat()}, timeout=T)
    step("a future cutoff is refused (422)", future.status_code == 422, f"[{future.status_code}]")
    own = applicant.get(f"{BASE}/api/v1/reports/summary", timeout=T)
    step("applicant metrics are scoped to own cases", own.status_code == 200 and own.json()["data"]["scope"] == {"kind": "OWN_CASES"}, f"[{own.status_code}] received={own.json()['data']['metrics']['received']}")

    # ---- exports (API-082..084) ---------------------------------------------------------------
    r = boss.post(f"{BASE}/api/v1/exports", json={"kind": "CASES", "field_set_key": "case-summary", "purpose": PURPOSE, "format": "PDF"}, headers=cmd(bh), timeout=T)
    step("PDF export refused with SERVICE_DISABLED", r.status_code == 409 and r.json().get("code") == "SERVICE_DISABLED", f"[{r.status_code}]")
    r = boss.post(f"{BASE}/api/v1/exports", json={"kind": "CASES", "field_set_key": "case-summary", "purpose": PURPOSE}, headers=cmd(bh), timeout=T)
    step("CASES export requested with a purpose (API-082) -> 202 READY", r.status_code == 202 and r.json()["data"]["state"] == "READY", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    export = r.json()["data"]
    eid = export["export_id"]
    state = export["state"]
    for _ in range(30):
        time.sleep(2)
        state = boss.get(f"{BASE}/api/v1/exports/{eid}", timeout=T).json()["data"]["state"]
        if state in ("COMPLETE", "FAILED", "EXPIRED"):
            break
    detail = boss.get(f"{BASE}/api/v1/exports/{eid}", timeout=T).json()["data"]
    step("worker generated the export (API-083 COMPLETE, scope still valid)", detail["state"] == "COMPLETE" and detail["scope_valid"] is True and detail["row_count"] == export["population"], f"state={detail['state']} rows={detail['row_count']} population={export['population']}")
    r = applicant.get(f"{BASE}/api/v1/exports/{eid}", timeout=T)
    step("another account learns nothing about the export (404)", r.status_code == 404, f"[{r.status_code}]")
    r = boss.post(f"{BASE}/api/v1/exports/{eid}/access", json={"reason": "Smoke download"}, headers=bh, timeout=T)
    step("access reauthorised and audited (API-084) -> ticketed URL", r.status_code == 200 and r.json()["data"]["url"].startswith("/api/v1/exports/"), f"[{r.status_code}]")
    url = r.json()["data"]["url"]
    r = applicant.get(f"{BASE}{url}", timeout=T)
    step("the ticket is bound to the requester (404 for another account)", r.status_code == 404, f"[{r.status_code}]")
    r = boss.get(f"{BASE}{url}", timeout=T)
    step("CSV downloaded, private and never cached", r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/csv") and "no-store" in r.headers.get("Cache-Control", ""), f"[{r.status_code}] {r.headers.get('Content-Type')}")
    lines = r.text.splitlines()
    header = lines[3] if len(lines) > 3 else ""
    data_rows = lines[4:]
    step("header carries the approved field set and every row is present", header.startswith("public_reference") and len(data_rows) == detail["row_count"], f"rows={len(data_rows)}")
    unsafe = [row for row in data_rows for cell in row.split(",") if cell[:1] in ("=", "+", "-", "@")]
    step("no cell starts with a spreadsheet formula prefix", not unsafe, f"unsafe={len(unsafe)}")
    step("no applicant contact or name in the field set", "Rakesh" not in r.text and "@" not in "".join(data_rows), "")
    listing = boss.get(f"{BASE}/api/v1/exports", timeout=T).json()["data"]["items"]
    step("export appears in the requester's list", any(e["export_id"] == eid for e in listing), f"count={len(listing)}")

    # ---- audit reader (API-085/086) -----------------------------------------------------------
    cases = boss.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"]
    step("a case exists for the audit search", bool(cases), f"count={len(cases)}")
    app_id = cases[0]["application_id"]
    r = boss.get(f"{BASE}/api/v1/audit-events", params={"entity_type": "application", "entity_id": app_id, "limit": "20"}, timeout=T)
    step("supervisor reads the case audit trail within scope (API-085)", r.status_code == 200 and r.json()["data"]["items"] and r.json()["data"]["redacted"] is False, f"[{r.status_code}] items={len(r.json().get('data', {}).get('items', []))}")
    first = r.json()["data"]["items"][0]
    me = boss.get(f"{BASE}/api/v1/me", timeout=T).json()["data"]["id"]
    reads = boss.get(f"{BASE}/api/v1/audit-events", params={"action": "audit.read", "entity_type": "audit_query", "entity_id": me}, timeout=T).json()["data"]["items"]
    step("the search itself is on the reader's own audit chain", any(x["actor_id"] == me for x in reads), f"reads={len(reads)}")
    r = boss.get(f"{BASE}/api/v1/audit-events/{first['audit_event_id']}", timeout=T)
    step("detail carries the integrity check (API-086)", r.status_code == 200 and r.json()["data"]["integrity"]["chain_valid"] is True, f"[{r.status_code}] {r.json().get('data', {}).get('integrity', {}).get('label')}")
    r = applicant.get(f"{BASE}/api/v1/audit-events", timeout=T)
    step("applicants have no audit reader (403)", r.status_code == 403, f"[{r.status_code}]")

    # ---- team governance (API-087..093) -------------------------------------------------------
    ops, oh = reports.keycloak_login("arjun", "demo-arjun-password")
    roster = ops.get(f"{BASE}/api/v1/staff", timeout=T).json()["data"]
    step("administrator roster is global and manageable (API-087)", roster["scope"] == "GLOBAL" and roster["can_manage"] is True and any(p["display_name"].startswith("Anita") for p in roster["items"]), f"staff={len(roster['items'])}")
    anita = next(p for p in roster["items"] if p["display_name"].startswith("Anita"))
    mine = boss.get(f"{BASE}/api/v1/staff", timeout=T).json()["data"]
    step("supervisor roster is jurisdiction-scoped and read-only", mine["scope"] == "JURISDICTIONS" and mine["can_manage"] is False, f"staff={len(mine['items'])}")
    jurisdiction_id = next(r_["jurisdiction_id"] for r_ in anita["roles"] if r_["jurisdiction_id"])
    existing = [g for g in anita["grants"] if g["capability"] == "export.sensitive" and g["state"] in ("PROPOSED", "APPROVED")]
    if existing:
        step("an export.sensitive grant from an earlier drill exists; reusing it", True, existing[0]["state"])
        grant = existing[0]
    else:
        r = ops.post(f"{BASE}/api/v1/authority-grants", json={"subject_id": anita["principal_id"], "capability": "export.sensitive", "scope_kind": "JURISDICTION", "jurisdiction_id": jurisdiction_id, "reason": REASON}, headers=cmd(oh), timeout=T)
        step("arjun proposes export.sensitive for anita (API-091) -> 201 PROPOSED", r.status_code == 201 and r.json()["data"]["state"] == "PROPOSED", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
        grant = {**r.json()["data"], "etag": r.headers.get("ETag", "")}
    if grant["state"] == "PROPOSED":
        r = ops.post(f"{BASE}/api/v1/authority-grants/{grant['grant_id']}/approve", json={"reason": REASON}, headers=cmd(oh, grant["etag"]), timeout=T)
        step("the preparer cannot approve his own proposal (403 separation of duties)", r.status_code == 403, f"[{r.status_code}] {r.json().get('code')}")
        meera, mh = reports.keycloak_login("meera", "demo-meera-password")
        r = meera.post(f"{BASE}/api/v1/authority-grants/{grant['grant_id']}/approve", json={"reason": REASON}, headers=cmd(mh, grant["etag"]), timeout=T)
        step("meera approves with the grant ETag (API-092) -> APPROVED", r.status_code == 200 and r.json()["data"]["state"] == "APPROVED", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
        grant_etag = r.headers.get("ETag", "")
    else:
        meera, mh = reports.keycloak_login("meera", "demo-meera-password")
        grant_etag = grant["etag"]
    r = meera.post(f"{BASE}/api/v1/authority-grants/{grant['grant_id']}/revoke", json={"reason": REASON}, headers=cmd(mh, grant_etag), timeout=T)
    step("meera revokes the grant (API-093) -> REVOKED", r.status_code == 200 and r.json()["data"]["state"] == "REVOKED", f"[{r.status_code}] {r.json().get('detail', '')[:80]}")
    after = ops.get(f"{BASE}/api/v1/staff/{anita['principal_id']}", timeout=T).json()["data"]
    step("roster shows the revoked grant; anita's roles untouched", any(g["grant_id"] == grant["grant_id"] and g["state"] == "REVOKED" for g in after["grants"]) and after["active"] is True, "")

    # ---- job recovery (API-105/106) -----------------------------------------------------------
    jobs = ops.get(f"{BASE}/api/v1/jobs", params={"state": "DEAD_LETTER"}, timeout=T).json()["data"]
    if jobs["items"]:
        job = jobs["items"][0]
        r = ops.post(f"{BASE}/api/v1/jobs/{job['job_id']}/retry", json={"reason": REASON}, headers=cmd(oh), timeout=T)
        step("dead-letter job retried as the same logical action (API-105)", r.status_code in (202, 409), f"[{r.status_code}] {r.json().get('data', {}).get('state') or r.json().get('detail', '')[:80]}")
    else:
        step("no dead-letter job waiting; retry drill NOT_RUN (covered by the integration test)", True, f"summary dead_letter={jobs['summary']['dead_letter']}")
    stale = boss.get(f"{BASE}/api/v1/me", timeout=T)
    step("anita's earlier session ended when her authority changed (epoch bump)", stale.status_code == 401, f"[{stale.status_code}]")
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    r = boss.post(f"{BASE}/api/v1/jobs/00000000-0000-0000-0000-000000000000/retry", json={"reason": REASON}, headers=cmd(bh), timeout=T)
    step("recovery commands are administrator-only (403 for a supervisor)", r.status_code == 403, f"[{r.status_code}]")
    print("ALL REPORTING SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
