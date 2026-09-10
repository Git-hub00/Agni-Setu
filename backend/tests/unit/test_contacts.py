from __future__ import annotations

import pytest

from agni.identity.contacts import decrypt_contact, encrypt_contact, normalize_contact
from agni.platform.errors import ValidationFailed


def test_email_is_lowercased_and_masked() -> None:
    contact = normalize_contact("EMAIL", "  Rakesh.Mehta@Example.TEST ")
    assert contact.value == "rakesh.mehta@example.test"
    assert contact.masked.startswith("r") and contact.masked.endswith("@example.test")
    assert "akesh" not in contact.masked


def test_phone_defaults_to_india_and_masks_middle() -> None:
    contact = normalize_contact("SMS", "98765 43210")
    assert contact.value == "+919876543210"
    assert contact.masked.startswith("+91") and contact.masked.endswith("3210")
    assert "98765" not in contact.masked


@pytest.mark.parametrize(
    ("channel", "raw"), [("EMAIL", "nope"), ("SMS", "12345"), ("FAX", "x"), ("EMAIL", "")]
)
def test_invalid_contacts_are_validation_failures(channel: str, raw: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_contact(channel, raw)


def test_lookup_hmac_is_deterministic_and_channel_bound() -> None:
    a = normalize_contact("EMAIL", "p1@example.test")
    b = normalize_contact("EMAIL", "P1@example.test")
    assert a.lookup_hmac == b.lookup_hmac and len(a.lookup_hmac) == 64
    assert a.lookup_hmac != normalize_contact("SMS", "+919876543210").lookup_hmac


def test_encryption_round_trip_and_key_version() -> None:
    ciphertext, version = encrypt_contact("p1@example.test")
    assert version == "v1" and b"p1@example" not in ciphertext
    assert decrypt_contact(ciphertext) == "p1@example.test"
