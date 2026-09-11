"""S3-compatible private object store (ADR-08). Locally this is SeaweedFS behind Compose; in a
deployment it is the approved private bucket. Keys are server-generated: `staging/<...>` for
bounded uploads in flight and `objects/<sha256>` as the content-addressed, never-overwritten
final identity that scans and every later access bind to (data model s.9)."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable, Iterator
from typing import Any

from django.conf import settings

from ..ports import ObjectNotFound, ObjectStoreUnavailable, ObjectTooLarge, StoredObject


class S3ObjectStore:
    name = "s3"

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        self._bucket_ready = False

    @classmethod
    def from_settings(cls) -> S3ObjectStore:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.OBJECT_ENDPOINT or None,
            region_name=settings.OBJECT_REGION,
            aws_access_key_id=settings.OBJECT_ACCESS_KEY,
            aws_secret_access_key=settings.OBJECT_SECRET_KEY,
            config=Config(
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        return cls(client, settings.OBJECT_BUCKET)

    # ---- helpers ------------------------------------------------------------------------------

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:  # noqa: BLE001 - botocore error hierarchy is dynamic
            if _status(exc) in (404, 403) or "NoSuchBucket" in str(exc) or "404" in str(exc):
                try:
                    self._client.create_bucket(Bucket=self._bucket)
                except Exception as create_exc:  # noqa: BLE001
                    if "BucketAlreadyOwnedByYou" not in str(create_exc):
                        raise ObjectStoreUnavailable(str(type(create_exc).__name__)) from None
            else:
                raise ObjectStoreUnavailable(type(exc).__name__) from None
        self._bucket_ready = True

    # ---- port ---------------------------------------------------------------------------------

    def put_staging(self, key: str, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        self._ensure_bucket()
        digest = hashlib.sha256()
        spool = io.BytesIO()
        total = 0
        for chunk in chunks:
            total += len(chunk)
            if total > max_bytes:
                raise ObjectTooLarge(f"upload exceeds {max_bytes} bytes")
            digest.update(chunk)
            spool.write(chunk)
        spool.seek(0)
        try:
            response = self._client.put_object(Bucket=self._bucket, Key=key, Body=spool)
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreUnavailable(type(exc).__name__) from None
        return StoredObject(
            key=key, size=total, sha256=digest.hexdigest(), version_id=_version(response)
        )

    def head(self, key: str) -> StoredObject | None:
        self._ensure_bucket()
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404 or "Not Found" in str(exc) or "404" in str(exc):
                return None
            raise ObjectStoreUnavailable(type(exc).__name__) from None
        return StoredObject(
            key=key, size=int(response["ContentLength"]), sha256=None, version_id=_version(response)
        )

    def read(self, key: str, *, max_bytes: int) -> Iterator[bytes]:
        self._ensure_bucket()
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404 or "NoSuchKey" in str(exc):
                raise ObjectNotFound(key) from None
            raise ObjectStoreUnavailable(type(exc).__name__) from None
        if int(response.get("ContentLength", 0)) > max_bytes:
            raise ObjectTooLarge(key)
        body = response["Body"]
        try:
            total = 0
            for chunk in body.iter_chunks(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ObjectTooLarge(key)
                yield chunk
        except ObjectTooLarge:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreUnavailable(type(exc).__name__) from None
        finally:
            body.close()

    def promote(self, staging_key: str, final_key: str, *, expected_size: int) -> StoredObject:
        self._ensure_bucket()
        existing = self.head(final_key)
        if existing is not None:
            # Content-addressed identity: the same SHA-256 means the same bytes. A size mismatch
            # would mean a collision or tampering and is refused instead of overwritten.
            if existing.size != expected_size:
                raise ObjectTooLarge(f"final key {final_key} exists with a different size")
            return existing
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=final_key,
                CopySource={"Bucket": self._bucket, "Key": staging_key},
                MetadataDirective="COPY",
            )
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404 or "NoSuchKey" in str(exc):
                raise ObjectNotFound(staging_key) from None
            raise ObjectStoreUnavailable(type(exc).__name__) from None
        promoted = self.head(final_key)
        if promoted is None or promoted.size != expected_size:
            raise ObjectStoreUnavailable("promoted object metadata mismatch")
        return promoted

    def delete(self, key: str) -> None:
        if not key.startswith("staging/"):
            return  # final objects are immutable; never deleted by this path
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001, S110 - best effort cleanup; expiry sweep retries
            pass


def _status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        meta = response.get("ResponseMetadata", {})
        code = meta.get("HTTPStatusCode")
        return int(code) if code is not None else None
    return None


def _version(response: Any) -> str:
    version = response.get("VersionId") if isinstance(response, dict) else None
    if version and version != "null":
        return f"v:{version}"
    etag = response.get("ETag", "") if isinstance(response, dict) else ""
    return f"etag:{str(etag).strip('"')}"
