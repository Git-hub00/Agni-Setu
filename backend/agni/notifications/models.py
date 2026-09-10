"""Demo sink storage. The local sink is isolated to demo/test and has no outbound provider
(security s.2); messages land here so tests and the demo inbox can read them."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


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
