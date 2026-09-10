"""Contact normalisation, purpose-bound lookup HMAC, at-rest encryption and safe masking
(security s.2, data model `contact_identity`). Plaintext contacts are never logged or queried."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from agni.platform.errors import ValidationFailed, Violation

from .models import ContactChannel

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_KEY_VERSION = "v1"


@dataclass(frozen=True)
class NormalizedContact:
    channel: ContactChannel
    value: str

    @property
    def lookup_hmac(self) -> str:
        key = settings.CONTACT_LOOKUP_KEY.encode("utf-8")
        return hmac.new(key, f"{self.channel}:{self.value}".encode(), hashlib.sha256).hexdigest()

    @property
    def masked(self) -> str:
        if self.channel == ContactChannel.EMAIL:
            local, _, domain = self.value.partition("@")
            head = local[:1]
            return f"{head}{'*' * max(3, len(local) - 1)}@{domain}"
        return f"{self.value[:3]}{'*' * max(3, len(self.value) - 7)}{self.value[-4:]}"


def normalize_contact(channel: str, raw: str) -> NormalizedContact:
    violations: list[Violation] = []
    if channel not in ContactChannel.values:
        violations.append(Violation("/channel", "invalid", "must be EMAIL or SMS"))
        raise ValidationFailed(violations=violations)
    value = (raw or "").strip()
    if channel == ContactChannel.EMAIL:
        value = value.lower()
        if not value or len(value) > 254 or not _EMAIL_RE.match(value):
            violations.append(Violation("/contact", "format", "must be a valid email address"))
    else:
        digits = re.sub(r"[\s\-()]", "", value)
        if digits and digits[0] != "+" and len(digits) == 10 and digits.isdigit():
            digits = f"+91{digits}"  # demo default country; live policy configures this
        value = digits
        if not _PHONE_RE.match(value):
            violations.append(
                Violation("/contact", "format", "must be an international mobile number")
            )
    if violations:
        raise ValidationFailed(violations=violations)
    return NormalizedContact(channel=ContactChannel(channel), value=value)


def _fernet() -> Fernet:
    secret = settings.DATA_ENCRYPTION_KEY
    if not secret:
        # local/test convenience only; production settings refuse an empty key
        secret = f"derived:{settings.SECRET_KEY}"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_contact(value: str) -> tuple[bytes, str]:
    return _fernet().encrypt(value.encode("utf-8")), _KEY_VERSION


def decrypt_contact(ciphertext: bytes | memoryview) -> str:
    try:
        return _fernet().decrypt(bytes(ciphertext)).decode("utf-8")
    except InvalidToken as exc:  # wrong key version / tampering
        raise ValueError("contact ciphertext cannot be decrypted with the configured key") from exc
