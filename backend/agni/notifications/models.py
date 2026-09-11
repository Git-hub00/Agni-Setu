"""Notifications persistence (data model `notification`, `delivery_attempt`, preferences) plus
the demo sink storage. The in-app notification is the durable intent written transactionally
by the fan-out job; channel attempts are tracked separately and never change case outcomes.
The local sink is isolated to demo/test and has no outbound provider (security s.2)."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from agni.platform.models import VersionedModel


class NotificationCategory(models.TextChoices):
    CASE = "CASE"
    NOTICE = "NOTICE"
    APPOINTMENT = "APPOINTMENT"
    REVIEW = "REVIEW"
    OBLIGATION = "OBLIGATION"
    ESCALATION = "ESCALATION"


class Notification(models.Model):
    """One in-app notification for one recipient (unique per recipient and logical key)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications"
    )
    source_event = models.ForeignKey(
        "cases.CaseEvent", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    application = models.ForeignKey(
        "cases.Application", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    logical_key = models.CharField(max_length=160)
    template_key = models.CharField(max_length=80)
    template_version = models.PositiveIntegerField(default=1)
    category = models.CharField(max_length=12, choices=NotificationCategory.choices)
    mandatory = models.BooleanField(default=False)
    safe_render_context = models.JSONField(default=dict)
    in_app_title = models.CharField(max_length=200)
    in_app_body = models.TextField()
    target_path = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "logical_key"], name="uniq_notification_recipient_key"
            )
        ]
        indexes = [
            models.Index(fields=["recipient", "created_at"], name="idx_notification_recipient"),
            models.Index(
                fields=["recipient"],
                name="idx_notification_unread",
                condition=models.Q(read_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template_key} -> {self.recipient_id}"


class DeliveryChannel(models.TextChoices):
    EMAIL = "EMAIL"
    SMS = "SMS"


class DeliveryState(models.TextChoices):
    READY = "READY"
    SENDING = "SENDING"
    ACCEPTED_BY_PROVIDER = "ACCEPTED_BY_PROVIDER"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class DeliveryAttempt(models.Model):
    """One channel delivery for a notification. Provider acceptance is not proof of delivery
    (workflow s.5); failures stay visible and never remove the in-app notification."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.PROTECT, related_name="deliveries"
    )
    channel = models.CharField(max_length=5, choices=DeliveryChannel.choices)
    job_id = models.UUIDField(null=True, blank=True)
    destination_masked = models.CharField(max_length=160, blank=True, default="")
    provider_message_id = models.TextField(null=True, blank=True)
    state = models.CharField(
        max_length=24, choices=DeliveryState.choices, default=DeliveryState.READY
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    safe_failure_code = models.CharField(max_length=80, null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="uniq_delivery_channel"
            ),
            models.UniqueConstraint(
                fields=["provider_message_id"],
                condition=models.Q(provider_message_id__isnull=False),
                name="uniq_delivery_provider_message",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel} {self.state} for {self.notification_id}"


class NotificationPreference(VersionedModel):
    """API-008 preferences: locale, optional channels and reduced motion. Mandatory service
    messages ignore `optional_channels`."""

    principal = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notification_preference"
    )
    locale = models.CharField(max_length=8, default="en")
    optional_channels = models.JSONField(default=list)
    reduced_motion = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"preferences {self.principal_id}"


class DemoOutboundMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.CharField(max_length=5)
    destination_lookup_hmac = models.CharField(max_length=64)
    destination_masked = models.CharField(max_length=160)
    purpose = models.CharField(max_length=40)
    body = models.TextField()
    reference_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        indexes = [
            models.Index(fields=["destination_lookup_hmac", "created_at"], name="idx_demo_msg_dest")
        ]

    def __str__(self) -> str:
        return f"{self.channel}->{self.destination_masked}"
