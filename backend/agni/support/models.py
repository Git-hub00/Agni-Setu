"""Support tickets (FR-30; data model `support_ticket` / `support_message`). A ticket is a help
conversation with its own lifecycle and owner queue. It is not an emergency channel, not a
regulatory notice and not a legal appeal; nothing here can mutate a case."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from agni.platform.models import AppendOnlyModel, VersionedModel


class TicketCategory(models.TextChoices):
    HOW_TO = "HOW_TO"
    TECHNICAL = "TECHNICAL"
    ACCESS = "ACCESS"
    DATA_CORRECTION = "DATA_CORRECTION"
    OTHER = "OTHER"


class TicketState(models.TextChoices):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_REQUESTER = "WAITING_FOR_REQUESTER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(models.TextChoices):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class MessageAudience(models.TextChoices):
    REQUESTER = "REQUESTER"
    INTERNAL = "INTERNAL"


class MessageKind(models.TextChoices):
    MESSAGE = "MESSAGE"
    STATUS = "STATUS"


class SupportTicket(VersionedModel):
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets"
    )
    application = models.ForeignKey(
        "cases.Application",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="support_tickets",
    )
    category = models.CharField(max_length=20, choices=TicketCategory.choices)
    subject = models.CharField(max_length=160)
    description = models.TextField()
    state = models.CharField(max_length=24, choices=TicketState.choices, default=TicketState.OPEN)
    owner_queue = models.ForeignKey(
        "routing.DutyQueue", on_delete=models.PROTECT, related_name="support_tickets"
    )
    priority = models.CharField(
        max_length=8, choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=[s.value for s in TicketState]),
                name="chk_support_ticket_state",
            )
        ]
        indexes = [
            models.Index(fields=["requester", "created_at"], name="idx_ticket_requester"),
            models.Index(fields=["owner_queue", "state"], name="idx_ticket_queue_state"),
        ]

    def __str__(self) -> str:
        return f"ticket {self.subject[:40]} [{self.state}]"

    @property
    def etag(self) -> str:
        return f'"ticket:{self.id}:v{self.version}"'


class SupportMessage(AppendOnlyModel):
    """Append-only conversation entry. INTERNAL notes never reach the requester; a wrong-audience
    message is corrected by a recorded follow-up, not by editing."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    audience = models.CharField(max_length=10, choices=MessageAudience.choices)
    kind = models.CharField(max_length=8, choices=MessageKind.choices, default=MessageKind.MESSAGE)
    body = models.TextField()
    document_version_ids = models.JSONField(default=list)
    state_after = models.CharField(max_length=24, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["ticket", "created_at"], name="idx_ticket_message")]

    def __str__(self) -> str:
        return f"{self.kind} on {self.ticket_id} ({self.audience})"
