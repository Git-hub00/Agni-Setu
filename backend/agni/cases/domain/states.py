"""The one canonical application state vocabulary (workflow s.1) and the authorized
transition catalogue (workflow s.3). Pure data: no ORM, no HTTP.

`TRANSITIONS` records which named command may move a case from which states. Guards beyond
state (authority, evidence, policy) live in each transition's application service; a
transition never happens implicitly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCRUTINY = "SCRUTINY"
    INFO_REQUIRED = "INFO_REQUIRED"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    REVIEW_PENDING = "REVIEW_PENDING"
    COMPLIANCE_PENDING = "COMPLIANCE_PENDING"
    APPROVED_PENDING_ISSUE = "APPROVED_PENDING_ISSUE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


TERMINAL_STATES: Final[frozenset[ApplicationStatus]] = frozenset(
    {ApplicationStatus.COMPLETED, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
)

DISPLAY_LABELS: Final[dict[ApplicationStatus, str]] = {
    ApplicationStatus.DRAFT: "Draft",
    ApplicationStatus.SUBMITTED: "Submitted",
    ApplicationStatus.SCRUTINY: "Under scrutiny",
    ApplicationStatus.INFO_REQUIRED: "Information required",
    ApplicationStatus.INSPECTION_PENDING: "Inspection pending",
    ApplicationStatus.REVIEW_PENDING: "Review pending",
    ApplicationStatus.COMPLIANCE_PENDING: "Compliance pending",
    ApplicationStatus.APPROVED_PENDING_ISSUE: "Approved - certificate processing",
    ApplicationStatus.COMPLETED: "Completed",
    ApplicationStatus.REJECTED: "Rejected",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}

# (transition id, command, from-states, to-state, event type) - workflow s.3. TR-12 rejection
# stages other than REVIEW_PENDING and TR-15 are profile-gated and disabled in the demo.
TRANSITIONS: Final[
    tuple[tuple[str, str, frozenset[ApplicationStatus], ApplicationStatus, str], ...]
] = (
    (
        "TR-01",
        "submit",
        frozenset({ApplicationStatus.DRAFT}),
        ApplicationStatus.SUBMITTED,
        "application.submitted.v1",
    ),
    (
        "TR-02",
        "start-scrutiny",
        frozenset({ApplicationStatus.SUBMITTED}),
        ApplicationStatus.SCRUTINY,
        "scrutiny.started.v1",
    ),
    (
        "TR-03",
        "request-information",
        frozenset({ApplicationStatus.SCRUTINY}),
        ApplicationStatus.INFO_REQUIRED,
        "notice.published.v1",
    ),
    (
        "TR-04",
        "accept-information",
        frozenset({ApplicationStatus.INFO_REQUIRED}),
        ApplicationStatus.SCRUTINY,
        "information.accepted.v1",
    ),
    (
        "TR-05",
        "require-inspection",
        frozenset({ApplicationStatus.SCRUTINY}),
        ApplicationStatus.INSPECTION_PENDING,
        "inspection.requested.v1",
    ),
    (
        "TR-06",
        "accept-report",
        frozenset({ApplicationStatus.INSPECTION_PENDING}),
        ApplicationStatus.REVIEW_PENDING,
        "inspection.report_accepted.v1",
    ),
    (
        "TR-07",
        "issue-deficiencies",
        frozenset({ApplicationStatus.REVIEW_PENDING}),
        ApplicationStatus.COMPLIANCE_PENDING,
        "deficiencies.published.v1",
    ),
    (
        "TR-08",
        "complete-corrections",
        frozenset({ApplicationStatus.COMPLIANCE_PENDING}),
        ApplicationStatus.REVIEW_PENDING,
        "compliance.verified.v1",
    ),
    (
        "TR-09",
        "require-reinspection",
        frozenset({ApplicationStatus.COMPLIANCE_PENDING}),
        ApplicationStatus.INSPECTION_PENDING,
        "inspection.reinspection_requested.v1",
    ),
    (
        "TR-10",
        "approve",
        frozenset({ApplicationStatus.REVIEW_PENDING}),
        ApplicationStatus.APPROVED_PENDING_ISSUE,
        "decision.approved.v1",
    ),
    (
        "TR-11",
        "publish-instrument",
        frozenset({ApplicationStatus.APPROVED_PENDING_ISSUE}),
        ApplicationStatus.COMPLETED,
        "certificate.published.v1",
    ),
    (
        "TR-12",
        "reject",
        frozenset({ApplicationStatus.REVIEW_PENDING}),
        ApplicationStatus.REJECTED,
        "decision.rejected.v1",
    ),
    (
        "TR-13",
        "withdraw",
        frozenset(
            {
                ApplicationStatus.DRAFT,
                ApplicationStatus.SUBMITTED,
                ApplicationStatus.SCRUTINY,
                ApplicationStatus.INFO_REQUIRED,
                ApplicationStatus.INSPECTION_PENDING,
                ApplicationStatus.COMPLIANCE_PENDING,
            }
        ),
        ApplicationStatus.WITHDRAWN,
        "application.withdrawn.v1",
    ),
    (
        "TR-14",
        "return-for-clarification",
        frozenset({ApplicationStatus.REVIEW_PENDING}),
        ApplicationStatus.INSPECTION_PENDING,
        "inspection.clarification_requested.v1",
    ),
)


def allowed_transitions(current: ApplicationStatus) -> list[tuple[str, str, ApplicationStatus]]:
    """(transition id, command, target) pairs whose *state* guard admits `current`."""
    return [
        (tid, command, target)
        for tid, command, sources, target, _ in TRANSITIONS
        if current in sources
    ]


def transition_for(
    command: str, current: ApplicationStatus
) -> tuple[str, ApplicationStatus, str] | None:
    for tid, cmd, sources, target, event in TRANSITIONS:
        if cmd == command and current in sources:
            return tid, target, event
    return None
