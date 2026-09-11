"""Partner request authentication (security s.2: partner callbacks use their own approved
scheme and never inherit browser exemptions). Baseline scheme: HMAC-SHA256 over
`<timestamp>.<raw body>` with a shared secret resolved from the integration's secret
*reference*; a bounded timestamp skew limits replay. Secret values never enter the database,
logs or responses; the stored evidence carries the scheme, the key reference and a signature
prefix only."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.conf import settings

from agni.platform.errors import IntegrationSignatureInvalid

from .models import Integration

SCHEME = "AGNI-HMAC-SHA256"
HEADER_KEY = "X-Agni-Partner-Key"
HEADER_SIGNATURE = "X-Agni-Signature"
HEADER_TIMESTAMP = "X-Agni-Timestamp"


def resolve_secret(reference: str) -> str | None:
    """Environment first (approved secret store injects it); demo secrets only outside LIVE."""
    if not reference:
        return None
    value = os.environ.get(reference)
    if value:
        return value
    demo: Mapping[str, str] = getattr(settings, "INTEGRATION_DEMO_SECRETS", {})
    return demo.get(reference)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def verify(
    integration: Integration, headers: Mapping[str, str], body: bytes, *, now: datetime
) -> dict[str, Any]:
    """Return safe auth evidence or raise IntegrationSignatureInvalid (401) before any parsing."""
    key = headers.get(HEADER_KEY, "")
    signature = headers.get(HEADER_SIGNATURE, "")
    timestamp = headers.get(HEADER_TIMESTAMP, "")
    if key != integration.key or not signature or not timestamp:
        raise IntegrationSignatureInvalid("Partner authentication headers are missing or wrong")
    try:
        issued = int(timestamp)
    except ValueError:
        raise IntegrationSignatureInvalid("Partner timestamp is not valid") from None
    skew = int(getattr(settings, "PARTNER_SIGNATURE_SKEW_SECONDS", 300))
    if abs(int(now.timestamp()) - issued) > skew:
        raise IntegrationSignatureInvalid("Partner timestamp is outside the accepted window")
    secret = resolve_secret(integration.credential_secret_ref)
    if not secret:
        # No secret configured means nothing can be verified; fail closed.
        raise IntegrationSignatureInvalid("Partner credential is not configured")
    expected = sign(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise IntegrationSignatureInvalid("Partner signature does not match")
    return {
        "scheme": SCHEME,
        "key_ref": integration.credential_secret_ref,
        "timestamp": issued,
        "signature_prefix": signature[:15],
    }
