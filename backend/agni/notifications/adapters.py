"""Provider adapters. Only the demo sink exists at B03; live adapters are added behind the
same port with contract tests and are refused by production settings until approved
(document 19). Never fall back from a live provider to the sink."""

from __future__ import annotations

from django.conf import settings

from agni.platform.errors import DependencyUnavailable

from .models import DemoOutboundMessage
from .ports import OtpMessage, OtpSender


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
