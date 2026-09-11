"""Report draft and immutable report submission (FR-13/FR-14; API-045, API-047; TR-06).

The assigned officer saves a server draft (child of the inspection, guarded by the inspection
ETag) and submits the complete report once: observations are validated against the pinned
checklist, evidence must be CLEAN documents of the same case, the evaluation is computed
deterministically and stored with the immutable revision, the attempt completes, the assignment
is fulfilled and TR-06 moves the case to REVIEW_PENDING with a review-task obligation. A
mandatory FAIL or NOT_VERIFIED does not stop acceptance of the report - it blocks eligibility
for a favourable decision, which the evaluation records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agni.cases.application.submission import enter_stage, record_event
from agni.cases.domain.states import transition_for
from agni.cases.models import Application, EventAudience
from agni.documents.models import DocumentVersion, ScanState
from agni.identity.models import PrincipalKind
from agni.obligations.domain.clock import WorkingCalendar, due_instant
from agni.obligations.models import Obligation, ObligationKind, ObligationState, TimeBasis
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    PreconditionRequired,
    ResourceNotFound,
    ValidationFailed,
    VersionConflict,
    Violation,
)
from agni.policies.models import PolicyArtifact, PolicyVersion

from ..domain.checklist import checklist_items, evaluate, validate_observations
from ..models import (
    AssignmentState,
    Inspection,
    InspectionDraft,
    InspectionReport,
    InspectionStatus,
    ReportEvidence,
)
from .commands import (
    _application_version,
    _assigned_officer_only,
    _assignment_version,
    _instant,
    _intent,
    _lock_inspection,
    inspection_body,
)


def draft_body(d: InspectionDraft) -> dict[str, Any]:
    return {
        "draft_id": str(d.pk),
        "inspection_id": str(d.inspection_id),
        "base_inspection_version": d.base_inspection_version,
        "assignment_version": d.assignment_version,
        "observations": d.payload.get("observations", []),
        "summary": d.payload.get("summary", ""),
        "captured_at": d.payload.get("captured_at"),
        "local_revision": d.local_revision,
        "saved_at": d.saved_at.isoformat(),
        "version": d.version,
    }


def report_body(r: InspectionReport) -> dict[str, Any]:
    return {
        "report_id": str(r.pk),
        "inspection_id": str(r.inspection_id),
        "revision_number": r.revision_number,
        "assignment_id": str(r.assignment_id),
        "checklist_ref": r.checklist_artifact.reference,
        "submitted_by": str(r.submitted_by_id),
        "captured_at": r.captured_at.isoformat() if r.captured_at else None,
        "capture_unavailable_reason": r.capture_unavailable_reason or None,
        "accepted_at": r.accepted_at.isoformat(),
        "observations": r.observations,
        "summary": r.summary,
        "evaluation": r.evaluation,
        "sha256": r.sha256,
        "supersedes_id": str(r.supersedes_id) if r.supersedes_id else None,
        "evidence": [
            {
                "item_code": e.item_code,
                "document_version_id": str(e.document_version_id),
                "sha256": e.capture_metadata.get("sha256"),
            }
            for e in r.evidence.all()
        ],
    }


def _checklist_version_ok(
    data: dict[str, Any], inspection: Inspection, violations: list[Violation]
) -> None:
    expected = inspection.checklist_artifact
    value = data.get("checklist_version")
    if value not in (expected.key, expected.reference):
        violations.append(
            Violation(
                "/checklist_version", "stale", f"report must target checklist {expected.reference}"
            )
        )


def _clean_documents(inspection: Inspection, doc_ids: set[str]) -> dict[str, DocumentVersion]:
    """Only CLEAN versions of this case may be cited as evidence (wrong-case evidence denied)."""
    return {
        str(d.pk): d
        for d in DocumentVersion.objects.filter(
            pk__in=[UUID(x) for x in doc_ids],
            application_id=inspection.application_id,
            scan_state=ScanState.CLEAN,
        )
    }


def _evidence_violations(
    inspection: Inspection, observations: list[dict[str, Any]]
) -> tuple[dict[str, DocumentVersion], list[Violation]]:
    wanted = {doc for o in observations for doc in o["document_version_ids"]}
    found = _clean_documents(inspection, wanted) if wanted else {}
    violations: list[Violation] = []
    for index, observation in enumerate(observations):
        for j, doc in enumerate(observation["document_version_ids"]):
            if doc not in found:
                violations.append(
                    Violation(
                        f"/observations/{index}/document_version_ids/{j}",
                        "not_clean_case_evidence",
                        "must be a CLEAN file of this case",
                    )
                )
    return found, violations


class SaveReportDraft(CommandHandler[InspectionDraft]):
    """API-045: server draft for the assigned officer. Guarded by the inspection ETag; the draft
    is the versioned child so the inspection version does not move on every save."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff perform inspections")

    def lock_target(self, uow: UnitOfWork) -> InspectionDraft | None:
        inspection = _lock_inspection(uow)
        _assigned_officer_only(uow, inspection)
        self._inspection = inspection
        return None

    def apply(
        self, uow: UnitOfWork, target: InspectionDraft | None
    ) -> CommandOutcome[InspectionDraft]:
        inspection = self._inspection
        assignment = _assigned_officer_only(uow, inspection)
        expected = uow.envelope.expected_version
        if expected is None:
            raise PreconditionRequired("Send If-Match with the current inspection version")
        if expected != inspection.version:
            raise VersionConflict(
                "The inspection changed since it was read",
                extensions={"current_version": inspection.version},
            )
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "assignment_version",
            "checklist_version",
            "observations",
            "summary",
            "captured_at",
            "local_revision",
            "client_operation_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, inspection.application, violations)
        _assignment_version(data, assignment, violations)
        _checklist_version_ok(data, inspection, violations)
        items = checklist_items(inspection.checklist_artifact.payload)
        observations, more = validate_observations(
            items, data.get("observations", []), complete=False
        )
        violations.extend(more)
        summary = data.get("summary", "")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 4000):
            violations.append(Violation("/summary", "length", "at most 4000 characters"))
        captured_at = _instant(data, "captured_at", violations, required=False)
        local_revision = data.get("local_revision")
        if local_revision is not None and (
            not isinstance(local_revision, int) or local_revision <= 0
        ):
            violations.append(Violation("/local_revision", "invalid", "positive integer"))
        if violations:
            raise ValidationFailed(violations=violations)
        if inspection.status not in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS):
            raise InvalidTransition("Drafts belong to an open attempt")
        _, evidence_violations = _evidence_violations(inspection, observations)
        if evidence_violations:
            raise ValidationFailed(violations=evidence_violations)
        draft, created = InspectionDraft.objects.select_for_update().get_or_create(
            inspection=inspection,
            officer=uow.actor,
            defaults={
                "base_inspection_version": inspection.version,
                "assignment_version": assignment.version,
                "payload": {},
                "saved_at": uow.now,
            },
        )
        draft.base_inspection_version = inspection.version
        draft.assignment_version = assignment.version
        draft.payload = {
            "observations": observations,
            "summary": summary or "",
            "captured_at": captured_at.isoformat() if captured_at else None,
        }
        draft.local_revision = local_revision
        draft.saved_at = uow.now
        draft.save()
        return CommandOutcome(
            status=200,
            body={**draft_body(draft), "inspection_version": inspection.version},
            aggregate=draft,
            created=created,
            audits=[
                AuditEntry(
                    "inspection",
                    inspection.pk,
                    "inspection.report_draft_saved",
                    {"observations": len(observations), "local_revision": local_revision},
                )
            ],
        )


