"""DEF-014: the production boot check must verify that its temporary Compose project is gone.

On 2026-09-13 `docker compose down` under engine memory pressure left `agni-prodcheck-api-1`,
`agni-prodcheck-scheduler-1` and both project networks behind while the script still logged
"check project removed"; with `restart: unless-stopped` the containers came back with the engine.
The teardown now lists what still carries the project label, removes it directly and reports the
result as check B23. Docker is replaced by a recording runner here.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "prod_boot_check.py"


@pytest.fixture(scope="module")
def boot_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prod_boot_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Runner:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        key = " ".join(args[:3])
        return subprocess.CompletedProcess(args, 0, stdout=self.outputs.get(key, ""), stderr="")


def test_leftovers_are_found_by_the_compose_project_label(boot_check: ModuleType) -> None:
    runner = _Runner(
        {
            "docker ps -a": "agni-prodcheck-api-1\nagni-prodcheck-scheduler-1\n",
            "docker network ls": "agni-prodcheck_edge\n\nagni-prodcheck_internal\n",
        }
    )
    found = boot_check.leftover_resources("agni-prodcheck", runner=runner)
    assert found == [
        "container:agni-prodcheck-api-1",
        "container:agni-prodcheck-scheduler-1",
        "network:agni-prodcheck_edge",
        "network:agni-prodcheck_internal",
    ]
    for call in runner.calls:
        assert "label=com.docker.compose.project=agni-prodcheck" in call
    assert runner.calls[0][:3] == ["docker", "ps", "-a"]
    assert runner.calls[1][:3] == ["docker", "network", "ls"]


def test_a_clean_engine_reports_no_leftovers(boot_check: ModuleType) -> None:
    runner = _Runner({})
    assert boot_check.leftover_resources("agni-prodcheck", runner=runner) == []


def test_force_remove_deletes_containers_before_networks(boot_check: ModuleType) -> None:
    runner = _Runner({})
    boot_check.force_remove(
        [
            "container:agni-prodcheck-api-1",
            "network:agni-prodcheck_edge",
            "container:agni-prodcheck-scheduler-1",
        ],
        runner=runner,
    )
    assert runner.calls == [
        ["docker", "rm", "-f", "agni-prodcheck-api-1", "agni-prodcheck-scheduler-1"],
        ["docker", "network", "rm", "agni-prodcheck_edge"],
    ]


def test_force_remove_with_nothing_left_issues_no_docker_command(boot_check: ModuleType) -> None:
    runner = _Runner({})
    boot_check.force_remove([], runner=runner)
    assert runner.calls == []
