"""Release evidence generator (docs/19 s.6 "release evidence required"; docs/12 s.2 "attach an
SBOM", s.5 "immutable image digests"). Produces, for one release identifier:

  release/<version>/manifest.json        commit, lockfile hashes, image ids / digests, SBOM
                                         hashes, scan summary, migration heads, tool versions
  release/<version>/sbom-python.cdx.json CycloneDX 1.5 from backend/uv.lock (runtime only)
  release/<version>/sbom-web.cdx.json    CycloneDX 1.5 from web/pnpm-lock.yaml (runtime graph,
                                         dev packages marked scope=excluded)
  evidence/release/<version>/            image SBOMs (Trivy CycloneDX) and vulnerability reports
                                         (large, gitignored; their sha256 is in the manifest)

Image SBOM + scan use Trivy in a container (`docker save` archive as input) when Docker is
available and `--scan` is given; otherwise the manifest records NOT_RUN with the reason. No step
needs credentials; nothing is pushed anywhere. Usage (repository root):

  uv run --directory backend python ../scripts/ops/release_manifest.py --version v0.18.0 \
      --api-image agni-setu-api:dev --web-image agni-setu-web:dev [--scan] [--trivy aquasec/trivy:0.74.0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCKS = (
    "backend/uv.lock",
    "backend/requirements.txt",
    "backend/pyproject.toml",
    "web/pnpm-lock.yaml",
    "web/package.json",
    "infra/images.lock.json",
)
DOCKERFILES = (
    "infra/containers/api.Dockerfile",
    "infra/containers/web.Dockerfile",
    "infra/containers/production/compose.prod.yml",
)


def log(message: str) -> None:
    print(f"[release] {message}", flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    args: list[str], *, cwd: Path = ROOT, check: bool = True, timeout: int = 3600
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(args[:5])} ...\n{result.stderr[-2000:]}"
        )
    return result


def git_state() -> dict[str, Any]:
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    dirty = run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
    describe = run(["git", "describe", "--tags", "--always", "--dirty"], check=False).stdout.strip()
    return {
        "commit": head,
        "branch": branch,
        "describe": describe,
        "tracked_changes_pending": bool(dirty),
    }


# ---- Python SBOM -----------------------------------------------------------------------------
def python_sbom(out: Path) -> dict[str, Any]:
    run(
        [
            "uv",
            "export",
            "--directory",
            str(ROOT / "backend"),
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "cyclonedx1.5",
            "-o",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    components = data.get("components", [])
    return {
        "file": out.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(out),
        "components": len(components),
        "generator": "uv export --format cyclonedx1.5 (runtime dependencies only)",
    }


# ---- Web SBOM from pnpm-lock.yaml (lockfile v9) --------------------------------------------
def _split_key(key: str) -> tuple[str, str]:
    # 'name@1.2.3' or '@scope/name@1.2.3(peer@x)' -> (name, version)
    base = key.split("(", 1)[0]
    at = base.rfind("@")
    return base[:at], base[at + 1 :]


def web_sbom(out: Path) -> dict[str, Any]:
    # pnpm 12 writes two YAML documents: the package-manager's own dependencies (pnpm exe) and
    # the project lock. Merge them, later documents winning per key, so the project importer,
    # packages and snapshots are complete; the pnpm binaries are not reachable from the project
    # roots and therefore never become components.
    lock: dict[str, Any] = {}
    for document in yaml.safe_load_all((ROOT / "web" / "pnpm-lock.yaml").read_text(encoding="utf-8")):
        for key, value in (document or {}).items():
            if isinstance(value, dict) and isinstance(lock.get(key), dict):
                lock[key] = {**lock[key], **value}
            else:
                lock[key] = value
    version = str(lock.get("lockfileVersion", "?"))
    importer = lock.get("importers", {}).get(".", {})
    packages: dict[str, Any] = lock.get("packages", {})
    snapshots: dict[str, Any] = lock.get("snapshots", {})

    def resolve(name: str, spec: dict[str, Any]) -> str:
        return f"{name}@{spec['version']}"

    runtime_roots = [resolve(n, s) for n, s in (importer.get("dependencies") or {}).items()]
    dev_roots = [resolve(n, s) for n, s in (importer.get("devDependencies") or {}).items()]

    def closure(roots: list[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            snap = snapshots.get(key) or {}
            for dep_name, dep_version in {
                **(snap.get("dependencies") or {}),
                **(snap.get("optionalDependencies") or {}),
            }.items():
                stack.append(f"{dep_name}@{dep_version}")
        return seen

    runtime = closure(runtime_roots)
    everything = runtime | closure(dev_roots)
    components = []
    for key in sorted(everything):
        name, ver = _split_key(key)
        meta = packages.get(key.split("(", 1)[0], {})
        integrity = (meta.get("resolution") or {}).get("integrity")
        component: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": ver,
            "purl": f"pkg:npm/{name}@{ver}",
            "scope": "required" if key in runtime else "excluded",
        }
        if integrity and integrity.startswith("sha512-"):
            import base64

            component["hashes"] = [
                {"alg": "SHA-512", "content": base64.b64decode(integrity[7:]).hex()}
            ]
        components.append(component)
    web_pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "tools": [{"name": "agni release_manifest.py (pnpm-lock.yaml parser)", "version": "1"}],
            "component": {
                "type": "application",
                "name": web_pkg.get("name", "agni-setu-web"),
                "version": web_pkg.get("version", "0.0.0"),
            },
            "properties": [{"name": "agni:pnpm-lockfile-version", "value": version}],
        },
        "components": components,
    }
    out.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
    return {
        "file": out.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(out),
        "components": len(components),
        "runtime_components": len(runtime),
        "generator": f"pnpm-lock.yaml v{version} graph (scope=required for the runtime closure, excluded for dev-only)",
    }


# ---- Images ----------------------------------------------------------------------------------
def image_record(ref: str) -> dict[str, Any]:
    inspect = run(["docker", "image", "inspect", ref], check=False)
    if inspect.returncode != 0:
        return {"reference": ref, "status": "NOT_FOUND"}
    data = json.loads(inspect.stdout)[0]
    return {
        "reference": ref,
        "image_id": data["Id"],
        "repo_digests": data.get("RepoDigests") or [],
        "created": data.get("Created"),
        "size_bytes": data.get("Size"),
        "user": (data.get("Config") or {}).get("User"),
        "labels": (data.get("Config") or {}).get("Labels") or {},
        "note": "repo_digests is empty for a locally built image; the registry digest is recorded by the release workflow after push",
    }


def trivy(
    image: str, name: str, evidence_dir: Path, trivy_image: str, timeout_minutes: int
) -> dict[str, Any]:
    """Image SBOM + vulnerability report through a Trivy container.

    The image is exported with `docker save` and scanned from the tar (`--input`): on a small
    Docker Desktop VM the socket-based export inside Trivy repeatedly hit its context deadline,
    while a saved archive scans reliably and needs no socket in the scanner container.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    archive = evidence_dir / f"image-{name}.tar"
    saved = run(["docker", "save", "-o", str(archive), image], check=False, timeout=1800)
    if saved.returncode != 0:
        return {"status": "FAILED", "step": "docker save", "stderr": saved.stderr[-500:]}
    base = [
        "docker",
        "run",
        "--rm",
        "-v",
        "agni-trivy-cache:/root/.cache",
        "-v",
        f"{evidence_dir.resolve()}:/out",
        trivy_image,
    ]
    version = run([*base, "--version"], check=False).stdout.strip().splitlines()[:1]
    sbom_name = f"sbom-image-{name}.cdx.json"
    report_name = f"scan-image-{name}.json"
    common = [
        "image",
        "--timeout",
        f"{timeout_minutes}m",
        "--quiet",
        "--input",
        f"/out/{archive.name}",
    ]
    sbom = run(
        [*base, *common, "--format", "cyclonedx", "--output", f"/out/{sbom_name}"],
        check=False,
        timeout=timeout_minutes * 60 + 120,
    )
    scan = run(
        [
            *base,
            *common,
            "--scanners",
            "vuln",
            "--format",
            "json",
            "--output",
            f"/out/{report_name}",
        ],
        check=False,
        timeout=timeout_minutes * 60 + 120,
    )
    archive.unlink(missing_ok=True)
    record: dict[str, Any] = {
        "tool": version[0] if version else trivy_image,
        "seconds": round(time.monotonic() - started, 1),
    }
    sbom_path, report_path = evidence_dir / sbom_name, evidence_dir / report_name
    record["sbom"] = (
        {"file": sbom_path.relative_to(ROOT).as_posix(), "sha256": sha256_file(sbom_path)}
        if sbom.returncode == 0 and sbom_path.is_file()
        else {"status": "FAILED", "stderr": sbom.stderr[-500:]}
    )
    if scan.returncode == 0 and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        counts: dict[str, int] = {}
        findings = []
        for result in report.get("Results") or []:
            for vuln in result.get("Vulnerabilities") or []:
                sev = vuln.get("Severity", "UNKNOWN")
                counts[sev] = counts.get(sev, 0) + 1
                if sev in ("HIGH", "CRITICAL"):
                    findings.append(
                        {
                            "id": vuln.get("VulnerabilityID"),
                            "package": vuln.get("PkgName"),
                            "installed": vuln.get("InstalledVersion"),
                            "fixed": vuln.get("FixedVersion") or None,
                            "severity": sev,
                            "target": result.get("Target"),
                            "class": result.get("Class"),
                        }
                    )
        record["scan"] = {
            "file": report_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(report_path),
            "severity_counts": counts,
            "high_and_critical": findings,
            "os": (report.get("Metadata") or {}).get("OS"),
        }
    else:
        record["scan"] = {"status": "FAILED", "stderr": scan.stderr[-500:]}
    return record


