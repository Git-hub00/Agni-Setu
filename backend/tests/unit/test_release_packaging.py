"""Packaging contract tests for the production-shaped stack (task card B18; docs/12 s.2, s.5).

These read the committed packaging files, so a change that publishes a private port, drops the
read-only root filesystem, re-enables start-up migrations or leaves a job kind unserved by the
two worker pools fails here before any image is built.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.management import CommandError

from agni.platform import jobs
from agni.platform.management.commands.process_jobs import selected_kinds

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ROOT / "infra" / "containers" / "production"
COMPOSE = PRODUCTION / "compose.prod.yml"


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return data


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = compose["services"]
    return services


def _command_kinds(service: dict[str, Any], flag: str) -> list[str]:
    command: list[str] = service["command"]
    return [command[i + 1] for i, token in enumerate(command) if token == flag]


def test_every_service_is_hardened(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        assert service.get("read_only") is True, f"{name} must run with a read-only root filesystem"
        assert service.get("cap_drop") == ["ALL"], f"{name} must drop every capability"
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert service.get("tmpfs"), f"{name} needs an explicit writable tmpfs"
        assert service.get("logging", {}).get("options", {}).get("max-size"), f"{name} log rotation"


def test_only_the_web_front_end_publishes_a_port(compose: dict[str, Any]) -> None:
    published = {
        name: svc.get("ports") for name, svc in _services(compose).items() if svc.get("ports")
    }
    assert set(published) == {"web"}
    bindings: list[str] = published["web"] or []
    assert len(bindings) == 1, bindings
    assert bindings[0].startswith("${WEB_BIND_ADDRESS:-127.0.0.1}:"), bindings


def test_application_services_use_production_settings_without_startup_migrations(
    compose: dict[str, Any],
) -> None:
    for name, service in _services(compose).items():
        if name == "web":
            continue
        environment = service["environment"]
        assert environment["DJANGO_SETTINGS_MODULE"] == "config.settings.production", name
        assert environment["RUN_MIGRATIONS_ON_START"] == "false", name
        (env_file,) = service["env_file"]
        assert env_file.startswith("${AGNI_ENV_FILE:?"), (
            f"{name}: secrets come from the rendered env file"
        )


def test_images_are_release_variables_never_tags(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        image: str = service["image"]
        assert re.fullmatch(r"\$\{AGNI_(API|WEB)_IMAGE:\?.*\}", image), f"{name}: {image}"
        assert "build" not in service, f"{name} must not build in production"


def test_migrate_is_a_one_shot_release_step(compose: dict[str, Any]) -> None:
    migrate = _services(compose)["migrate"]
    assert migrate["profiles"] == ["release"]
    assert migrate["restart"] == "no"
    assert migrate["command"][-2:] == ["migrate", "--noinput"]


def test_worker_pools_partition_every_registered_job_kind(compose: dict[str, Any]) -> None:
    services = _services(compose)
    heavy = _command_kinds(services["worker-heavy"], "--kind")
    light_excluded = _command_kinds(services["worker-light"], "--exclude-kind")
    registered = set(jobs.handlers())
    assert set(heavy) == set(light_excluded), (
        "the heavy pool must serve exactly what the light pool excludes"
    )
    assert set(heavy) <= registered, f"unknown kinds in the heavy pool: {set(heavy) - registered}"
    assert "--kind" not in services["worker-light"]["command"]
    assert registered - set(heavy), "the light pool must have kinds left to serve"
    assert {"certificate.issue", "document.scan", "export.generate"} == set(heavy)


def test_stop_grace_exceeds_the_job_lease(compose: dict[str, Any], settings: Any) -> None:
    for name in ("worker-light", "worker-heavy"):
        grace = _services(compose)[name]["stop_grace_period"]
        assert int(grace.rstrip("s")) > settings.AGNI_JOBS["LEASE_SECONDS"], name


def test_selected_kinds_include_exclude_and_refusals() -> None:
    registered = ["a.one", "b.two", "c.three"]
    assert selected_kinds(registered=registered, include=None, exclude=None) is None
    assert selected_kinds(registered=registered, include=["b.two"], exclude=None) == ["b.two"]
    assert selected_kinds(registered=registered, include=None, exclude=["b.two"]) == [
        "a.one",
        "c.three",
    ]
    with pytest.raises(CommandError, match="unknown job kind"):
        selected_kinds(registered=registered, include=["typo.kind"], exclude=None)
    with pytest.raises(CommandError, match="mutually exclusive"):
        selected_kinds(registered=registered, include=["a.one"], exclude=["b.two"])


@pytest.mark.django_db
def test_process_jobs_once_surfaces_a_lost_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--once` callers (scripts, tests) must see the error; only `--loop` retries."""
    from django.core.management import call_command
    from django.db import OperationalError

    def lost(**_kwargs: Any) -> None:
        raise OperationalError("could not translate host name")

    monkeypatch.setattr(jobs, "run_due_jobs", lost)
    with pytest.raises(OperationalError):
        call_command("process_jobs", "--once")


def test_production_env_example_holds_placeholders_only() -> None:
    text = (PRODUCTION / "production.env.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1)
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for key in (
        "DJANGO_SECRET_KEY",
        "OTP_PEPPER",
        "CONTACT_LOOKUP_KEY",
        "DATA_ENCRYPTION_KEY",
        "OBJECT_SECRET_KEY",
        "OIDC_CLIENT_SECRET",
    ):
        assert values[key].startswith("<") and values[key].endswith(">"), key
    assert values["ENABLE_DEMO_CONTROLS"] == "false"
    assert values["CSRF_TRUSTED_ORIGINS"].startswith("https://")
    assert "*" not in values["ALLOWED_HOSTS"]
    assert values["INTEGRATION_DEMO_SECRETS"] == ""


def test_release_workflow_is_manual_and_approval_gated() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    triggers = workflow.get("on") or workflow.get(True)  # PyYAML reads the bare key `on` as True
    assert list(triggers) == ["workflow_dispatch"]
    publish = workflow["jobs"]["publish"]
    assert publish["environment"]["name"] == "production"
    assert publish["needs"] == "build"
    assert workflow["jobs"]["build"]["needs"] == "verify"
    assert "deploy" not in " ".join(step.get("name", "") for step in publish["steps"]).lower()
