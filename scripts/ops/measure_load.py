"""Reduced performance measurement against the running Compose stack (docs/11 s.7 protocol,
scaled down to what a 3 GB Docker Desktop VM can host). Signs in one applicant (real OTP) and
one supervisor (real Keycloak) once, hands the sessions to Locust through the environment,
runs the 70/20/10 workload headless for a bounded time, then prints p50/p95/p99 per request
name, error counts and a `docker stats` snapshot. Records facts; never hides slow samples.

Usage: uv run --directory backend python ../scripts/ops/measure_load.py [http://127.0.0.1:5173] [--users 20] [--spawn 5] [--time 2m]
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
import smoke_reports as reports  # noqa: E402
import smoke_submission as base  # noqa: E402

BASE, T = reports.BASE, reports.T
ROOT = Path(__file__).resolve().parents[2]


def arg(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> None:
    users, spawn, duration = arg("--users", "20"), arg("--spawn", "5"), arg("--time", "2m")
    applicant, _ = base.sign_in_applicant()
    boss, _ = reports.keycloak_login("anita", "demo-anita-password")
    own_cases = [c["application_id"] for c in applicant.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"]]
    staff_cases = [c["application_id"] for c in boss.get(f"{BASE}/api/v1/applications", timeout=T).json()["data"]["items"]][:20]
    env = {
        **os.environ,
        "LOAD_APPLICANT_SESSION": applicant.cookies.get("sessionid", ""),
        "LOAD_APPLICANT_CSRF": applicant.cookies.get("csrftoken", ""),
        "LOAD_STAFF_SESSION": boss.cookies.get("sessionid", ""),
        "LOAD_STAFF_CSRF": boss.cookies.get("csrftoken", ""),
        "LOAD_CASE_IDS": ",".join(own_cases),
        "LOAD_STAFF_CASE_IDS": ",".join(staff_cases),
    }
    out = ROOT / "evidence" / "B17-load"
    out.parent.mkdir(exist_ok=True)
    print(f"[load] users={users} spawn={spawn}/s time={duration} host={BASE} applicant_cases={len(own_cases)} staff_cases={len(staff_cases)}")
    started = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "locust", "-f", "tests/load/locustfile.py", "--headless", "-u", users, "-r", spawn, "-t", duration, "--host", BASE, "--csv", str(out), "--only-summary"],
        cwd=ROOT / "backend",
        env=env,
        text=True,
    )
    print(f"[load] locust exit {result.returncode} after {int(time.time() - started)}s")
    stats = out.with_name("B17-load_stats.csv")
    if stats.exists():
        with stats.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        print(f"{'name':58} {'reqs':>6} {'fails':>5} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}")
        for row in rows:
            print(f"{row['Name'][:58]:58} {row['Request Count']:>6} {row['Failure Count']:>5} {row['50%']:>7} {row['95%']:>7} {row['99%']:>7} {row['Max Response Time']:>7}")
    snapshot = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"], capture_output=True, text=True)
    print(snapshot.stdout)
    failures = out.with_name("B17-load_failures.csv")
    if failures.exists():
        print(failures.read_text()[:2000])


if __name__ == "__main__":
    main()
