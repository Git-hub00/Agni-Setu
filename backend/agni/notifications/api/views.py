"""Personal notifications API-078..080 and preferences API-008 (UI-19). Recipient-only: no
staff member can read another person's notifications; read markers never change case state."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.models import Principal
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    AuthenticationRequired,
    MalformedRequest,
    ResourceNotFound,
    ValidationFailed,
    Violation,
)

from ..models import DeliveryAttempt, Notification, NotificationPreference

PAGE_SIZE = 50


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def notification_body(n: Notification, deliveries: list[DeliveryAttempt]) -> dict[str, Any]:
    return {
        "notification_id": str(n.pk),
        "category": n.category,
        "mandatory": n.mandatory,
        "title": n.in_app_title,
        "body": n.in_app_body,
        "target_path": n.target_path or None,
        "application_id": str(n.application_id) if n.application_id else None,
        "created_at": n.created_at.isoformat(),
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "deliveries": [
            {
                "channel": d.channel,
                "state": d.state,
                "destination_masked": d.destination_masked or None,
                "sent_at": d.sent_at.isoformat() if d.sent_at else None,
                "failure_code": d.safe_failure_code,
                "attempts": d.attempts,
            }
            for d in deliveries
        ],
    }


class NotificationListView(ApiView):
    """API-078."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        queryset = Notification.objects.filter(recipient=principal)
        if request.query_params.get("unread_only") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)
        before = request.query_params.get("cursor")
        if before:
            parsed = parse_datetime(before)
            if parsed is None or parsed.tzinfo is None:
                raise MalformedRequest("cursor must be an ISO 8601 UTC timestamp")
            queryset = queryset.filter(created_at__lt=parsed)
        rows = list(queryset.order_by("-created_at", "-id")[: PAGE_SIZE + 1])
        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        deliveries: dict[UUID, list[DeliveryAttempt]] = {}
        for d in DeliveryAttempt.objects.filter(notification__in=[r.pk for r in rows]):
            deliveries.setdefault(d.notification_id, []).append(d)
        return ok(
            {
                "items": [notification_body(n, deliveries.get(n.pk, [])) for n in rows],
                "next_cursor": rows[-1].created_at.isoformat() if has_more and rows else None,
                "has_more": has_more,
                "unread_count": Notification.objects.filter(
                    recipient=principal, read_at__isnull=True
                ).count(),
                "as_of": now.isoformat(),
            },
            request,
        )


class MarkRead(CommandHandler[Principal]):
    """API-079: idempotent read marker for the recipient only."""

    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        return None

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        notification = (
            Notification.objects.select_for_update()
            .filter(pk=uow.envelope.target_id, recipient=uow.actor)
            .first()
        )
        if notification is None:
            raise ResourceNotFound("Notification not found")
        if notification.read_at is None:
            notification.read_at = uow.now
            notification.save(update_fields=["read_at"])
        return CommandOutcome(
            status=200,
            body=notification_body(notification, list(notification.deliveries.all())),
            aggregate=None,
            audits=[AuditEntry("notification", notification.pk, "notification.read", {})],
        )


class ReadThrough(CommandHandler[Principal]):
    """API-080: mark read up to an explicit boundary; later arrivals stay unread."""

    def authorize(self, uow: UnitOfWork) -> None:
        return None

    def lock_target(self, uow: UnitOfWork) -> Principal | None:
        return None

    def apply(self, uow: UnitOfWork, target: Principal | None) -> CommandOutcome[Principal]:
        data = dict(uow.envelope.payload)
        raw = data.get("through")
        parsed = parse_datetime(str(raw)) if raw else None
        if parsed is None or parsed.tzinfo is None:
            raise ValidationFailed(
                violations=[Violation("/through", "format", "ISO 8601 UTC timestamp boundary")]
            )
        updated = Notification.objects.filter(
            recipient=uow.actor, read_at__isnull=True, created_at__lte=parsed
        ).update(read_at=uow.now)
        return CommandOutcome(
            status=200,
            body={
                "through": parsed.isoformat(),
                "marked_read": updated,
                "unread_count": Notification.objects.filter(
                    recipient=uow.actor, read_at__isnull=True
                ).count(),
            },
            aggregate=None,
            audits=[
                AuditEntry(
                    "principal", uow.actor.pk, "notification.read_through", {"count": updated}
                )
            ],
        )


class NotificationReadView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, notification_id: UUID) -> Response:
        return self.run_command(
            request,
            MarkRead(),
            command_name="mark-notification-read",
            target_type="notification",
            target_id=notification_id,
        )


class ReadThroughView(ApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            ReadThrough(),
            command_name="notifications-read-through",
            target_type="notifications:scope",
            target_id=principal.pk,
        )


class PreferencesView(ApiView):
    """API-008 (GET/PATCH /me/preferences)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        pref = NotificationPreference.objects.filter(principal=principal).first()
        return ok(_pref_body(pref), request)

    def patch(self, request: Request) -> Response:
        principal = _principal(request)
        data = request.data if isinstance(request.data, dict) else {}
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"locale", "optional_channels", "reduced_motion"})
        ]
        locale = data.get("locale", "en")
        if locale not in ("en", "hi"):
            violations.append(Violation("/locale", "unsupported", "en or hi"))
        channels = data.get("optional_channels", [])
        if (
            not isinstance(channels, list)
            or any(c not in ("EMAIL", "SMS") for c in channels)
            or len(set(channels)) != len(channels)
        ):
            violations.append(Violation("/optional_channels", "allowlist", "unique EMAIL/SMS"))
        reduced = data.get("reduced_motion", False)
        if not isinstance(reduced, bool):
            violations.append(Violation("/reduced_motion", "invalid", "true or false"))
        if violations:
            raise ValidationFailed(violations=violations)
        pref, _ = NotificationPreference.objects.get_or_create(principal=principal)
        pref.locale = locale
        pref.optional_channels = list(channels)
        pref.reduced_motion = reduced
        pref.version += 1
        pref.save()
        return ok(_pref_body(pref), request)


def _pref_body(pref: NotificationPreference | None) -> dict[str, Any]:
    return {
        "locale": pref.locale if pref else "en",
        "optional_channels": list(pref.optional_channels) if pref else [],
        "reduced_motion": pref.reduced_motion if pref else False,
        "mandatory_note": (
            "Mandatory service messages (notices, appointments, decisions) cannot be disabled."
        ),
    }
