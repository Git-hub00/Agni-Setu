"""Typed ports for private object storage and malware scanning (integrations s.2). Application
code depends on these; adapters live in `documents.adapters`."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str | None
    version_id: str  # provider-opaque identity of the exact bytes (ETag or native version)


class ObjectStoreError(Exception):
    """Base class; subclasses tell the caller whether to retry."""


class ObjectNotFound(ObjectStoreError):
    pass


class ObjectStoreUnavailable(ObjectStoreError):
    """Transient provider failure: retry later, never treat as success or as not-found."""


class ObjectTooLarge(ObjectStoreError):
    pass


class ObjectStore(Protocol):
    name: str

    def put_staging(self, key: str, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        """Stream bytes to a temporary key, hashing server-side; refuse beyond `max_bytes`."""

    def head(self, key: str) -> StoredObject | None:
        """Trusted metadata for an existing key (size + version id), or None."""

    def read(self, key: str, *, max_bytes: int) -> Iterator[bytes]:
        """Stream the object; raise ObjectNotFound / ObjectStoreUnavailable / ObjectTooLarge."""

    def promote(self, staging_key: str, final_key: str, *, expected_size: int) -> StoredObject:
        """Copy staged bytes to a never-overwritten final key. An existing final object is
        reused only when its size matches (content-addressed identity); nothing replaces it."""

    def delete(self, key: str) -> None:
        """Best-effort removal of a staging key; final keys are never deleted here."""


@dataclass(frozen=True)
class ScanResult:
    verdict: str  # CLEAN | REJECTED | UNKNOWN
    engine: str
    engine_version: str
    detail: str
    at: datetime


class MalwareScanner(Protocol):
    name: str

    def scan(self, chunks: Iterable[bytes], *, at: datetime) -> ScanResult:
        """Return CLEAN, REJECTED or UNKNOWN. Timeouts and outages are UNKNOWN, never CLEAN."""
