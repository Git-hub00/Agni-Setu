"""S3 adapter conformance against the real Compose object store (SeaweedFS). Skipped with an
explicit reason when the endpoint is not reachable; never faked."""

from __future__ import annotations

import hashlib
import socket
import uuid
from urllib.parse import urlparse

import pytest
from django.conf import settings

from agni.documents.adapters.s3 import S3ObjectStore
from agni.documents.ports import ObjectNotFound, ObjectTooLarge


def _reachable(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.django_db
def test_s3_store_put_head_promote_read_never_overwrites() -> None:
    if not (_reachable(settings.OBJECT_ENDPOINT) and settings.OBJECT_ACCESS_KEY):
        pytest.skip(
            f"object store {settings.OBJECT_ENDPOINT or '<unset>'} not reachable (Compose down?)"
        )
    store = S3ObjectStore.from_settings()
    data = b"%PDF-1.7\n" + uuid.uuid4().bytes * 200
    digest = hashlib.sha256(data).hexdigest()
    staging = f"staging/test/{uuid.uuid4()}"
    final = f"objects/{digest}"

    staged = store.put_staging(staging, [data[:100], data[100:]], max_bytes=len(data))
    assert staged.size == len(data) and staged.sha256 == digest
    head = store.head(staging)
    assert head is not None and head.size == len(data)
    with pytest.raises(ObjectTooLarge):
        store.put_staging(f"{staging}-big", [data], max_bytes=len(data) - 1)

    promoted = store.promote(staging, final, expected_size=len(data))
    assert promoted.key == final and promoted.size == len(data) and promoted.version_id
    assert b"".join(store.read(final, max_bytes=len(data))) == data
    with pytest.raises(ObjectTooLarge):
        list(store.read(final, max_bytes=10))
    # Promoting the same content again reuses the final object (content-addressed identity).
    again = store.put_staging(f"{staging}-2", [data], max_bytes=len(data))
    assert again.sha256 == digest
    assert (
        store.promote(f"{staging}-2", final, expected_size=len(data)).version_id
        == promoted.version_id
    )
    # A different size claiming the same final key is refused, never overwritten.
    with pytest.raises(ObjectTooLarge):
        store.promote(f"{staging}-2", final, expected_size=len(data) - 1)
    store.delete(staging)
    store.delete(f"{staging}-2")
    assert store.head(staging) is None
    with pytest.raises(ObjectNotFound):
        list(store.read(staging, max_bytes=len(data)))
    store.delete(final)  # final keys are never deleted by this path
    assert store.head(final) is not None
