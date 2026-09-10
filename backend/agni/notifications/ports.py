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