# ---- Migrations ------------------------------------------------------------------------------
def migration_heads() -> dict[str, str]:
    heads: dict[str, str] = {}
    for migrations in sorted((ROOT / "backend" / "agni").glob("*/migrations")):
        files = sorted(p.stem for p in migrations.glob("[0-9]*.py"))
        if files:
            heads[migrations.parent.name] = files[-1]
    return heads


def tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {
        "python_host": platform.python_version(),
        "platform": platform.platform(),
    }
    for label, args in (
        ("uv", ["uv", "--version"]),
        ("docker", ["docker", "--version"]),
        ("compose", ["docker", "compose", "version"]),
        ("pnpm", ["corepack", "pnpm", "--version"]),
    ):
        # `shutil.which` resolves Windows launchers such as corepack.cmd; a missing tool is
        # recorded as NOT_RUN instead of aborting the manifest.
        executable = shutil.which(args[0])
        if executable is None:
            versions[label] = "NOT_RUN (not installed)"
            continue
        result = run([executable, *args[1:]], check=False, timeout=60)
        versions[label] = (
            (result.stdout or result.stderr).strip().splitlines()[0]
            if (result.stdout or result.stderr).strip()
            else "NOT_RUN"
        )
    return versions


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version", required=True, help="release identifier, e.g. v0.18.0 or 2026.09.12-b18"
    )
    parser.add_argument("--api-image", default="agni-setu-api:dev")
    parser.add_argument("--web-image", default="agni-setu-web:dev")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="run Trivy image SBOM + vulnerability scan in a container",
    )
    parser.add_argument(
        "--trivy",
        default="aquasec/trivy:latest",
        help="scanner image reference (record the reported version)",
    )
    parser.add_argument("--scan-timeout-minutes", type=int, default=40)
    options = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", options.version):
        raise SystemExit("version must be a plain identifier")

    out = ROOT / "release" / options.version
    out.mkdir(parents=True, exist_ok=True)
    evidence = ROOT / "evidence" / "release" / options.version
    started = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "schema": "agni-release-manifest/1",
        "version": options.version,
        "created_at": started.isoformat(timespec="seconds"),
        "git": git_state(),
        "locks": {
            path: {"sha256": sha256_file(ROOT / path), "bytes": (ROOT / path).stat().st_size}
            for path in LOCKS
            if (ROOT / path).is_file()
        },
        "packaging_files": {
            path: sha256_file(ROOT / path) for path in DOCKERFILES if (ROOT / path).is_file()
        },
        "images": {"api": image_record(options.api_image), "web": image_record(options.web_image)},
        "migration_heads": migration_heads(),
        "tools": tool_versions(),
    }
    log(
        f"git {manifest['git']['commit'][:12]} ({manifest['git']['branch']}); pending tracked changes: {manifest['git']['tracked_changes_pending']}"
    )
    manifest["sboms"] = {
        "python": python_sbom(out / "sbom-python.cdx.json"),
        "web": web_sbom(out / "sbom-web.cdx.json"),
    }
    log(
        f"python SBOM {manifest['sboms']['python']['components']} components; web SBOM {manifest['sboms']['web']['components']} components ({manifest['sboms']['web']['runtime_components']} runtime)"
    )

    docker_ok = (
        run(
            ["docker", "info", "--format", "{{.ServerVersion}}"], check=False, timeout=60
        ).returncode
        == 0
    )
    if options.scan and docker_ok:
        manifest["image_scan"] = {}
        for name, image in (("api", options.api_image), ("web", options.web_image)):
            log(
                f"trivy: SBOM + vulnerability scan of {image} (may take several minutes on a small VM)"
            )
            manifest["image_scan"][name] = trivy(
                image, name, evidence, options.trivy, options.scan_timeout_minutes
            )
            scan = manifest["image_scan"][name].get("scan", {})
            log(
                f"{name}: {scan.get('severity_counts', scan.get('status'))}; HIGH/CRITICAL {len(scan.get('high_and_critical', []))}"
            )
    else:
        manifest["image_scan"] = {
            "status": "NOT_RUN",
            "reason": "--scan not given" if not options.scan else "docker daemon not reachable",
        }

    manifest["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    log(f"wrote {out.relative_to(ROOT).as_posix()}/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
