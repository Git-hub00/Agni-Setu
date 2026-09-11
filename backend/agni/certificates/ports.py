"""Typed ports for certificate rendering, signing and signature verification (integrations
s.2). Application code depends on these Protocols; adapters live in `certificates.adapters`.
Every simulator implements the same semantic contract incl. transient failure, unknown
outcome, duplicate request and permanent refusal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RenderedArtifact:
    data: bytes
    sha256: str
    media_type: str
    renderer: str
    renderer_version: str
    mode: str  # DEMO_WATERMARK | SIGNED


class RendererUnavailable(Exception):
    """Transient: the renderer cannot run right now (retry later)."""


class RendererFailed(Exception):
    """Permanent for this snapshot: the input cannot be rendered."""


class CertificateRenderer(Protocol):
    name: str

    def render(
        self, template_key: str, template_version: int, snapshot: Mapping[str, Any]
    ) -> RenderedArtifact:
        """Deterministic business data -> artifact bytes with embedded mode + verification link."""


@dataclass(frozen=True)
class SignReceipt:
    provider: str
    request_id: str
    artifact_sha256: str
    signed_at: datetime
    mode: str
    evidence: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "request_id": self.request_id,
            "artifact_sha256": self.artifact_sha256,
            "signed_at": self.signed_at.isoformat(),
            "mode": self.mode,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class SignLookup:
    status: str  # COMPLETED | NOT_FOUND | UNKNOWN
    receipt: SignReceipt | None = None


class SignerUnavailable(Exception):
    """The request never reached the signer: a retry with the same identity is safe."""


class SignerUnknownOutcome(Exception):
    """The request may have reached the signer: look it up before any resubmission."""


class SignerRejected(Exception):
    """The signer refused the artifact explicitly."""


class CertificateSigner(Protocol):
    name: str
    mode: str

    def submit(self, stable_request_id: str, artifact_sha256: str, *, at: datetime) -> SignReceipt:
        """Bounded call; raises SignerUnavailable / SignerUnknownOutcome / SignerRejected."""

    def lookup(self, stable_request_id: str) -> SignLookup:
        """Status of an earlier submission by its stable identity."""


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    evidence: Mapping[str, Any]


class SignatureVerifier(Protocol):
    name: str

    def verify(
        self, artifact_sha256: str, receipt: SignReceipt, *, expected_issuer: str
    ) -> VerificationResult:
        """Integrity/signature status with retained evidence; a QR code is never a signature."""
