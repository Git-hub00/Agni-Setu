"""Database connection bounds (G-06): connect timeout, server-side statement timeout and the
per-request health check are configured from the environment; migrations can switch the
statement timeout off. Nothing here connects to a database."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

_MODULE = "config.settings.base"
_ENV_KEYS = ("DB_STATEMENT_TIMEOUT_MS", "DB_CONNECT_TIMEOUT_SECONDS", "DB_CONN_MAX_AGE")


@pytest.fixture
def clean_base_module() -> Iterator[None]:
    saved = sys.modules.pop(_MODULE, None)
    yield
    sys.modules.pop(_MODULE, None)
    if saved is not None:
        sys.modules[_MODULE] = saved


def _load(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> ModuleType:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.import_module(_MODULE)


@pytest.mark.usefixtures("clean_base_module")
def test_defaults_bound_every_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch, {})
    default = module.DATABASES["default"]
    assert default["OPTIONS"]["connect_timeout"] == 5
    assert default["OPTIONS"]["options"] == "-c statement_timeout=30000"
    assert default["CONN_HEALTH_CHECKS"] is True
    assert default["CONN_MAX_AGE"] == 60


@pytest.mark.usefixtures("clean_base_module")
def test_environment_tunes_the_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(
        monkeypatch,
        {"DB_STATEMENT_TIMEOUT_MS": "15000", "DB_CONNECT_TIMEOUT_SECONDS": "3"},
    )
    options = module.DATABASES["default"]["OPTIONS"]
    assert options == {"connect_timeout": 3, "options": "-c statement_timeout=15000"}


@pytest.mark.usefixtures("clean_base_module")
def test_zero_disables_the_statement_timeout_for_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(monkeypatch, {"DB_STATEMENT_TIMEOUT_MS": "0"})
    options = module.DATABASES["default"]["OPTIONS"]
    assert "options" not in options
    assert options["connect_timeout"] == 5
    assert module.DB_STATEMENT_TIMEOUT_MS == 0
