"""Decision readiness (FR-20, UI-14): the server-calculated guard list. Pure functions over
facts gathered by the application layer. The same blockers disable the UI controls and refuse
the command, and the command re-evaluates them under the case lock - a readiness read never
authorises anything by itself (API-064)."""

from __future__ import annotations

from dataclasses import dataclass

APPROVE_STATUS = "REVIEW_PENDING"


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str
    refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "refs": list(self.refs)}


@dataclass(frozen=True)
class CaseFacts:
    status: str
    inspection_required: bool
    has_accepted_report: bool
    report_eligible: bool
    report_blockers: tuple[str, ...]
    open_mandatory_findings: tuple[str, ...]
    reinspection_outstanding: tuple[str, ...]
    open_attempt: bool
    routing_exception_open: bool
    open_notices: tuple[str, ...]
    decision_exists: bool
    reject_from: tuple[str, ...]


@dataclass(frozen=True)
class ActorFacts:
    has_grant: bool
    grant_out_of_scope: bool
    inspected_this_case: bool
    inspector_cannot_decide: bool


@dataclass(frozen=True)
class Readiness:
    approve: tuple[Blocker, ...]
    reject: tuple[Blocker, ...]

    @property
    def can_approve(self) -> bool:
        return not self.approve

    @property
    def can_reject(self) -> bool:
        return not self.reject


def authority_blockers(actor: ActorFacts) -> list[Blocker]:
    out: list[Blocker] = []
    if not actor.has_grant:
        if actor.grant_out_of_scope:
            out.append(
                Blocker(
                    "AUTHORITY_SCOPE_MISMATCH",
                    "Your decision authority does not cover this jurisdiction",
                )
            )
        else:
            out.append(
                Blocker(
                    "AUTHORITY_MISSING",
                    "An approved case.decide authority grant is required",
                )
            )
    if actor.inspector_cannot_decide and actor.inspected_this_case:
        out.append(
            Blocker(
                "SEPARATION_OF_DUTIES",
                "The officer who inspected this case cannot decide it",
            )
        )
    return out


def approve_blockers(case: CaseFacts, actor: ActorFacts) -> tuple[Blocker, ...]:
    out: list[Blocker] = []
    if case.decision_exists:
        out.append(Blocker("DECISION_EXISTS", "A final decision is already recorded for this case"))
    if case.status != APPROVE_STATUS:
        out.append(
            Blocker(
                "STATUS_NOT_REVIEW_PENDING",
                f"Approval requires {APPROVE_STATUS}; the case is {case.status}",
            )
        )
    if case.routing_exception_open:
        out.append(Blocker("ROUTING_UNRESOLVED", "An accountable routing exception is still open"))
    if case.open_attempt:
        out.append(Blocker("INSPECTION_OPEN", "An inspection attempt is still open"))
    if case.inspection_required and not case.has_accepted_report:
        out.append(
            Blocker(
                "NO_ACCEPTED_REPORT",
                "The policy requires an accepted inspection report",
            )
        )
    if case.has_accepted_report and not case.report_eligible:
        out.append(
            Blocker(
                "REPORT_NOT_ELIGIBLE",
                "The accepted report carries mandatory blockers",
                case.report_blockers,
            )
        )
    if case.open_mandatory_findings:
        out.append(
            Blocker(
                "MANDATORY_FINDINGS_OPEN",
                "Mandatory findings are not verified closed",
                case.open_mandatory_findings,
            )
        )
    if case.reinspection_outstanding:
        out.append(
            Blocker(
                "REINSPECTION_OUTSTANDING",
                "A required reinspection has not been completed",
                case.reinspection_outstanding,
            )
        )
    if case.open_notices:
        out.append(
            Blocker(
                "NOTICE_OPEN",
                "A published notice is still awaiting the applicant",
                case.open_notices,
            )
        )
    out.extend(authority_blockers(actor))
    return tuple(out)


def reject_blockers(case: CaseFacts, actor: ActorFacts) -> tuple[Blocker, ...]:
    out: list[Blocker] = []
    if case.decision_exists:
        out.append(Blocker("DECISION_EXISTS", "A final decision is already recorded for this case"))
    if case.status not in case.reject_from:
        out.append(
            Blocker(
                "STATUS_NOT_PERMITTED",
                "The active profile permits rejection only from " + ", ".join(case.reject_from),
            )
        )
    out.extend(authority_blockers(actor))
    return tuple(out)


def readiness(case: CaseFacts, actor: ActorFacts) -> Readiness:
    return Readiness(approve=approve_blockers(case, actor), reject=reject_blockers(case, actor))
