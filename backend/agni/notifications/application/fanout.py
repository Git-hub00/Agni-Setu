"""Event fan-out and channel delivery jobs (FR-23; docs/08 s.2-5).

`notification.fanout` turns one dispatched outbox intent into in-app notifications (unique per
recipient and logical key) plus READY delivery attempts for recipients with a verified contact.
`notification.deliver` hands one attempt to the provider port; a transient failure retries with
the job backoff, a permanent one dead-letters the attempt - the in-app notification stays.
Threshold and manual escalations call the same recipient/creation helpers directly inside their
own transactions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction

from agni.cases.models import Application, CaseEvent
from agni.identity.contacts import decrypt_contact, normalize_contact
from agni.identity.models import ContactChannel, ContactIdentity, Principal, PrincipalKind
from agni.platform import jobs
from agni.platform.models import AttemptOutcome, LogicalJob, OutboxMessage

from ..adapters import get_message_sender
from ..models import (
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryState,
    Notification,
    NotificationPreference,
)
from ..ports import OutboundMessage, ProviderRejected, ProviderUnavailable
from ..templates import (
    APPLICANT,
    ASSIGNED_OFFICER,
    MANUAL_ESCALATION,
    SUPERVISORS,
    TEMPLATES,
    THRESHOLD_ESCALATION,
    THRESHOLD_REMINDER,
    Template,
    render,
)

FANOUT_JOB = "notification.fanout"
DELIVER_JOB = "notification.deliver"
_NAMESPACE = uuid.UUID("9d3a5c1e-7b4f-4e2a-8c6d-1f0e2b3c4d5e")


def fanout_job_id(outbox_logical_action_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"fanout:{outbox_logical_action_id}")


def deliver_job_id(notification_id: uuid.UUID, channel: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"deliver:{notification_id}:{channel}")


# ---- recipients ---------------------------------------------------------------------------


def _supervisors(application: Application, at: datetime) -> list[Principal]:
    from agni.obligations.application.scheduler import supervisors_for_queue

    return supervisors_for_queue(application.owner_queue, at)


def _applicants(application: Application) -> list[Principal]:
    people = [application.applicant]
    if application.acting_operator_id != application.applicant_id:
        people.append(application.acting_operator)
    return people


def _assigned_officer(payload: dict[str, Any]) -> list[Principal]:
    from agni.inspections.models import AssignmentState, Inspection

    inspection_id = payload.get("inspection_id")
    if not inspection_id:
        return []
    inspection = (
        Inspection.objects.select_related("current_assignment__officer")
        .filter(pk=inspection_id)
        .first()
    )
    current = inspection.current_assignment if inspection else None
    if current is None or current.state != AssignmentState.ACTIVE:
        return []
    return [current.officer]


def recipients_for(
    template: Template, application: Application, payload: dict[str, Any], at: datetime
) -> list[Principal]:
    people: dict[Any, Principal] = {}
    for audience in template.audiences:
        if audience == APPLICANT:
            found = _applicants(application)
        elif audience == SUPERVISORS:
            found = _supervisors(application, at)
        elif audience == ASSIGNED_OFFICER:
            found = _assigned_officer(payload)
        else:
            found = []
        for person in found:
            if person.is_active:
                people[person.pk] = person
    return list(people.values())


# ---- creation ---------------------------------------------------------------------------------


def _context(application: Application, payload: dict[str, Any]) -> dict[str, Any]:
    due = payload.get("due_at")
    context = {
        "reference": application.public_reference or application.draft_reference,
        "application_id": str(application.pk),
        "queue": application.owner_queue.display_name
        if hasattr(application.owner_queue, "display_name")
        else application.owner_queue.queue_key,
        "item_count": len(payload.get("item_codes", []) or []),
        "items": ", ".join(payload.get("item_codes", []) or []),
        "due": due,
        "outcome": payload.get("outcome"),
        "outcome_lower": str(payload.get("outcome", "")).replace("_", " ").lower(),
        "public_reason": payload.get("public_reason", ""),
        "item_code": payload.get("item_code"),
        "reason_code": payload.get("reason_code"),
        "scheduled_start": payload.get("scheduled_start"),
        "timezone": payload.get("appointment_timezone") or payload.get("timezone"),
        "notice_id": payload.get("notice_id"),
        "inspection_id": payload.get("inspection_id"),
    }
    return context


def create_notification(
    *,
    recipient: Principal,
    template: Template,
    logical_key: str,
    context: dict[str, Any],
    application: Application | None,
    source_event: CaseEvent | None,
    now: datetime,
) -> Notification | None:
    """Idempotent on (recipient, logical_key). Also schedules channel delivery for mandatory
    messages (or when the recipient opted in) when a verified contact exists."""
    title, body, target = render(template, context)
    safe_context = {
        k: v
        for k, v in context.items()
        if k in ("reference", "due", "item_code", "outcome", "kind", "threshold", "level")
    }
    try:
        with transaction.atomic():
            notification = Notification.objects.create(
                recipient=recipient,
                source_event=source_event,
                application=application,
                logical_key=logical_key[:160],
                template_key=template.key,
                template_version=template.version,
                category=template.category,
                mandatory=template.mandatory,
                safe_render_context=safe_context,
                in_app_title=title,
                in_app_body=body,
                target_path=target,
                created_at=now,
            )
    except IntegrityError:
        return None  # duplicate dispatch: the earlier notification stands
    _schedule_channels(notification, recipient, template, now)
    return notification


def _schedule_channels(
    notification: Notification, recipient: Principal, template: Template, now: datetime
) -> None:
    if recipient.kind != PrincipalKind.APPLICANT or not recipient.verified_contact_ref:
        return  # staff receive in-app only in the demo profile
    preference = NotificationPreference.objects.filter(principal=recipient).first()
    optional = set(preference.optional_channels) if preference else set()
    contact = ContactIdentity.objects.filter(pk=recipient.verified_contact_ref).first()
    if contact is None or contact.verified_at is None:
        return
    channel = (
        DeliveryChannel.EMAIL if contact.channel == ContactChannel.EMAIL else DeliveryChannel.SMS
    )
    if not template.mandatory and channel not in optional:
        return
    attempt = DeliveryAttempt.objects.create(
        notification=notification,
        channel=channel,
        job_id=deliver_job_id(notification.pk, channel),
        state=DeliveryState.READY,
    )
    jobs.enqueue_job(
        kind=DELIVER_JOB,
        aggregate_ref={
            "delivery_attempt_id": str(attempt.pk),
            "notification_id": str(notification.pk),
        },
        run_at=now,
        logical_action_id=attempt.job_id,
    )


def fan_out_event(message: OutboxMessage, *, now: datetime) -> int:
    template = TEMPLATES.get(message.event_type)
    if template is None or message.aggregate_type != "application":
        return 0
    application = (
        Application.objects.select_related(
            "applicant", "acting_operator", "owner_queue__jurisdiction"
        )
        .filter(pk=message.aggregate_id)
        .first()
    )
    if application is None:
        return 0
    payload = dict(message.payload.get("payload", {}))
    event = CaseEvent.objects.filter(pk=message.payload.get("event_id")).first()
    context = _context(application, payload)
    created = 0
    for recipient in recipients_for(template, application, payload, now):
        if create_notification(
            recipient=recipient,
            template=template,
            logical_key=f"{message.event_type}:{message.logical_action_id}",
            context=context,
            application=application,
            source_event=event,
            now=now,
        ):
            created += 1
    return created


def notify_threshold(
    action: Any, obligation: Any, escalation: Any, event: CaseEvent | None, *, now: datetime
) -> int:
    """Called inside the threshold job's completion transaction."""
    application = obligation.application
    if application is None:
        return 0
    template = THRESHOLD_ESCALATION if escalation is not None else THRESHOLD_REMINDER
    context = {
        "reference": application.public_reference or application.draft_reference,
        "application_id": str(application.pk),
        "kind": obligation.kind.replace("_", " ").lower(),
        "threshold": action.threshold_key,
        "due": obligation.due_at.isoformat() if obligation.due_at else None,
        "level": escalation.level if escalation else 0,
        "queue": obligation.owner_queue.queue_key,
    }
    recipients: list[Principal]
    if escalation is None and obligation.responsible_principal_id:
        recipients = [obligation.responsible_principal]
    else:
        from agni.obligations.application.scheduler import supervisors_for_queue

        recipients = supervisors_for_queue(obligation.owner_queue, now)
    created = 0
    for recipient in recipients:
        if create_notification(
            recipient=recipient,
            template=template,
            logical_key=f"threshold:{action.pk}",
            context=context,
            application=application,
            source_event=event,
            now=now,
        ):
            created += 1
    return created