class SubmitReport(CommandHandler[Inspection]):
    """API-047 -> TR-06."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff perform inspections")

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        fulfilled = inspection.current_assignment
        if (
            inspection.status == InspectionStatus.COMPLETED
            and fulfilled is not None
            and fulfilled.officer_id == uow.actor.pk
        ):
            # The submitter of the accepted report learns that the attempt is closed; anyone
            # else still learns nothing.
            raise InvalidTransition("This attempt already has an accepted report")
        _assigned_officer_only(uow, inspection)
        # TR-06 moves the case, so the case row is locked too (inspection first, then its
        # application: no other command locks an inspection after its application).
        locked = (
            Application.objects.select_for_update(of=("self",))
            .select_related("owner_queue__jurisdiction", "premises", "current_stage_instance")
            .get(pk=inspection.application_id)
        )
        inspection.application = locked
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        assignment = _assigned_officer_only(uow, target)
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "assignment_version",
            "checklist_version",
            "observations",
            "summary",
            "captured_at",
            "capture_unavailable_reason",
            "declaration_accepted",
            "source_operation_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        application = target.application
        _application_version(data, application, violations)
        _assignment_version(data, assignment, violations)
        _checklist_version_ok(data, target, violations)
        items = checklist_items(target.checklist_artifact.payload)
        observations, more = validate_observations(
            items, data.get("observations", []), complete=True
        )
        violations.extend(more)
        summary = data.get("summary")
        if not isinstance(summary, str) or not (10 <= len(summary.strip()) <= 4000):
            violations.append(Violation("/summary", "length", "10 to 4000 characters"))
            summary = ""
        captured_at = _instant(data, "captured_at", violations, required=False)
        capture_reason = data.get("capture_unavailable_reason")
        if captured_at is None and not (isinstance(capture_reason, str) and capture_reason.strip()):
            violations.append(
                Violation(
                    "/captured_at",
                    "required",
                    "captured_at or an explicit capture_unavailable_reason is required",
                )
            )
        if data.get("declaration_accepted") is not True:
            violations.append(
                Violation(
                    "/declaration_accepted", "required", "the officer declaration must be accepted"
                )
            )
        source_operation = data.get("source_operation_id")
        source_operation_id: UUID | None = None
        if source_operation is not None:
            try:
                source_operation_id = UUID(str(source_operation))
            except ValueError:
                violations.append(Violation("/source_operation_id", "invalid", "must be a UUID"))
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status != InspectionStatus.IN_PROGRESS:
            raise InvalidTransition("Check in at the site before submitting the report")
        found, evidence_violations = _evidence_violations(target, observations)
        if evidence_violations:
            raise ValidationFailed(violations=evidence_violations)
        transition = transition_for("accept-report", application.status_enum)
        if transition is None:
            raise InvalidTransition("The case is not waiting for an inspection report")
        from agni.cases.application.holds import ensure_not_on_hold

        ensure_not_on_hold(application, scope="transition")

        evaluation = evaluate(items, observations)
        digest = canonical_sha256(
            {
                "inspection_id": str(target.pk),
                "assignment_id": str(assignment.pk),
                "checklist": target.checklist_artifact.reference,
                "observations": observations,
                "summary": summary.strip(),
                "evidence": sorted(
                    (doc, found[doc].sha256)
                    for o in observations
                    for doc in o["document_version_ids"]
                ),
                "captured_at": captured_at.isoformat() if captured_at else None,
            }
        )
        revision = (InspectionReport.objects.filter(inspection=target).count()) + 1
        report = InspectionReport.objects.create(
            inspection=target,
            revision_number=revision,
            assignment=assignment,
            checklist_artifact=target.checklist_artifact,
            submitted_by=uow.actor,
            captured_at=captured_at,
            capture_unavailable_reason=(capture_reason or "")[:200] if captured_at is None else "",
            accepted_at=uow.now,
            observations=observations,
            summary=summary.strip(),
            evaluation=evaluation.as_dict(),
            sha256=digest,
            source_operation_id=source_operation_id,
        )
        ReportEvidence.objects.bulk_create(
            [
                ReportEvidence(
                    report=report,
                    item_code=o["item_code"],
                    document_version=found[doc],
                    capture_metadata={
                        "sha256": found[doc].sha256,
                        "object_key": found[doc].object_key,
                        "captured_at": o.get("captured_at"),
                    },
                )
                for o in observations
                for doc in o["document_version_ids"]
            ]
        )
        # Itemised findings (FR-14 -> FR-17) become OPEN finding rows in the same transaction;
        # an unresolved finding for the same item on this case is retained, not duplicated.
        from agni.notices.application.findings import materialise_findings

        materialise_findings(
            application, report, [dict(f) for f in evaluation.as_dict()["findings"]]
        )
        # Attempt completes; assignment fulfilled; draft is superseded by the accepted report.
        assignment.state = AssignmentState.FULFILLED
        assignment.ends_at = uow.now
        assignment.version += 1
        assignment.save(update_fields=["state", "ends_at", "version", "updated_at"])
        target.status = InspectionStatus.COMPLETED
        target.finished_at = uow.now
        target.current_report = report
        target.save(update_fields=["status", "finished_at", "current_report", "updated_at"])
        # The server draft has served its purpose; the immutable report is the record.
        InspectionDraft.objects.filter(inspection=target).delete()

        # TR-06: INSPECTION_PENDING -> REVIEW_PENDING.
        _, target_state, event_type = transition
        new_version = application.version + 1
        application.status = target_state.value
        accepted_event = record_event(
            uow,
            application,
            event_type,
            {
                "inspection_id": str(target.pk),
                "attempt_number": target.attempt_number,
                "report_revision": revision,
                "eligible_for_review": evaluation.eligible_for_review,
                "blocker_count": len(evaluation.blockers),
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        evaluated_event = record_event(
            uow,
            application,
            "inspection.report_evaluated.v1",
            {
                "report_id": str(report.pk),
                "blockers": [b.code + ":" + b.item_code for b in evaluation.blockers],
                "findings": len(evaluation.findings),
                "na_requiring_review": list(evaluation.na_requiring_review),
            },
            audience=EventAudience.INTERNAL,
            ordinal=1,
            version=new_version,
        )
        stage = enter_stage(
            application, target_state.value, accepted_event, uow.now, application.policy_version_id
        )
        application.version = new_version
        application.save(
            update_fields=["status", "current_stage_instance", "version", "updated_at"]
        )
        Obligation.objects.filter(
            application=application,
            kind=ObligationKind.INSPECTION_TASK,
            state=ObligationState.ACTIVE,
        ).update(state=ObligationState.SATISFIED, satisfied_event=accepted_event)
        pinned_id = application.policy_version_id
        policy = PolicyVersion.objects.filter(pk=pinned_id).first() if pinned_id else None
        if policy is not None:
            budget = int(
                policy.payload.get("internal_targets", {}).get("review_working_minutes", 0)
            )
            calendar_artifact = (
                PolicyArtifact.objects.filter(
                    kind="CALENDAR", key=str(policy.payload.get("calendar_key", ""))
                )
                .order_by("-number")
                .first()
            )
            if budget > 0 and calendar_artifact is not None:
                calendar = WorkingCalendar.from_artifact(calendar_artifact.payload)
                Obligation.objects.create(
                    application=application,
                    application_stage_instance=stage,
                    kind=ObligationKind.REVIEW_TASK,
                    owner_queue=application.owner_queue,
                    policy_version=policy,
                    calendar_artifact=calendar_artifact,
                    time_basis=TimeBasis.WORKING,
                    start_event=accepted_event,
                    started_at=uow.now,
                    budget_minutes=budget,
                    due_at=due_instant(
                        basis="WORKING",
                        started_at=uow.now,
                        budget_minutes=budget,
                        calendar=calendar,
                    ),
                )
        target.refresh_from_db()
        target.application = application
        receipt = {
            **inspection_body(target),
            "report": report_body(report),
            "receipt": {
                "report_id": str(report.pk),
                "revision_number": revision,
                "sha256": digest,
                "accepted_at": uow.now.isoformat(),
                "inspection_version": target.version + 1,
                "application_version": new_version,
                "application_status": application.status,
            },
        }
        return CommandOutcome(
            status=201,
            body=receipt,
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.report_accepted",
                    {
                        "report_id": str(report.pk),
                        "revision": revision,
                        "sha256": digest,
                        "eligible_for_review": evaluation.eligible_for_review,
                        "blockers": [b.code for b in evaluation.blockers],
                    },
                ),
                AuditEntry(
                    "application",
                    application.pk,
                    "application.report_accepted",
                    {"inspection_id": str(target.pk), "report_id": str(report.pk)},
                ),
            ],
            intents=[_intent(accepted_event, uow), _intent(evaluated_event, uow)],
        )
