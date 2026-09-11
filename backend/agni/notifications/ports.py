"""Provider ports (architecture s.4: notifications may call provider ports only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class OtpMessage:
    channel: str
    destination: str
    destination_masked: str
    destination_lookup_hmac: str
    purpose: str
    code: str
    challenge_id: UUID
    expires_in_minutes: int


class OtpSender(Protocol):
    name: str

    def send(self, message: OtpMessage) -> None:
        """Deliver (or sink) a one-time code. Must never log the code."""


@dataclass(frozen=True)
class OutboundMessage:
    """A rendered service message (FR-23). `logical_id` is the provider idempotency key."""

    channel: str
    destination: str
    destination_masked: str
    destination_lookup_hmac: str
    subject: str
    body: str
    logical_id: UUID
    category: str


@dataclass(frozen=True)
class SendReceipt:
    provider_message_id: str
    accepted: bool = True


class MessageSender(Protocol):
    name: str

    def send(self, message: OutboundMessage) -> SendReceipt:
        """Hand the message to the channel provider. Raise `ProviderUnavailable` for a transient
        failure before any irreversible effect; raise `ProviderRejected` for a permanent one."""


class ProviderUnavailable(Exception):
    """Transient provider failure (timeout, 5xx, circuit open) - safe to retry."""


class ProviderRejected(Exception):
    """Permanent provider rejection (bad destination, unsupported channel) - do not retry."""
