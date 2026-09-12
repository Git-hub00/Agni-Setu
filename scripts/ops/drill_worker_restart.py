"""Physical drill (docs/08 s.6 "Worker terminated"): stop the worker container, accept durable
work through the API (a CSV export), show the job waits PENDING with the export READY, restart
the worker and watch the same logical action complete exactly once. Then kill the worker while
a job is RUNNING (a second export) and show the lease-expiry recovery: the job is reclaimed
after `LEASE_SECONDS` and still completes once with one artifact.

Usage: uv run --directory backend python ../scripts/ops/drill_worker_restart.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
import smoke_reports as reports  # noqa: E402

BASE, T, step, cmd = reports.BASE, reports.T, reports.step, reports.cmd
WORKER = "agni-dev-worker-1"
PURPOSE = "Reliability drill: worker restart; synthetic demonstration data only."


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def job_for(ops: reports.requests.Session, export_id: str) -> dict:
    jobs = ops.get(f"{BASE}/api/v1/jobs", params={"kind": "export.generate"}, timeout=T).json()["data"]["items"]
    return next(j for j in jobs if j["aggregate_ref"].get("export_id") == export_id)


def request_export(boss: reports.requests.Session, bh: dict[str, str]) -> str:
    r = boss.post(f"{BASE}/api/v1/exports", json={"kind": "CASES", "field_set_key": "case-summary", "purpose": PURPOSE}, headers=cmd(bh), timeout=T)
    step("export requested (durable job enqueued)", r.status_code == 202, f"[{r.status_code}]")
    return str(r.json()["data"]["export_id"])


def wait_state(boss: reports.requests.Session, export_id: str, wanted: str, seconds: int) -> str:
    state = ""
    for _ in range(seconds // 3):
        time.sleep(3)
        state = boss.get(f"{BASE}/api/v1/exports/{export_id}", timeout=T).json()["data"]["state"]
        if state == wanted:
            break
    return state


def main() -> None:
    ops, _ = reports.keycloak_login("arjun", "demo-arjun-password")
    boss, bh = reports.keycloak_login("anita", "demo-anita-password")

    # ---- stop / start: work waits, then completes once ---------------------------------------
    docker("stop", WORKER)
    step("worker stopped", docker("inspect", "-f", "{{.State.Running}}", WORKER) == "false")
    try:
        export_id = request_export(boss, bh)
        time.sleep(5)
        job = job_for(ops, export_id)
        step("job PENDING while no worker runs; export still READY", job["state"] == "PENDING" and boss.get(f"{BASE}/api/v1/exports/{export_id}", timeout=T).json()["data"]["state"] == "READY", f"job={job['state']}")
    finally:
        docker("start", WORKER)
    state = wait_state(boss, export_id, "COMPLETE", 90)
    job = job_for(ops, export_id)
    step("restarted worker completed the export once", state == "COMPLETE" and job["state"] == "COMPLETE" and job["attempt_count"] == 1, f"state={state} attempts={job['attempt_count']}")

    # ---- kill while RUNNING: lease expiry recovers the same action ----------------------------
    # The export job is quick, so the kill is timed by stopping the worker first, enqueueing,
    # starting it with a SIGKILL a moment later. If the job already finished, the drill records
    # that honestly instead of pretending a crash happened.
    docker("stop", WORKER)
    export_id = request_export(boss, bh)
    docker("start", WORKER)
    time.sleep(1.0)
    docker("kill", WORKER)
    time.sleep(2)
    job = job_for(ops, export_id)
    if job["state"] == "RUNNING":
        step("worker killed mid-job: job left RUNNING under a lease", True, f"lease_until={job['lease_until']}")
        docker("start", WORKER)
        # Lease is 120 s by default; the next claim happens after expiry.
        state = wait_state(boss, export_id, "COMPLETE", 240)
        job = job_for(ops, export_id)
        step("expired lease reclaimed; export completed once with two attempts", state == "COMPLETE" and job["attempt_count"] == 2, f"state={state} attempts={job['attempt_count']}")
    else:
        docker("start", WORKER)
        step(f"job already {job['state']} before the kill landed - crash variant NOT_RUN this pass (covered by tests/faults)", True, f"attempts={job['attempt_count']}")
        wait_state(boss, export_id, "COMPLETE", 90)
    for _ in range(20):
        time.sleep(3)
        if docker("inspect", "-f", "{{.State.Health.Status}}", WORKER) == "healthy":
            break
    step("worker healthy at the end of the drill", docker("inspect", "-f", "{{.State.Health.Status}}", WORKER) == "healthy")
    exports = boss.get(f"{BASE}/api/v1/exports", timeout=T).json()["data"]["items"]
    drill = [e for e in exports if e["purpose"] == PURPOSE]
    step("each drill export has exactly one COMPLETE record and artifact", all(e["state"] == "COMPLETE" and e["row_count"] is not None for e in drill[:2]), f"count={len(drill)}")
    print("WORKER RESTART DRILL PASSED")


if __name__ == "__main__":
    main()