def notify_manual_escalation(
    escalation: Any, obligation: Any, requester: Principal, *, now: datetime
) -> int:
    from agni.obligations.application.scheduler import supervisors_for_queue

    application = obligation.application
    context = {
        "reference": (application.public_reference or application.draft_reference)
        if application
        else "-",
        "application_id": str(application.pk) if application else "",
        "kind": obligation.kind.replace("_", " ").lower(),
        "level": escalation.level,
        "requester": requester.display_name,
        "reason": escalation.reason,
        "queue": obligation.owner_queue.queue_key,
    }
    created = 0
    for recipient in supervisors_for_queue(obligation.owner_queue, now):
        if create_notification(
            recipient=recipient,
            template=MANUAL_ESCALATION,
            logical_key=f"escalation:{escalation.pk}",
            context=context,
            application=application,
            source_event=None,
            now=now,
        ):
            created += 1
    return created


# ---- jobs ------------------------------------------------------------------------------------


@jobs.register(FANOUT_JOB)
def run_fanout(job: LogicalJob) -> jobs.JobResult:
    now = jobs.current_clock().now()
    message = OutboxMessage.objects.filter(pk=job.aggregate_ref.get("outbox_id")).first()
    if message is None:
        return jobs.JobResult(AttemptOutcome.PERMANENT, error_code="OUTBOX_ROW_MISSING")

    def apply() -> None:
        fan_out_event(message, now=now)
        OutboxMessage.objects.filter(pk=message.pk).update(state="COMPLETE")

    return jobs.JobResult(AttemptOutcome.SUCCESS, apply=apply)


