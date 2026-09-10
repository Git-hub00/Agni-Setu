"""Demo-only inbox (UI-02 edge behaviour: a local demo inbox may reveal synthetic messages
only on an isolated development surface). Registered ONLY when demo controls are enabled and
APP_ENV is not production; production settings reject demo controls (ADR-15)."""

from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.contacts import normalize_contact
from agni.platform.api.views import ApiView, ok

from ..models import DemoOutboundMessage


class DemoInboxView(ApiView):
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        channel = str(request.query_params.get("channel", "EMAIL")).upper()
        contact = str(request.query_params.get("contact", ""))
        normalized = normalize_contact(channel, contact)
        messages = DemoOutboundMessage.objects.filter(
            destination_lookup_hmac=normalized.lookup_hmac
        ).order_by("-created_at")[:10]
        return ok(
            {
                "destination": normalized.masked,
                "messages": [
                    {
                        "id": str(m.id),
                        "purpose": m.purpose,
                        "body": m.body,
                        "reference_id": str(m.reference_id) if m.reference_id else None,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in messages
                ],
            },
            request,
        )
