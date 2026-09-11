"""Adapter selection from settings. `s3` is the only storage adapter allowed in deployed
environments (production settings refuse anything else); `memory` serves hermetic tests.
`clamav` speaks the clamd INSTREAM protocol; `demo_eicar` is the local test scanner."""

from __future__ import annotations

from django.conf import settings

from agni.platform.errors import DependencyUnavailable

from ..ports import MalwareScanner, ObjectStore
from .memory import MemoryObjectStore
from .s3 import S3ObjectStore
from .scanners import ClamdScanner, DemoEicarScanner


def get_object_store() -> ObjectStore:
    provider = settings.OBJECT_STORE_PROVIDER
    if provider == "s3":
        return S3ObjectStore.from_settings()
    if provider == "memory":
        return MemoryObjectStore.shared()
    raise DependencyUnavailable(f"Object store provider '{provider}' has no adapter installed")


def get_scanner() -> MalwareScanner:
    provider = settings.SCANNER_PROVIDER
    if provider == "clamav":
        return ClamdScanner(host=settings.SCANNER_HOST, port=settings.SCANNER_PORT)
    if provider == "demo_eicar":
        return DemoEicarScanner()
    raise DependencyUnavailable(f"Scanner provider '{provider}' has no adapter installed")