@jobs.register(DELIVER_JOB)
def run_delivery(job: LogicalJob) -> jobs.JobResult:
    now = jobs.current_clock().now()
    attempt = (
        DeliveryAttempt.objects.select_related("notification__recipient")
        .filter(pk=job.aggregate_ref.get("delivery_attempt_id"))
        .first()
    )
    if attempt is None:
        return jobs.JobResult(AttemptOutcome.PERMANENT, error_code="DELIVERY_ROW_MISSING")
    if attempt.state in (DeliveryState.ACCEPTED_BY_PROVIDER, DeliveryState.DELIVERED):
        return jobs.JobResult(AttemptOutcome.SUCCESS, disposition="ALREADY_SENT")
    notification = attempt.notification
    recipient = notification.recipient
    contact_ref = recipient.verified_contact_ref
    contact = ContactIdentity.objects.filter(pk=contact_ref).first() if contact_ref else None
    if contact is None or contact.verified_at is None:
        DeliveryAttempt.objects.filter(pk=attempt.pk).update(
            state=DeliveryState.FAILED, safe_failure_code="NO_VERIFIED_CONTACT"
        )
        return jobs.JobResult(AttemptOutcome.PERMANENT, error_code="NO_VERIFIED_CONTACT")
    normalized = normalize_contact(contact.channel, decrypt_contact(contact.ciphertext))
    DeliveryAttempt.objects.filter(pk=attempt.pk).update(
        state=DeliveryState.SENDING,
        attempts=attempt.attempts + 1,
        destination_masked=normalized.masked,
    )
    message = OutboundMessage(
        channel=attempt.channel,
        destination=normalized.value,
        destination_masked=normalized.masked,
        destination_lookup_hmac=normalized.lookup_hmac,
        subject=notification.in_app_title,
        body=notification.in_app_body,
        logical_id=attempt.pk,
        category=notification.category,
    )
    try:
        receipt = get_message_sender().send(message)
    except ProviderUnavailable as exc:
        DeliveryAttempt.objects.filter(pk=attempt.pk).update(
            state=DeliveryState.FAILED, safe_failure_code="PROVIDER_UNAVAILABLE"
        )
        return jobs.JobResult(
            AttemptOutcome.RETRYABLE, error_code="PROVIDER_UNAVAILABLE", safe_message=str(exc)[:80]
        )
    except ProviderRejected as exc:
        DeliveryAttempt.objects.filter(pk=attempt.pk).update(
            state=DeliveryState.FAILED, safe_failure_code="PROVIDER_REJECTED"
        )
        return jobs.JobResult(
            AttemptOutcome.PERMANENT, error_code="PROVIDER_REJECTED", safe_message=str(exc)[:80]
        )

    def apply() -> None:
        DeliveryAttempt.objects.filter(pk=attempt.pk).update(
            state=DeliveryState.ACCEPTED_BY_PROVIDER,
            provider_message_id=receipt.provider_message_id,
            sent_at=now,
            safe_failure_code=None,
        )

    return jobs.JobResult(
        AttemptOutcome.SUCCESS, provider_request_id=receipt.provider_message_id, apply=apply
    )
