"""Secret and unsafe-configuration scan over tracked files (security s.10 release gates).

Fails when a tracked file contains a private key block, a cloud access key, a bearer/JWT-like
token, a URL with embedded credentials, or an assignment of a real-looking secret to a
password/secret/token variable. Known-safe demo/test markers (`demo-`, `test-only`, `local-
insecure`, `changeme`, `<generated`, `example`) are allowlisted because they are documented
placeholders, never real credentials. Runs in CI and in scripts/ci/verify.sh; no network.

Usage: python scripts/ci/scan_secrets.py [--all-files]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAFE_MARKERS = (
    "demo-",
    "test-only",
    "local-insecure",
    "changeme",
    "change-me",
    "<generated",
    "example",
    "placeholder",
    "ci-only",
    "verify-placeholder",
    "not-for-live",
    "your-",
    "xxxx",
    "<",
)
SKIP_SUFFIXES = (".lock", ".png", ".jpg", ".jpeg", ".ico", ".pdf", ".woff", ".woff2", ".svg")
SKIP_PARTS = ("node_modules", ".venv", "dist", "__pycache__", "references")
SKIP_FILES = {"pnpm-lock.yaml", "uv.lock", "MANIFEST.sha256", "scan_secrets.py"}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("JWT-like token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "URL with embedded credentials",
        re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{8,}@[^\s/]+"),
    ),
    (
        "secret assignment",
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?key|token)\b\s*[:=]\s*['\"]([^'\"\s]{16,})['\"]"
        ),
    ),
]


def tracked_files(all_files: bool) -> list[Path]:
    if all_files:
        return [p for p in ROOT.rglob("*") if p.is_file()]
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [ROOT / name for name in output.decode("utf-8").split("\0") if name]


def safe(line: str) -> bool:
    lowered = line.lower()
    if "${" in line or "$(" in line or "{{" in line:
        return True  # shell / Compose / template interpolation, not a literal value
    return any(marker in lowered for marker in SAFE_MARKERS)


def scan(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line) and not safe(line):
                    relative = path.relative_to(ROOT).as_posix()
                    findings.append(f"{relative}:{number}: {label}")
    return findings


def main(argv: list[str]) -> int:
    paths = tracked_files("--all-files" in argv)
    findings = scan(paths)
    if findings:
        print("SECRET SCAN FAILED:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"secret scan: {len(paths)} files, no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
