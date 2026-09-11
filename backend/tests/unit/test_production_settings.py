"""B01 acceptance: a bad production configuration must fail at import (startup), and a
complete one must load. Architecture s.9 / build guide s.6 / document 19.

The settings modules read the environment at import time, so each case reloads them under a
controlled environment. Nothing here connects to a database.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

GOOD_ENV: dict[str, str] = {
    "APP_ENV": "production",
    "SERVICE_MODE": "DEMO",
    "DJANGO_SECRET_KEY": "x" * 64,
    "ALLOWED_HOSTS": "agni.example.gov.in",
    "CSRF_TRUSTED_ORIGINS": "https://agni.example.gov.in",
    "DATABASE_URL": "postgresql://agni_app:s3cret@db.internal:5432/agni_live",
    "OTP_PROVIDER": "approved_sms_gateway",
    "NOTIFICATION_PROVIDER": "approved_sms_gateway",
    "SIGNING_PROVIDER": "approved_signer",
    "ENABLE_DEMO_CONTROLS": "false",
}

_SETTINGS_MODULES = ("config.settings.base", "config.settings.production")


@pytest.fixture
def clean_settings_modules() -> Iterator[None]:
    """Drop cached settings modules so each test re-imports under its own environment."""
    saved = {name: sys.modules.pop(name, None) for name in _SETTINGS_MODULES}
    yield
    for name in _SETTINGS_MODULES:
        sys.modules.pop(name, None)
    for name, module in saved.items():
        if module is not None:
            sys.modules[name] = module


def _load_production(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> ModuleType:
    for key in list(GOOD_ENV) + ["DEBUG"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.import_module("config.settings.production")


@pytest.mark.usefixtures("clean_settings_modules")
def test_complete_production_configuration_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_production(monkeypatch, GOOD_ENV)
    assert module.DEBUG is False
    assert module.SESSION_COOKIE_SECURE is True
    assert module.CSRF_COOKIE_SECURE is True
    assert module.ALLOWED_HOSTS == ["agni.example.gov.in"]


@pytest.mark.usefixtures("clean_settings_modules")
@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        ({"DJANGO_SECRET_KEY": "short"}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": "local-insecure-" + "x" * 60}, "DJANGO_SECRET_KEY"),
        ({"ALLOWED_HOSTS": "*"}, "ALLOWED_HOSTS"),
        ({"ALLOWED_HOSTS": ""}, "ALLOWED_HOSTS"),
        ({"CSRF_TRUSTED_ORIGINS": "http://agni.example.gov.in"}, "CSRF_TRUSTED_ORIGINS"),
        ({"DATABASE_URL": "postgresql://db.internal:5432/agni_live"}, "DATABASE_URL"),
        ({"SERVICE_MODE": "STAGING"}, "SERVICE_MODE"),
    ],
)
def test_unsafe_production_configuration_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], expected_fragment: str
) -> None:
    with pytest.raises(ImproperlyConfigured) as excinfo:
        _load_production(monkeypatch, {**GOOD_ENV, **overrides})
    assert expected_fragment in str(excinfo.value)


@pytest.mark.usefixtures("clean_settings_modules")
@pytest.mark.parametrize(
    "overrides",
    [
        {"SERVICE_MODE": "LIVE", "OTP_PROVIDER": "demo_sink"},
        {"SERVICE_MODE": "LIVE", "NOTIFICATION_PROVIDER": "console"},
        {"SERVICE_MODE": "LIVE", "SIGNING_PROVIDER": "demo_watermark"},
        {"SERVICE_MODE": "LIVE", "ENABLE_DEMO_CONTROLS": "true"},
        {"SERVICE_MODE": "LIVE", "SIGNING_PROVIDER": ""},
        # B12: the hermetic renderer and the demo number lookup are not live options.
        {"SERVICE_MODE": "LIVE", "CERTIFICATE_RENDERER_PROVIDER": "simulated"},
        {"SERVICE_MODE": "LIVE", "PUBLIC_LOOKUP_PROFILE": "TOKEN_OR_NUMBER"},
    ],
)
def test_live_mode_rejects_demo_sinks_and_demo_controls(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    with pytest.raises(ImproperlyConfigured):
        _load_production(monkeypatch, {**GOOD_ENV, **overrides})


@pytest.mark.usefixtures("clean_settings_modules")
def test_live_mode_with_approved_providers_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_production(monkeypatch, {**GOOD_ENV, "SERVICE_MODE": "LIVE"})
    assert module.SERVICE_MODE == "LIVE"
    assert module.ENABLE_DEMO_CONTROLS is False


@pytest.mark.usefixtures("clean_settings_modules")
def test_all_problems_are_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator should see every misconfiguration in one startup failure."""
    with pytest.raises(ImproperlyConfigured) as excinfo:
        _load_production(
            monkeypatch,
            {**GOOD_ENV, "DJANGO_SECRET_KEY": "", "ALLOWED_HOSTS": "*", "SERVICE_MODE": "BAD"},
        )
    message = str(excinfo.value)
    assert "DJANGO_SECRET_KEY" in message
    assert "ALLOWED_HOSTS" in message
    assert "SERVICE_MODE" in message
