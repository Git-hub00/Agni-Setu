"""In-memory object store for hermetic tests. Implements the same never-overwrite semantics as
the S3 adapter so the command tests exercise the real contract."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Iterator

from ..ports import ObjectNotFound, ObjectTooLarge, StoredObject


class MemoryObjectStore:
    name = "memory"
    _instance: MemoryObjectStore | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self.fail_next_read = False  # test hook: simulate a transient storage outage

    @classmethod
    def shared(cls) -> MemoryObjectStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = cls()

    def put_staging(self, key: str, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        digest = hashlib.sha256()
        buffer = bytearray()
        for chunk in chunks:
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise ObjectTooLarge(f"upload exceeds {max_bytes} bytes")
            digest.update(chunk)
        data = bytes(buffer)
        self._objects[key] = data
        return StoredObject(
            key=key, size=len(data), sha256=digest.hexdigest(), version_id=_etag(data)
        )

    def head(self, key: str) -> StoredObject | None:
        data = self._objects.get(key)
        if data is None:
            return None
        return StoredObject(key=key, size=len(data), sha256=None, version_id=_etag(data))

    def read(self, key: str, *, max_bytes: int) -> Iterator[bytes]:
        if self.fail_next_read:
            self.fail_next_read = False
            from ..ports import ObjectStoreUnavailable

            raise ObjectStoreUnavailable("simulated storage outage")
        data = self._objects.get(key)
        if data is None:
            raise ObjectNotFound(key)
        if len(data) > max_bytes:
            raise ObjectTooLarge(key)
        for start in range(0, len(data), 65536):
            yield data[start : start + 65536]

    def promote(self, staging_key: str, final_key: str, *, expected_size: int) -> StoredObject:
        data = self._objects.get(staging_key)
        if data is None:
            raise ObjectNotFound(staging_key)
        existing = self._objects.get(final_key)
        if existing is not None:
            if len(existing) != expected_size:
                raise ObjectTooLarge(f"final key {final_key} exists with a different size")
            return StoredObject(final_key, len(existing), None, _etag(existing))
        self._objects[final_key] = data  # never overwritten afterwards
        return StoredObject(final_key, len(data), None, _etag(data))

    def delete(self, key: str) -> None:
        if key.startswith("staging/"):
            self._objects.pop(key, None)

    # test helpers
    def overwrite_for_test(self, key: str, data: bytes) -> None:
        """Simulates an out-of-band byte replacement attack (never a supported operation)."""
        self._objects[key] = data


def _etag(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()
