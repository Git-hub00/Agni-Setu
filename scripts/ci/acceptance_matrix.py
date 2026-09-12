"""Acceptance coverage matrix generator (task card B19; docs/11 s.3 core cases, s.4 properties,
s.5 journeys, s.12 preservation tests; docs/13 s.8 demonstration scenarios).

Scans the repository for references to the specification identifiers and writes
docs/ACCEPTANCE_MATRIX.md: for every AT-xx-yy (30 FRs x 6 = 180), AT-X-nn, PROP-nn, E2E-nn and
DS-nn it lists WHERE the identifier is exercised (automated tests, browser suite, smoke /
acceptance scripts) and derives an honest label:

  AUTOMATED   referenced by a pytest / vitest / Playwright test (runs in CI or the local gates)
  SMOKE       referenced only by a smoke / acceptance script (runs against the local stack)
  MANUAL      no automated reference; covered by a recorded manual walk (listed in the overrides)
  BLOCKED     cannot run on this host / without an external dependency (reason listed)
  NOT_RUN     nothing references it yet

References are found as explicit ids (`AT-06-02`), ranges in docstrings (`AT-06-01..05`) and
test function names (`test_at_06_01_07_01_...`). A reference is evidence that a test claims the
case, not proof it passed: the run records live in docs/21 and handover B7. Nothing here edits
docs/11. Usage: uv run --directory backend python ../scripts/ci/acceptance_matrix.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "ACCEPTANCE_MATRIX.md"
SCAN = {
    "automated": [ROOT / "backend" / "tests", ROOT / "web" / "src", ROOT / "web" / "e2e"],
    "smoke": [ROOT / "scripts" / "dev", ROOT / "scripts" / "ops"],
}
SUFFIXES = {".py", ".ts", ".tsx"}
FR_TITLES = {
    1: "Applicant identity and account recovery", 2: "Staff provisioning and account lifecycle",
    3: "Service applicability and premises", 4: "Draft creation and editing",
    5: "Document and evidence intake", 6: "Atomic application submission",
    7: "Jurisdiction routing and exceptions", 8: "Assignment and reassignment",
    9: "Case visibility and timeline", 10: "Assisted intake and delegation",
    11: "Appointments and visit outcomes", 12: "Offline drafts and explicit synchronization",
    13: "Versioned inspection report and provenance", 14: "Deterministic checklist evaluation",
    15: "Information requests and deficiency notices", 16: "Applicant response versions",
    17: "Verification, return and reinspection", 18: "Persistent stage and case clocks",
    19: "Reminders and accountable escalation", 20: "Guarded decisions and authority",
    21: "Issuance and external registration", 22: "Privacy-safe public verification",
    23: "Notifications and delivery visibility", 24: "Certificate lifecycle and continuing obligations",
    25: "Operational dashboards and metrics", 26: "Controlled exports",
    27: "Policy and master-data governance", 28: "Business and sensitive-access audit",
    29: "Integration ownership and reconciliation", 30: "Support, withdrawal and profile-dependent appeals",
}
CASE_KIND = {1: "valid workflow", 2: "invalid / blocked", 3: "recovery path", 4: "authorization / privacy", 5: "concurrency / replay", 6: "screen and accessibility"}

# Cases that no automated test can claim on this host, with the exact reason (docs/11 s.9).
BLOCKED: dict[str, str] = {
    "AT-05-05": "real ClamAV scan of concurrent uploads needs the `full` profile RAM (BL-007); the demo scanner and adapter fences are tested",
    "AT-21-01": "external registry / live digital signing has no approved provider (docs/19 gate); the demo watermark signer path is tested end to end",
    "AT-21-03": "live signer reconciliation needs the approved provider sandbox; the simulator reconciliation path is tested (E2E-14 analogue)",
    "AT-23-03": "notification bounce needs a real delivery provider; the demo sink records PENDING/FAILED only",
    "AT-24-05": "external ownership source race needs the partner sandbox; the simulated source ordering is tested",
    "AT-29-01": "no live partner integration is approved; the HMAC contract is proven against the simulator",
    "E2E-14": "unknown live signing outcome needs the provider sandbox; the simulator variant runs in tests/faults and smoke_decisions",
    "DS-15": "same as E2E-14",
    "DS-19": "covered by tests/faults/test_authority_race.py at grant level; a decision-command race needs the two-reviewer fixture (see E2E-12)",
    "DS-23": "screen-reader and camera/GPS-denial walks are manual; the axe + keyboard + viewport suite runs (web/e2e)",
}

# Manual walks recorded during B19 (docs/21 s.3u) for cases with no automated reference.
MANUAL: dict[str, str] = {}

ID_PATTERNS = {
    "AT": re.compile(r"AT-(\d{2}|X)-(\d{2})(?:\.\.(\d{2}))?"),
    "PROP": re.compile(r"PROP-(\d{2})"),
    "E2E": re.compile(r"E2E-(\d{2})"),
    "DS": re.compile(r"DS-(\d{2})"),
}
FUNC_PATTERN = re.compile(r"def test_at_((?:\d{2}_\d{2}_?)+)")


def scan() -> dict[str, dict[str, set[str]]]:
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for layer, roots in SCAN.items():
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in SUFFIXES or "node_modules" in path.parts or "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                rel = path.relative_to(ROOT).as_posix()
                for match in ID_PATTERNS["AT"].finditer(text):
                    fr, first, last = match.group(1), int(match.group(2)), match.group(3)
                    for case in range(first, (int(last) if last else first) + 1):
                        found[f"AT-{fr}-{case:02d}"][layer].add(rel)
                for match in FUNC_PATTERN.finditer(text):
                    digits = [int(d) for d in match.group(1).strip("_").split("_")]
                    for fr, case in zip(digits[0::2], digits[1::2], strict=False):
                        found[f"AT-{fr:02d}-{case:02d}"][layer].add(rel)
                for key in ("PROP", "E2E", "DS"):
                    for match in ID_PATTERNS[key].finditer(text):
                        found[f"{key}-{match.group(1)}"][layer].add(rel)
    return found


def label(identifier: str, refs: dict[str, set[str]]) -> tuple[str, str]:
    if refs.get("automated"):
        return "AUTOMATED", ", ".join(sorted(f"`{r}`" for r in refs["automated"]))
    if refs.get("smoke"):
        return "SMOKE", ", ".join(sorted(f"`{r}`" for r in refs["smoke"]))
    if identifier in MANUAL:
        return "MANUAL", MANUAL[identifier]
    if identifier in BLOCKED:
        return "BLOCKED", BLOCKED[identifier]
    return "NOT_RUN", "no reference in tests or scripts"


def render(found: dict[str, dict[str, set[str]]]) -> str:
    lines = [
        "# Acceptance coverage matrix (generated)",
        "",
        f"Generated by `scripts/ci/acceptance_matrix.py` on {datetime.now(UTC).isoformat(timespec='minutes')} from the repository tree. Labels: AUTOMATED = a pytest / vitest / Playwright test references the case; SMOKE = a smoke or acceptance script exercises it against the local stack; MANUAL = recorded manual walk; BLOCKED = needs a dependency this host / demo cannot provide (reason given); NOT_RUN = nothing references it yet. A reference shows which test claims the case; the actual PASS / FAIL runs are recorded in `docs/21_IMPLEMENTATION_STATUS.md` and `handover.md` B7. Where a test covers only part of a case, the test's own docstring says so.",
        "",
    ]
    counts: dict[str, int] = defaultdict(int)
    lines += ["## 1. Core requirement acceptance cases (docs/11 s.3)", ""]
    for fr in range(1, 31):
        lines += [f"### FR-{fr:02d} - {FR_TITLES[fr]}", "", "| Test | Scenario | Coverage | Evidence |", "| --- | --- | --- | --- |"]
        for case in range(1, 7):
            identifier = f"AT-{fr:02d}-{case:02d}"
            status, evidence = label(identifier, found.get(identifier, {}))
            counts[status] += 1
            lines.append(f"| {identifier} | {CASE_KIND[case]} | {status} | {evidence} |")
        lines.append("")
    for title, key, upper in (("2. Explicit preservation tests (docs/11 s.12)", "AT-X", 5), ("3. State and concurrency properties (docs/11 s.4)", "PROP", 16), ("4. End-to-end journeys (docs/11 s.5)", "E2E", 20), ("5. Demonstration scenarios (docs/13 s.8)", "DS", 24)):
        lines += [f"## {title}", "", "| Id | Coverage | Evidence |", "| --- | --- | --- |"]
        for number in range(1, upper + 1):
            identifier = f"{key}-{number:02d}"
            status, evidence = label(identifier, found.get(identifier, {}))
            counts[f"{key}:{status}"] += 1
            lines.append(f"| {identifier} | {status} | {evidence} |")
        lines.append("")
    core = {k: v for k, v in counts.items() if ":" not in k}
    lines += ["## 6. Totals", "", "| Group | AUTOMATED | SMOKE | MANUAL | BLOCKED | NOT_RUN |", "| --- | --- | --- | --- | --- | --- |"]
    lines.append("| AT (180 core cases) | " + " | ".join(str(core.get(s, 0)) for s in ("AUTOMATED", "SMOKE", "MANUAL", "BLOCKED", "NOT_RUN")) + " |")
    for key in ("AT-X", "PROP", "E2E", "DS"):
        lines.append(f"| {key} | " + " | ".join(str(counts.get(f"{key}:{s}", 0)) for s in ("AUTOMATED", "SMOKE", "MANUAL", "BLOCKED", "NOT_RUN")) + " |")
    lines += ["", "---", "[Documentation index](../README.md) | [Test plan](11_TEST_PLAN_AND_ACCEPTANCE.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed matrix is stale")
    options = parser.parse_args(argv)
    rendered = render(scan())
    body = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("Generated by"))  # noqa: E731
    if options.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if body(current) != body(rendered):
            print("docs/ACCEPTANCE_MATRIX.md is stale; regenerate it", file=sys.stderr)
            return 1
        print("acceptance matrix up to date")
        return 0
    OUT.write_text(rendered, encoding="utf-8")
    totals = rendered.split("## 6. Totals", 1)[1]
    print(totals.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
