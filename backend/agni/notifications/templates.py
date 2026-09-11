"""Versioned notification templates (FR-23). Each template names its audience rule, category,
whether it is a mandatory service message (channel preferences cannot suppress it) and the
safe render context it may use. Bodies never contain attachment URLs or internal notes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Audience rules resolved by the fan-out: who receives the event.
APPLICANT = "APPLICANT"  # the case applicant (and acting operator when different)
SUPERVISORS = "SUPERVISORS"  # supervisors of the owner queue's jurisdiction
ASSIGNED_OFFICER = "ASSIGNED_OFFICER"  # current assigned officer of the referenced attempt


@dataclass(frozen=True)
class Template:
    key: str
    version: int
    audiences: tuple[str, ...]
    category: str
    mandatory: bool
    title: str
    body: str
    target: str  # path template with {application_id} / {notice_id} / {inspection_id}


TEMPLATES: dict[str, Template] = {
    "application.withdrawn.v1": Template(
        "case-withdrawn",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Application {reference} withdrawn",
        "The application {reference} was withdrawn at your request. Open work on it was closed; "
        "nothing else changed.",
        "/applications/{application_id}",
    ),
    "certificate.status_changed.v1": Template(
        "certificate-status",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Certificate {certificate_number}: {action}",
        "An authorised status action ({action}) was recorded for certificate "
        "{certificate_number}. {public_reason}",
        "/applications/{application_id}",
    ),
    "inspection.clarification_requested.v1": Template(
        "clarification-requested",
        1,
        (APPLICANT, SUPERVISORS),
        "INSPECTION",
        True,
        "Follow-up visit required for {reference}",
        "The review of {reference} needs clarification on site; a new visit (attempt "
        "{attempt_number}) will be scheduled.",
        "/applications/{application_id}",
    ),
    "decision.approved.v1": Template(
        "decision-approved",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Application {reference} approved - certificate processing",
        "A favourable decision was recorded for {reference}. {public_reason} The sample "
        "certificate is being processed; you will be notified when it is published.",
        "/applications/{application_id}",
    ),
    "decision.rejected.v1": Template(
        "decision-rejected",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Application {reference} was not approved",
        "The department recorded a decision on {reference}. {public_reason}",
        "/applications/{application_id}",
    ),
    "certificate.published.v1": Template(
        "certificate-published",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Sample certificate {certificate_number} published for {reference}",
        "The demonstration certificate {certificate_number} for {reference} is now in the "
        "register (valid until {valid_until}). It is a sample, not an official certificate.",
        "/applications/{application_id}",
    ),
    "application.submitted.v1": Template(
        "case-submitted",
        1,
        (APPLICANT, SUPERVISORS),
        "CASE",
        True,
        "Application {reference} received",
        "Your application {reference} was received by {queue}. You will be notified of every step.",
        "/applications/{application_id}",
    ),
    "scrutiny.started.v1": Template(
        "scrutiny-started",
        1,
        (APPLICANT,),
        "CASE",
        False,
        "Scrutiny started for {reference}",
        "The department has started checking your application {reference}.",
        "/applications/{application_id}",
    ),
    "notice.published.v1": Template(
        "notice-information",
        1,
        (APPLICANT,),
        "NOTICE",
        True,
        "Information required for {reference}",
        "A notice with {item_count} item(s) asks for information. Respond by {due}.",
        "/applications/{application_id}/notices/{notice_id}",
    ),
    "deficiencies.published.v1": Template(
        "notice-deficiency",
        1,
        (APPLICANT,),
        "NOTICE",
        True,
        "Corrections required for {reference}",
        "The inspection recorded deficiencies. A notice with {item_count} item(s) explains "
        "what to correct. Respond by {due}.",
        "/applications/{application_id}/notices/{notice_id}",
    ),
    "notice.response_received.v1": Template(
        "notice-response",
        1,
        (SUPERVISORS,),
        "REVIEW",
        False,
        "Reply received on {reference}",
        "The applicant replied to notice items {items}. Review is waiting.",
        "/applications/{application_id}/notices/{notice_id}",
    ),
    "notice.item_reviewed.v1": Template(
        "notice-item-reviewed",
        1,
        (APPLICANT,),
        "NOTICE",
        True,
        "Notice item {item_code} {outcome}",
        "Your reply to item {item_code} was {outcome_lower}. {public_reason}",
        "/applications/{application_id}/notices/{notice_id}",
    ),
    "information.accepted.v1": Template(
        "information-accepted",
        1,
        (APPLICANT,),
        "CASE",
        False,
        "Information accepted for {reference}",
        "The information round is complete; your application is back in scrutiny.",
        "/applications/{application_id}",
    ),
    "inspection.requested.v1": Template(
        "inspection-required",
        1,
        (APPLICANT,),
        "APPOINTMENT",
        True,
        "Site inspection required for {reference}",
        "A site inspection is required. You will receive the appointment once scheduled.",
        "/applications/{application_id}",
    ),
    "inspection.scheduled.v1": Template(
        "inspection-scheduled",
        1,
        (APPLICANT, ASSIGNED_OFFICER),
        "APPOINTMENT",
        True,
        "Inspection appointment for {reference}",
        "The site inspection is scheduled for {scheduled_start} ({timezone}).",
        "/applications/{application_id}",
    ),
    "inspection.visit_failed.v1": Template(
        "inspection-visit-failed",
        1,
        (APPLICANT, SUPERVISORS),
        "APPOINTMENT",
        True,
        "Inspection visit could not be completed ({reference})",
        "The visit was not completed ({reason_code}). A new appointment will be arranged.",
        "/applications/{application_id}",
    ),
    "inspection.report_accepted.v1": Template(
        "report-accepted",
        1,
        (APPLICANT, SUPERVISORS),
        "REVIEW",
        False,
        "Inspection report accepted for {reference}",
        "The inspection report was accepted; the application moves to review.",
        "/applications/{application_id}",
    ),
    "inspection.reinspection_requested.v1": Template(
        "reinspection-required",
        1,
        (APPLICANT,),
        "APPOINTMENT",
        True,
        "Reinspection required for {reference}",
        "A physical reinspection is required for the outstanding findings.",
        "/applications/{application_id}",
    ),
    "finding.reviewed.v1": Template(
        "finding-reviewed",
        1,
        (APPLICANT,),
        "NOTICE",
        True,
        "Finding {item_code}: {outcome}",
        "The reviewer recorded {outcome_lower} for finding {item_code}. {public_reason}",
        "/applications/{application_id}",
    ),
    "compliance.verified.v1": Template(
        "compliance-verified",
        1,
        (APPLICANT,),
        "CASE",
        False,
        "Corrections verified for {reference}",
        "All mandatory findings are verified closed; the application returns to review.",
        "/applications/{application_id}",
    ),
    "routing.exception_opened.v1": Template(
        "routing-exception",
        1,
        (SUPERVISORS,),
        "CASE",
        False,
        "Routing exception on {reference}",
        "The case could not be routed automatically and is held by {queue}.",
        "/applications/{application_id}",
    ),
}

THRESHOLD_REMINDER = Template(
    "obligation-reminder",
    1,
    (),
    "OBLIGATION",
    False,
    "{kind} due {due}",
    "Obligation {kind} on {reference} reaches {threshold}. Due {due}.",
    "/applications/{application_id}",
)
THRESHOLD_ESCALATION = Template(
    "obligation-escalation",
    1,
    (),
    "ESCALATION",
    False,
    "Escalation L{level}: {kind} overdue on {reference}",
    "Obligation {kind} on {reference} is overdue ({threshold}). "
    "An intervention task is open for {queue}.",
    "/monitoring",
)
MANUAL_ESCALATION = Template(
    "manual-escalation",
    1,
    (),
    "ESCALATION",
    False,
    "Manual escalation L{level} on {reference}",
    "{requester} escalated {kind} on {reference}: {reason}",
    "/monitoring",
)


class _Safe(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "-"


def render(template: Template, context: dict[str, Any]) -> tuple[str, str, str]:
    safe = _Safe({k: ("-" if v is None else v) for k, v in context.items()})
    return (
        template.title.format_map(safe)[:200],
        template.body.format_map(safe),
        template.target.format_map(safe)[:300],
    )
