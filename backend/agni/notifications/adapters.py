"""Provider adapters. Only the demo sink exists at B03; live adapters are added behind the
same port with contract tests and are refused by production settings until approved
(document 19). Never fall back from a live provider to the sink."""

from __future__ import annotations

from django.conf import settings

from agni.platform.errors import DependencyUnavailable

from .models import DemoOutboundMessage
from .ports import (
    MessageSender,
    OtpMessage,
    OtpSender,
    OutboundMessage,
    ProviderRejected,
    ProviderUnavailable,
    SendReceipt,
)


class DemoSinkOtpSender:
    """Stores the synthetic message in the local database. No network."""

    name = "demo_sink"

    def send(self, message: OtpMessage) -> None:
        DemoOutboundMessage.objects.create(
            channel=message.channel,
            destination_lookup_hmac=message.destination_lookup_hmac,
            destination_masked=message.destination_masked,
            purpose=message.purpose,
            body=(
                f"Your Agni Setu verification code is {message.code}. "
                f"It expires in {message.expires_in_minutes} minutes. "
                "Demo message - not an official service."
            ),
            reference_id=message.challenge_id,
        )


def get_otp_sender() -> OtpSender:
    provider = settings.OTP_PROVIDER
    if provider == "demo_sink":
        return DemoSinkOtpSender()
    raise DependencyUnavailable(f"OTP provider '{provider}' has no approved adapter installed")


class DemoSinkMessageSender:
    """Stores the rendered service message in the local sink. `force_failure` lets tests and the
    demo walkthrough simulate an unavailable gateway without any network."""

    name = "demo_sink"
    force_failure: str | None = None  # None | "transient" | "permanent"

    def send(self, message: OutboundMessage) -> SendReceipt:
        if DemoSinkMessageSender.force_failure == "transient":
            raise ProviderUnavailable("demo gateway unavailable")
        if DemoSinkMessageSender.force_failure == "permanent":
            raise ProviderRejected("demo gateway rejected the destination")
        row = DemoOutboundMessage.objects.create(
            channel=message.channel,
            destination_lookup_hmac=message.destination_lookup_hmac,
            destination_masked=message.destination_masked,
            purpose=f"NOTIFICATION:{message.category}",
            body=f"{message.subject}\n\n{message.body}\n\nDemo message - not an official service.",
            reference_id=message.logical_id,
        )
        return SendReceipt(provider_message_id=f"demo-sink:{row.id}")


def get_message_sender() -> MessageSender:
    provider = settings.NOTIFICATION_PROVIDER
    if provider == "demo_sink":
        return DemoSinkMessageSender()
    raise DependencyUnavailable(
        f"Notification provider '{provider}' has no approved adapter installed"
    )
