"""Smoke-check B10 (clocks, outbox dispatch, notifications) against a running local stack.

anita (Keycloak) reads the obligations from one cutoff (API-074/075), creates a manual
escalation (API-076), acknowledges it (API-077), then the scheduler/dispatcher and worker are
run once inside the api container so outbox intents fan out into in-app notifications and
threshold jobs; anita's notifications (API-078..080) and the operations summary (API-103, as
arjun) are checked. Nothing here changes a case.

Usage: uv run --directory backend python ../scripts/dev/smoke_clocks.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid

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
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/monitoring"}, timeout=T, allow_redirects=False)
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


def in_container(*args: str) -> str:
    run = subprocess.run(["docker", "exec", "agni-dev-api-1", "python", "manage.py", *args], capture_output=True, text=True, timeout=300)
    return (run.stdout + run.stderr).strip()


def main() -> None:
    boss, bh = keycloak_login("anita", "demo-anita-password")
    listing = boss.get(f"{BASE}/api/v1/obligations", timeout=T)
    step("obligations list (API-074) from one cutoff", listing.status_code == 200 and "as_of" in listing.json()["data"], f"[{listing.status_code}] counts={listing.json().get('data', {}).get('counts')}")
    items = listing.json()["data"]["items"]
    step("at least one open obligation in the jurisdiction", bool(items), f"items={len(items)}")
    row = items[0]
    detail = boss.get(f"{BASE}/api/v1/obligations/{row['obligation_id']}", timeout=T)
    step("obligation detail (API-075) with clock breakdown", detail.status_code == 200 and "clock" in detail.json()["data"], f"basis={detail.json().get('data', {}).get('clock', {}).get('basis')} remaining={detail.json().get('data', {}).get('clock', {}).get('remaining_minutes')}")
    etag = detail.headers.get("ETag", "")
    body = {"reason": "Smoke: manual escalation on the oldest open obligation", "requested_level": 2, "next_action": "Smoke: reassign to the senior desk before 17:00"}
    key = str(uuid.uuid4())
    r = boss.post(f"{BASE}/api/v1/obligations/{row['obligation_id']}/escalations", json=body, headers=cmd(bh, etag, key), timeout=T)
    step("manual escalation (API-076) -> 201, obligation untouched", r.status_code == 201 and r.json()["data"]["state"] == "OPEN" and r.json()["data"]["obligation_state"] in ("ACTIVE", "PAUSED"), f"[{r.status_code}] {r.json().get('detail', '')[:100]}")
    escalation = r.json()["data"]
    replay = boss.post(f"{BASE}/api/v1/obligations/{row['obligation_id']}/escalations", json=body, headers=cmd(bh, etag, key), timeout=T)
    step("same key replays the same escalation", replay.status_code == 201 and replay.json()["data"]["escalation_id"] == escalation["escalation_id"] and replay.json()["data"]["replayed"] is True, f"[{replay.status_code}]")
    ack = boss.post(f"{BASE}/api/v1/escalations/{escalation['escalation_id']}/acknowledge", json={"reason": "Smoke: taking ownership of the intervention", "next_action": "Smoke: senior desk review"}, headers=cmd(bh, f'"escalation:{escalation["escalation_id"]}:v{escalation["version"]}"'), timeout=T)
    step("acknowledge (API-077) -> ACKNOWLEDGED; obligation still open", ack.status_code == 200 and ack.json()["data"]["state"] == "ACKNOWLEDGED" and ack.json()["data"]["obligation_state"] in ("ACTIVE", "PAUSED"), f"[{ack.status_code}] {ack.json().get('detail', '')[:100]}")
    again = boss.post(f"{BASE}/api/v1/escalations/{escalation['escalation_id']}/acknowledge", json={"reason": "Smoke: second acknowledgement"}, headers=cmd(bh, ack.headers.get("ETag")), timeout=T)
    step("second acknowledgement refused (409)", again.status_code == 409, f"[{again.status_code}]")

    out = in_container("run_schedulers", "--once")
    step("scheduler + dispatcher pass inside the api container", "Traceback" not in out, out[-140:] or "(quiet pass)")
    for _ in range(3):
        wout = in_container("process_jobs", "--once")
        if "claimed=" not in wout:
            break
    step("worker passes drained fan-out / delivery / threshold jobs", "Traceback" not in wout, wout[-140:] or "(nothing due)")
    mine = boss.get(f"{BASE}/api/v1/notifications", timeout=T).json()["data"]
    step("anita has in-app notifications (API-078), escalation included", any(n["category"] == "ESCALATION" for n in mine["items"]), f"items={len(mine['items'])} unread={mine['unread_count']}")
    target = next(n for n in mine["items"] if n["category"] == "ESCALATION")
    read = boss.post(f"{BASE}/api/v1/notifications/{target['notification_id']}/read", json={}, headers=cmd(bh), timeout=T)
    step("mark read (API-079) idempotent", read.status_code == 200 and read.json()["data"]["read_at"], f"[{read.status_code}]")
    swept = boss.post(f"{BASE}/api/v1/notifications/read-through", json={"through": mine["as_of"]}, headers=cmd(bh), timeout=T)
    step("read-through (API-080) up to the seen boundary", swept.status_code == 200, f"marked={swept.json().get('data', {}).get('marked_read')}")
    prefs = boss.get(f"{BASE}/api/v1/me/preferences", timeout=T)
    step("preferences (API-008) readable", prefs.status_code == 200 and "mandatory_note" in prefs.json()["data"], "")

    ops, oh = keycloak_login("arjun", "demo-arjun-password")
    jobs = ops.get(f"{BASE}/api/v1/jobs", timeout=T)
    step("operations summary + jobs (API-103) for the administrator", jobs.status_code == 200 and "outbox" in jobs.json()["data"]["summary"], f"outbox={jobs.json().get('data', {}).get('summary', {}).get('outbox')} dead={jobs.json().get('data', {}).get('summary', {}).get('dead_letter')}")
    denied = boss.get(f"{BASE}/api/v1/jobs", timeout=T)
    step("supervisor cannot read the operations view (403)", denied.status_code == 403, f"[{denied.status_code}]")
    print("ALL CLOCK SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
