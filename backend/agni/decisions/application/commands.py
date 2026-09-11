"""TR-10 / TR-12 decisions (API-064/065/066; FR-20). The server gathers the facts, computes the
readiness under the case lock and binds the outcome to the exact evidence reviewed and to the
authority grant in force. Approval creates the issuance intent (FR-21) in the same transaction;
the instrument itself is produced by the durable issuance job, never inside this command."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from agni.cases.application.holds import ensure_not_on_hold
from agni.cases.application.submission import (
    _lock_case_for_staff,
    _reason,
    enter_stage,
    record_event,
)
from agni.cases.domain.states import transition_for
from agni.cases.models import Application, EventAudience, SubmissionRevision
from agni.identity.authz import AuthzSnapshot, load_snapshot
from agni.identity.domain.roles import Capability
from agni.identity.models import PrincipalKind
from agni.inspections.application.commands import _intent
from agni.inspections.models import Inspection, InspectionReport, InspectionStatus
from agni.notices.application.commands import (
    _open_obligation,
    _pinned_policy,
    _satisfy,
    _task_budget,
)
from agni.notices.domain.rules import open_mandatory_findings, reinspection_outstanding
from agni.notices.models import Finding, Notice, NoticeState
from agni.obligations.models import Obligation, ObligationKind, ObligationState, TimeBasis
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    AuthorityScopeMismatch,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    SeparationOfDuties,
    ValidationFailed,
    VersionConflict,
    Violation,
)
from agni.policies.models import PolicyVersion
from agni.routing.models import RoutingException, RoutingExceptionState

from ..domain.readiness import (
    ActorFacts,
    Blocker,
    CaseFacts,
    approve_blockers,
    readiness,
    reject_blockers,
)
from ..models import Decision, DecisionKind

OPEN_ATTEMPTS = (
    InspectionStatus.REQUESTED,
    InspectionStatus.SCHEDULED,
    InspectionStatus.IN_PROGRESS,
)


# ---- facts ------------------------------------------------------------------------------------


def current_revision(application: Application) -> SubmissionRevision | None:
    return SubmissionRevision.objects.filter(application=application).order_by("-number").first()


def current_report(application: Application) -> InspectionReport | None:
    """The most recently accepted report of the case (the evidence a favourable decision cites)."""
    return (
        InspectionReport.objects.filter(inspection__application=application)
        .select_related("inspection")
        .order_by("-accepted_at", "-revision_number")
        .first()
    )


def case_facts(application: Application, policy: PolicyVersion) -> CaseFacts:
    payload = policy.payload
    report = current_report(application)
    findings = list(Finding.objects.filter(application=application))
    evaluation: dict[str, Any] = dict(report.evaluation) if report is not None else {}
    blockers = evaluation.get("blockers", [])
    return CaseFacts(
        status=application.status,
        inspection_required=bool(payload.get("inspection_required", False)),
        has_accepted_report=report is not None,
        report_eligible=bool(evaluation.get("eligible_for_review", False)),
        report_blockers=tuple(
            f"{b.get('code')}:{b.get('item_code')}" for b in blockers if isinstance(b, dict)
        ),
        open_mandatory_findings=tuple(open_mandatory_findings(findings)),
        reinspection_outstanding=tuple(reinspection_outstanding(findings)),
        open_attempt=Inspection.objects.filter(
            application=application, status__in=OPEN_ATTEMPTS
        ).exists(),
        routing_exception_open=RoutingException.objects.filter(
            application=application, state=RoutingExceptionState.OPEN
        ).exists(),
        open_notices=tuple(
            f"{n.type}:{n.round_number}"
            for n in Notice.objects.filter(
                application=application, state=NoticeState.PUBLISHED
            ).order_by("round_number")
        ),
        decision_exists=Decision.objects.filter(application=application).exists(),
        reject_from=tuple(str(s) for s in payload.get("reject_from", ["REVIEW_PENDING"])),
    )


def actor_facts(
    snapshot: AuthzSnapshot, application: Application, policy: PolicyVersion
) -> ActorFacts:
    jurisdiction_id = application.owner_queue.jurisdiction_id
    grant = snapshot.grant_for(Capability.CASE_DECIDE, jurisdiction_id=jurisdiction_id)
    any_grant = any(g.capability == Capability.CASE_DECIDE for g in snapshot.grants)
    inspected = InspectionReport.objects.filter(
        inspection__application=application, submitted_by_id=snapshot.principal_id
    ).exists()
    rules = policy.payload.get("separation_of_duties", {})
    inspector_cannot_decide = (
        bool(rules.get("inspector_cannot_decide", True)) if isinstance(rules, dict) else True
    )
    return ActorFacts(
        has_grant=grant is not None,
        grant_out_of_scope=grant is None and any_grant,
        inspected_this_case=inspected,
        inspector_cannot_decide=inspector_cannot_decide,
    )


def readiness_body(
    application: Application, snapshot: AuthzSnapshot, now: datetime
) -> dict[str, Any]:
    """API-064 `DecisionReadiness`: server-calculated guard list for the current actor."""
    policy = _pinned_policy(application)
    facts = case_facts(application, policy)
    actor = actor_facts(snapshot, application, policy)
    result = readiness(facts, actor)
    revision = current_revision(application)
    report = current_report(application)
    grant = snapshot.grant_for(
        Capability.CASE_DECIDE, jurisdiction_id=application.owner_queue.jurisdiction_id
    )
    return {
        "application_id": str(application.pk),
        "public_reference": application.public_reference,
        "status": application.status,
        "version": application.version,
        "evidence": {
            "submission_revision_id": str(revision.pk) if revision else None,
            "submission_number": revision.number if revision else None,
            "submission_sha256": revision.sha256 if revision else None,
            "report_id": str(report.pk) if report else None,
            "report_revision": report.revision_number if report else None,
            "report_sha256": report.sha256 if report else None,
            "report_eligible": facts.report_eligible if report else None,
            "policy_version_id": str(policy.pk),
            "policy_number": policy.number,
            "open_mandatory_findings": list(facts.open_mandatory_findings),
            "reinspection_outstanding": list(facts.reinspection_outstanding),
            "open_notices": list(facts.open_notices),
        },
        "authority": {
            "grant_id": str(grant.grant_id) if grant else None,
            "scope": str(grant.scope_kind.value) if grant else None,
            "inspector_cannot_decide": actor.inspector_cannot_decide,
            "inspected_this_case": actor.inspected_this_case,
        },
        "approve": {
            "eligible": result.can_approve,
            "blockers": [b.as_dict() for b in result.approve],
        },
        "reject": {
            "eligible": result.can_reject,
            "blockers": [b.as_dict() for b in result.reject],
        },
        "evaluated_at": now.isoformat(),
        "notice": (
            "Readiness is advisory: the decision command re-evaluates every guard under the "
            "case lock."
        ),
    }


def decision_body(decision: Decision, *, staff: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "decision_id": str(decision.pk),
        "decision_number": decision.decision_number,
        "kind": decision.kind,
        "public_reason": decision.public_reason,
        "accepted_at": decision.accepted_at.isoformat(),
        "submission_revision_id": str(decision.submitted_revision_id),
        "report_id": str(decision.report_id) if decision.report_id else None,
        "policy_version_id": str(decision.policy_version_id),
    }
    if staff:
        body.update(
            {
                "reason": decision.reason,
                "actor_id": str(decision.actor_id),
                "authority_grant_id": str(decision.authority_grant_id),
                "evidence_snapshot": decision.evidence_snapshot,
                "sha256": decision.sha256,
            }
        )
    return body


# ---- command ------------------------------------------------------------------------------------


def _text(data: dict[str, Any], key: str, violations: list[Violation]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not (10 <= len(value.strip()) <= 4000):
        violations.append(Violation(f"/{key}", "length", "10 to 4000 characters"))
        return ""
    return value.strip()


def _uuid(value: Any, pointer: str, violations: list[Violation]) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError:
        violations.append(Violation(pointer, "invalid", "must be a UUID"))
        return None


def _raise_for(blockers: tuple[Blocker, ...]) -> None:
    if not blockers:
        return
    codes = [b.code for b in blockers]
    if codes == ["AUTHORITY_MISSING"]:
        raise Forbidden("This action requires an approved case.decide authority grant")
    if codes == ["AUTHORITY_SCOPE_MISMATCH"]:
        raise AuthorityScopeMismatch("Your decision authority does not cover this jurisdiction")
    if codes == ["SEPARATION_OF_DUTIES"]:
        raise SeparationOfDuties("The officer who inspected this case cannot decide it")
    # Catalogue code INVALID_TRANSITION (docs/06 s.5): the guards of this transition are not
    # satisfied; the blocker list travels as a problem extension for UI-14.
    raise InvalidTransition(
        "The decision guards are not satisfied",
        extensions={"blockers": [b.as_dict() for b in blockers]},
    )


class RecordDecision(CommandHandler[Application]):
    """API-065: TR-10 approve (REVIEW_PENDING -> APPROVED_PENDING_ISSUE) or TR-12 reject
    (profile-permitted stages -> REJECTED). The payload never names the actor, the grant, a
    status or a certificate number: the server identifies the effective grant and freezes the
    evidence snapshot (API s.9)."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff record decisions")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return _lock_case_for_staff(uow)

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "kind",
            "submission_revision_id",
            "report_id",
            "reason",
            "public_reason",
            "review_acknowledged",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        kind = str(data.get("kind") or "")
        if kind not in DecisionKind.values:
            violations.append(Violation("/kind", "invalid", "APPROVE or REJECT"))
        reason = _reason(data, violations)
        public_reason = _text(data, "public_reason", violations)
        if data.get("review_acknowledged") is not True:
            violations.append(
                Violation(
                    "/review_acknowledged",
                    "required",
                    "acknowledge the review summary explicitly (no preselected approval)",
                )
            )
        if "submission_revision_id" not in data:
            violations.append(
                Violation(
                    "/submission_revision_id",
                    "required",
                    "the accepted submission revision being decided",
                )
            )
        revision_id = _uuid(
            data.get("submission_revision_id"), "/submission_revision_id", violations
        )
        report_id = _uuid(data.get("report_id"), "/report_id", violations)
        if kind == DecisionKind.APPROVE and data.get("report_id") in (None, ""):
            violations.append(
                Violation(
                    "/report_id", "required", "a favourable decision cites the accepted report"
                )
            )
        if violations:
            raise ValidationFailed(violations=violations)

        policy = _pinned_policy(target)
        revision = current_revision(target)
        if revision is None:
            raise InvalidTransition("The case has no accepted submission to decide")
        # Reviewed evidence that moved on is a stale read (catalogue VERSION_CONFLICT, 412):
        # UI-14 reloads the changed evidence and requires a renewed review.
        if revision_id != revision.pk:
            raise VersionConflict(
                "The accepted submission revision changed since your review",
                extensions={
                    "changed": "submission_revision",
                    "current_submission_revision_id": str(revision.pk),
                },
            )
        report = current_report(target)
        if report_id is not None and (report is None or report.pk != report_id):
            raise VersionConflict(
                "The accepted report changed since your review",
                extensions={
                    "changed": "report",
                    "current_report_id": str(report.pk) if report else None,
                },
            )

        snapshot = load_snapshot(uow.actor, uow.now)
        facts = case_facts(target, policy)
        actor = actor_facts(snapshot, target, policy)
        approve = approve_blockers(facts, actor)
        reject = reject_blockers(facts, actor)
        _raise_for(approve if kind == DecisionKind.APPROVE else reject)
        grant = snapshot.grant_for(
            Capability.CASE_DECIDE, jurisdiction_id=target.owner_queue.jurisdiction_id
        )
        if grant is None:  # unreachable after the blockers; keeps the type narrow
            raise Forbidden("This action requires an approved case.decide authority grant")

        command = "approve" if kind == DecisionKind.APPROVE else "reject"
        transition = transition_for(command, target.status_enum)
        if transition is None:
            raise InvalidTransition(f"'{command}' is not permitted from {target.status}")
        ensure_not_on_hold(target, scope="decision")
        _, target_state, event_type = transition

        new_version = target.version + 1  # the kernel increments after apply; events carry it
        evidence_snapshot: dict[str, Any] = {
            "submission_revision_id": str(revision.pk),
            "submission_number": revision.number,
            "submission_sha256": revision.sha256,
            "report_id": str(report.pk) if report else None,
            "report_revision": report.revision_number if report else None,
            "report_sha256": report.sha256 if report else None,
            "report_evaluation": dict(report.evaluation) if report else None,
            "findings": [
                {"item_code": f.checklist_item_code, "severity": f.severity, "state": f.state}
                for f in Finding.objects.filter(application=target).order_by("checklist_item_code")
            ],
            "policy_version_id": str(policy.pk),
            "policy_number": policy.number,
            "status_before": target.status,
            "case_version_before": target.version,
            "readiness": {
                "approve": [b.as_dict() for b in approve],
                "reject": [b.as_dict() for b in reject],
            },
        }
        number = Decision.objects.filter(application=target).count() + 1
        digest = canonical_sha256(
            {
                "application_id": target.pk,
                "decision_number": number,
                "kind": kind,
                "submission_revision_id": revision.pk,
                "report_id": report.pk if report else None,
                "evidence_snapshot": evidence_snapshot,
                "policy_version_id": policy.pk,
                "authority_grant_id": grant.grant_id,
                "actor_id": uow.actor.pk,
                "reason": reason,
                "public_reason": public_reason,
                "accepted_at": uow.now,
            }
        )
        decision = Decision.objects.create(
            application=target,
            decision_number=number,
            kind=kind,
            submitted_revision=revision,
            report=report if report_id is not None else None,
            evidence_snapshot=evidence_snapshot,
            policy_version=policy,
            authority_grant_id=grant.grant_id,
            actor=uow.actor,
            reason=reason,
            public_reason=public_reason,
            accepted_at=uow.now,
            sha256=digest,
        )
        target.status = target_state.value
        event = record_event(
            uow,
            target,
            event_type,
            {
                "decision_id": str(decision.pk),
                "decision_number": number,
                "kind": kind,
                "public_reason": public_reason,
                "submission_revision_id": str(revision.pk),
                "report_id": str(report.pk) if report_id is not None and report else None,
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        record_event(
            uow,
            target,
            "decision.rationale.v1",
            {
                "decision_id": str(decision.pk),
                "reason": reason,
                "authority_grant_id": str(grant.grant_id),
                "evidence_sha256": digest,
            },
            audience=EventAudience.INTERNAL,
            ordinal=1,
            version=new_version,
        )
        stage = enter_stage(target, target.status, event, uow.now, target.policy_version_id)
        target.version = new_version
        target.save(update_fields=["status", "current_stage_instance", "version", "updated_at"])
        _satisfy(target, ObligationKind.REVIEW_TASK, event)

        issuance: dict[str, Any] | None = None
        if kind == DecisionKind.APPROVE:
            _open_obligation(
                target,
                stage,
                ObligationKind.ISSUANCE_TASK,
                policy=policy,
                basis=TimeBasis.CALENDAR,
                budget=_task_budget(policy, "issuance_calendar_minutes"),
                event=event,
                now=uow.now,
            )
            from agni.certificates.application.issuance import create_issuance_request

            request = create_issuance_request(target, decision, now=uow.now)
            issuance = {
                "issuance_request_id": str(request.pk),
                "certificate_number": request.certificate_number,
                "state": request.state,
            }
        else:
            # Terminal outcome: open obligations are closed by the decision instrument. They are
            # CANCELLED, never marked satisfied as if the work had completed.
            Obligation.objects.filter(
                application=target,
                state__in=[ObligationState.ACTIVE, ObligationState.PAUSED],
            ).update(state=ObligationState.CANCELLED, satisfied_event=event)

        body: dict[str, Any] = {
            "decision_id": str(decision.pk),
            "decision_number": number,
            "kind": kind,
            "application_id": str(target.pk),
            "public_reference": target.public_reference,
            "status": target.status,
            "accepted_at": uow.now.isoformat(),
            "public_reason": public_reason,
            "authority_grant_id": str(grant.grant_id),
            "evidence_sha256": digest,
            "issuance": issuance,
        }
        return CommandOutcome(
            status=201,
            body=body,
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    f"decision.{kind.lower()}",
                    {
                        "decision_id": str(decision.pk),
                        "decision_number": number,
                        "submission_revision_id": str(revision.pk),
                        "report_id": str(report.pk) if report else None,
                        "public_reason": public_reason[:200],
                        "evidence_sha256": digest,
                    },
                    authority_grant_id=grant.grant_id,
                )
            ],
            intents=[_intent(event, uow)],
        )
