"""B19 acceptance runner: executes every role-journey smoke script against the running local
stack in the documented order (infra/compose/README.md), one after another, and records a
PASS / FAIL table with durations and per-script logs under evidence/. It is the API-and-database
level of the demonstration acceptance (docs/13 s.8 scenarios, docs/11 s.5 journeys); the browser
level is `corepack pnpm --dir web test:e2e`.

Every script talks to the real containers (api, worker, scheduler, PostgreSQL, object store,
Keycloak) with synthetic personas; nothing is mocked and nothing real is sent. A script failing
is reported, never hidden; the exit code is 1 if any step failed.

Usage (repository root):
  uv run --directory backend python ../scripts/dev/acceptance_run.py [--base http://127.0.0.1:5173]
      [--only identity,drafts,...] [--skip-oidc]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence"

# (name, script, extra args, scenarios / journeys it exercises)
SEQUENCE: list[tuple[str, str, list[str], str]] = [
    ("identity", "smoke_identity.py", ["--oidc"], "FR-01/02 sign-in, replay refusal, logout; staff OIDC"),
    ("policy", "smoke_policy.py", ["--oidc"], "DS-18 policy draft / simulate / submit / independent approval / activation"),
    ("drafts", "smoke_drafts.py", [], "DS-02 drafts, uploads, scan states, version conflicts"),
    ("submission", "smoke_submission.py", ["--scan-via-demo", "--oidc"], "DS-01 part 1 / E2E-01 E2E-02 E2E-03 E2E-04 atomic submission, receipt, same-key retry, routing exception, timeline"),
    ("inspections", "smoke_inspections.py", [], "DS-05 DS-06 DS-10 / E2E-05 E2E-06 scheduling, overlap conflict, check-in, failed visit, follow-up attempt"),
    ("reports", "smoke_reports.py", [], "DS-01 part 2 / E2E-07 evidence, draft, accepted report -> REVIEW_PENDING"),
    ("notices", "smoke_notices.py", ["--scan-via-demo"], "DS-03 DS-04 / E2E-08 E2E-09 notices, responses, review return, verified closure, reinspection"),
    ("clocks", "smoke_clocks.py", [], "DS-12 DS-13 obligations, escalation, scheduler + dispatcher, notifications, operations"),
    ("offline", "smoke_offline.py", [], "DS-07 DS-08 DS-09 / E2E-10 E2E-11 offline package, sync replay, tamper refusal, conflict resolution"),
    ("decisions", "smoke_decisions.py", [], "DS-01 part 3 / DS-14 / E2E-13 decision, issuance job, sample PDF, registry, public verification"),
    ("lifecycle", "smoke_lifecycle.py", [], "DS-16 DS-17 DS-21 / E2E-15 E2E-16 E2E-20 status instruments, renewal, hold, support, appeal referral, withdrawal"),
    ("reporting", "smoke_reporting.py", [], "DS-20 / E2E-19 metrics, exports, audited audit search, grants, recovery permissions"),
    ("integrations", "smoke_integrations.py", [], "DS-24 signed partner events, duplicates, gaps, probes, resolution"),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument("--only", default="", help="comma-separated subset of step names")
    parser.add_argument("--skip-oidc", action="store_true", help="drop --oidc flags (no Keycloak)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per script")
    options = parser.parse_args(argv)
    only = {name.strip() for name in options.only.split(",") if name.strip()}
    EVIDENCE.mkdir(exist_ok=True)

    started_at = datetime.now(UTC)
    results: list[tuple[str, str, float, str]] = []
    for name, script, extra, covers in SEQUENCE:
        if only and name not in only:
            continue
        args = [a for a in extra if not (options.skip_oidc and a == "--oidc")]
        log_path = EVIDENCE / f"B19-smoke-{name}.log"
        command = ["uv", "run", "--directory", str(ROOT / "backend"), "python", str(ROOT / "scripts" / "dev" / script), options.base, *args]
        print(f"[acceptance] {name:13s} {script} {' '.join(args)}", flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=options.timeout, check=False)
            output, code = result.stdout + result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = f"{exc.stdout or ''}{exc.stderr or ''}\nTIMEOUT after {options.timeout}s", 124
        elapsed = time.monotonic() - started
        log_path.write_text(f"# {script} {' '.join(args)} @ {datetime.now(UTC).isoformat(timespec='seconds')} exit {code} in {elapsed:.1f}s\n{output}", encoding="utf-8")
        status = "PASS" if code == 0 else "FAIL"
        last = next((line for line in reversed(output.strip().splitlines()) if line.strip()), "")
        results.append((name, status, elapsed, last[:120]))
        print(f"[acceptance] {name:13s} {status} {elapsed:6.1f}s  {last[:100]}", flush=True)

    print("\n| Step | Result | Seconds | Covers | Last line |\n| --- | --- | --- | --- | --- |")
    covers_by_name = {name: covers for name, _, _, covers in SEQUENCE}
    for name, status, elapsed, last in results:
        print(f"| {name} | {status} | {elapsed:.0f} | {covers_by_name[name]} | {last.replace('|', '/')} |")
    failed = [name for name, status, _, _ in results if status != "PASS"]
    total = (datetime.now(UTC) - started_at).total_seconds()
    print(f"\n[acceptance] {len(results) - len(failed)}/{len(results)} steps passed in {total:.0f}s; failed: {failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
