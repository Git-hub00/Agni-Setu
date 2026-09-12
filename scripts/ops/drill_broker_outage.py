"""Physical drill (docs/08 s.10 "stop the broker after an application is accepted"): stop the
RabbitMQ container, accept a real command through the API (an administrative hold and its
release on an open case - both emit outbox events), show the API still accepted the work with
the intents PENDING in the outbox, restart the broker and watch the scheduler's dispatcher
republish them. Nothing is deleted; only `docker stop/start` on the broker container.

Usage: uv run --directory backend python ../scripts/ops/drill_broker_outage.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
import smoke_reports as reports  # noqa: E402

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd
BROKER = "agni-dev-rabbitmq-1"
REASON = "Reliability drill: broker outage; synthetic demonstration data only."


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def summary(ops: reports.requests.Session) -> dict:
    return ops.get(f"{BASE}/api/v1/jobs", timeout=T).json()["data"]["summary"]


def main() -> None:
    ops, _ = reports.keycloak_login("arjun", "demo-arjun-password")
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")
    baseline = summary(ops)
    step("baseline outbox has no old pending intents", baseline["outbox"]["pending"] == 0, f"pending={baseline['outbox']['pending']}")
    cases = [c for c in boss.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"] if c["status"] in ("SCRUTINY", "INSPECTION_PENDING", "COMPLIANCE_PENDING", "REVIEW_PENDING") and not c.get("on_hold")]
    step("an open case without a hold exists", bool(cases), f"count={len(cases)}")
    app_id = cases[0]["application_id"]
    fanout_before = baseline["by_kind"].get("notification.fanout", 0)
    started = time.time()
    outage_since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    docker("stop", BROKER)
    step("broker container stopped", docker("inspect", "-f", "{{.State.Running}}", BROKER) == "false")
    try:
        detail = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T)
        held = boss.post(f"{BASE}/api/v1/applications/{app_id}/holds", json={"kind": "ADMINISTRATIVE", "reason": REASON, "affected_obligation_ids": [], "command_block_scope": []}, headers=cmd(bh, detail.headers.get("ETag")), timeout=T)
        step("command accepted while the broker is down (durable receipt, outbox intent)", held.status_code == 201, f"[{held.status_code}] {held.text[:80]}")
        hold = held.json()["data"]
        released = boss.post(f"{BASE}/api/v1/holds/{hold['hold_id']}/release", json={"reason": REASON}, headers=cmd(bh, hold["etag"]), timeout=T)
        step("second command accepted while the broker is down", released.status_code == 200, f"[{released.status_code}]")
        time.sleep(70)  # at least one dispatcher pass (every 60 s) happens while the broker is down
        scheduler_log = docker("logs", "--since", outage_since, "agni-dev-scheduler-1")
        failed_lines = [line for line in scheduler_log.splitlines() if "[dispatch]" in line and "failed=" in line and "failed=0" not in line]
        step("dispatcher recorded failed publishes while the broker was down (intents kept, attempts counted)", bool(failed_lines), failed_lines[-1] if failed_lines else scheduler_log[-200:])
        during = summary(ops)
        # Architecture s.2 / docs 08 s.2: the broker is only a wake-up. The durable fan-out job is
        # enqueued in the database before publishing, so the polling worker still completes the
        # business effect (notifications) without the broker - nothing waits for RabbitMQ.
        step("durable fan-out still completed through the database poll (broker is a wake-up, not the source of truth)", during["by_kind"].get("notification.fanout", 0) >= fanout_before + 2, f"fanout jobs {fanout_before} -> {during['by_kind'].get('notification.fanout', 0)}; outbox pending={during['outbox']['pending']}")
        api_ok = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).status_code == 200
        step("API reads keep working during the broker outage", api_ok)
    finally:
        docker("start", BROKER)
    for _ in range(40):
        time.sleep(3)
        if docker("inspect", "-f", "{{.State.Health.Status}}", BROKER) == "healthy":
            break
    step("broker back and healthy", docker("inspect", "-f", "{{.State.Health.Status}}", BROKER) == "healthy")
    recovered_since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    time.sleep(70)  # one dispatcher pass after recovery
    later = docker("logs", "--since", recovered_since, "agni-dev-scheduler-1")
    new_failures = [line for line in later.splitlines() if "[dispatch]" in line and "failed=" in line and "failed=0" not in line]
    pending = summary(ops)["outbox"]["pending"]
    step("after recovery: no failed publishes and no pending intents", not new_failures and pending == 0, f"pending={pending} new_failures={len(new_failures)} after {int(time.time() - started)}s total")
    after = boss.get(f"{BASE}/api/v1/applications/{app_id}", timeout=T).json()["data"]
    timeline = boss.get(f"{BASE}/api/v1/applications/{app_id}/timeline", timeout=T).json()["data"]["items"]
    started_events = [e for e in timeline if e["event_type"] == "case.hold_started.v1"]
    released_events = [e for e in timeline if e["event_type"] == "case.hold_released.v1"]
    step("case state consistent after the drill (hold released once, events not duplicated)", after["on_hold"] is False and len(started_events) == len(released_events) >= 1, f"started={len(started_events)} released={len(released_events)}")
    print("BROKER OUTAGE DRILL PASSED")


if __name__ == "__main__":
    main()
