"""Notice, response, review and correction-cycle commands (FR-15, FR-16, FR-17).

Transitions: TR-03 request-information and TR-07 issue-deficiencies (`PublishNotice`),
TR-04 accept-information (`AcceptInformation`), TR-08 complete-corrections
(`CompleteCorrections`), TR-09 require-reinspection (`RequireReinspection`). `SubmitResponse`,
`ReviewItem` and `VerifyFinding` mutate their own resources only (workflow s.4): a response never
closes a finding and a returned item keeps its earlier replies."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from agni.cases.application.access import can_respond_to_notices
from agni.cases.application.submission import enter_stage, record_event
from agni.cases.domain.states import transition_for
from agni.cases.models import Application, CaseEvent, EventAudience, StageInstance
from agni.documents.models import DocumentVersion, ScanState
from agni.identity.authz import load_snapshot, require_capability, require_role
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import PrincipalKind
from agni.inspections.application.commands import (
    _application_version,
    _case_event,
    _intent,
    _new_attempt,
    _reason,
    inspection_body,
)
from agni.inspections.models import Inspection, InspectionPurpose, InspectionStatus
from agni.obligations.domain.clock import WorkingCalendar, due_instant
from agni.obligations.models import Obligation, ObligationKind, ObligationState, TimeBasis
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    MandatoryFindingsOpen,
    NoticeNotOpen,
    ResourceNotFound,
    ResponseNotVerified,
    SeparationOfDuties,
    ValidationFailed,
    Violation,
)
from agni.policies.models import PolicyArtifact, PolicyVersion

from ..domain.rules import (
    open_mandatory_findings,
    pending_required_items,
    reinspection_outstanding,
    validate_items,
)
from ..models import (
    Finding,
    FindingReview,
    FindingState,
    ItemReviewOutcome,
    ItemState,
    Notice,
    NoticeItem,
    NoticeItemReview,
    NoticeState,
    NoticeType,
    ResponseDocument,
    ResponseRevision,
    ReviewOutcome,
)
from .projections import finding_body, item_body, notice_body

# ---- shared helpers -------------------------------------------------------------------------


def _lock_application(application_id: UUID) -> Application | None:
    return (
        Application.objects.select_for_update(of=("self",))
        .select_related(
            "owner_queue__jurisdiction",
            "premises",
            "service",
            "current_stage_instance",
            "applicant",
        )
        .filter(pk=application_id)
        .first()
    )


def _supervisor_here(uow: UnitOfWork, application: Application) -> None:
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
    ):
        raise ResourceNotFound("Application not found")


def _publisher_here(uow: UnitOfWork, application: Application) -> None:
    """Publish notice / verify finding = supervisor in the case jurisdiction plus the
    `notice.publish` capability (security s.5 'J plus capability')."""
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
    ):
        raise ResourceNotFound("Application not found")
    require_capability(
        snapshot,
        Capability.NOTICE_PUBLISH,
        jurisdiction_id=application.owner_queue.jurisdiction_id,
    )


def _pinned_policy(application: Application) -> PolicyVersion:
    policy = (
        PolicyVersion.objects.filter(pk=application.policy_version_id).first()
        if application.policy_version_id
        else None
    )
    if policy is None:
        raise InvalidTransition("The case has no pinned policy")
    return policy


def _calendar(policy: PolicyVersion) -> tuple[PolicyArtifact | None, WorkingCalendar | None]:
    artifact = (
        PolicyArtifact.objects.filter(
            kind="CALENDAR", key=str(policy.payload.get("calendar_key", ""))
        )
        .order_by("-number")
        .first()
    )
    return artifact, (WorkingCalendar.from_artifact(artifact.payload) if artifact else None)


def _satisfy(application: Application, kind: str, event: CaseEvent) -> None:
    Obligation.objects.filter(
        application=application, kind=kind, state=ObligationState.ACTIVE
    ).update(state=ObligationState.SATISFIED, satisfied_event=event)


def _open_obligation(
    application: Application,
    stage: StageInstance,
    kind: str,
    *,
    policy: PolicyVersion,
    basis: str,
    budget: int,
    event: CaseEvent,
    now: datetime,
    responsible: Any = None,
) -> Obligation | None:
    if budget <= 0:
        return None
    artifact, calendar = _calendar(policy)
    if basis == TimeBasis.WORKING and calendar is None:
        return None
    generation = Obligation.objects.filter(application_stage_instance=stage, kind=kind).count() + 1
    return Obligation.objects.create(
        application=application,
        application_stage_instance=stage,
        kind=kind,
        owner_queue=application.owner_queue,
        responsible_principal=responsible,
        policy_version=policy,
        calendar_artifact=artifact,
        time_basis=basis,
        start_event=event,
        started_at=now,
        budget_minutes=budget,
        generation=generation,
        due_at=due_instant(basis=basis, started_at=now, budget_minutes=budget, calendar=calendar),
    )


def _task_budget(policy: PolicyVersion, key: str) -> int:
    return int(policy.payload.get("internal_targets", {}).get(key, 0))


def _clean_case_documents(application: Application, ids: list[str]) -> dict[str, DocumentVersion]:
    return {
        str(d.pk): d
        for d in DocumentVersion.objects.filter(
            pk__in=[UUID(x) for x in ids], application=application, scan_state=ScanState.CLEAN
        )
    }


def _uuid_list(raw: Any, pointer: str, violations: list[Violation]) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(Violation(pointer, "invalid", "must be a list of UUIDs"))
        return []
    out: list[str] = []
    for j, value in enumerate(raw):
        try:
            out.append(str(UUID(str(value))))
        except ValueError:
            violations.append(Violation(f"{pointer}/{j}", "invalid", "must be a UUID"))
    if len(set(out)) != len(out):
        violations.append(Violation(pointer, "duplicate", "ids must be unique"))
    return out


def _transition(uow: UnitOfWork, application: Application, command: str) -> tuple[str, str]:
    transition = transition_for(command, application.status_enum)
    if transition is None:
        raise InvalidTransition(f"'{command}' is not permitted from {application.status}")
    _, target_state, event_type = transition
    return target_state.value, event_type


# ---- TR-03 / TR-07: publish a notice (API-054) ---------------------------------------------


class PublishNotice(CommandHandler[Application]):
    """One published, immutable, itemised notice per command. INFORMATION rounds concern
    completeness (TR-03 from SCRUTINY); DEFICIENCY rounds itemise open findings of the accepted
    report (TR-07 from REVIEW_PENDING). A superseding round is published while the case already
    waits for the applicant and keeps the original notice and its clock disposition."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff publish notices")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = _lock_application(uow.envelope.target_id)
        if application is None or application.status == "DRAFT":
            raise ResourceNotFound("Application not found")
        _publisher_here(uow, application)
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "type",
            "public_reason",
            "internal_note",
            "items",
            "proposed_response_budget_minutes",
            "supersedes_notice_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        notice_type = data.get("type")
        if notice_type not in NoticeType.values:
            violations.append(Violation("/type", "invalid", "INFORMATION or DEFICIENCY"))
            notice_type = NoticeType.INFORMATION
        public_reason = _reason(data, violations, key="public_reason")
        internal_note = data.get("internal_note") or ""
        if not isinstance(internal_note, str) or len(internal_note) > 4000:
            violations.append(Violation("/internal_note", "length", "at most 4000 characters"))
            internal_note = ""
        deficiency = notice_type == NoticeType.DEFICIENCY
        open_findings = {
            str(f.pk): f
            for f in Finding.objects.filter(application=target).exclude(
                state=FindingState.VERIFIED_CLOSED
            )
        }
        items, more = validate_items(
            data.get("items"), deficiency=deficiency, known_findings=open_findings
        )
        violations.extend(more)
        policy = _pinned_policy(target)
        policy_budget = int(policy.payload.get("applicant_response_calendar_minutes", 0))
        budget_raw = data.get("proposed_response_budget_minutes")
        budget = policy_budget
        if budget_raw is not None:
            if (
                not isinstance(budget_raw, int)
                or isinstance(budget_raw, bool)
                or budget_raw <= 0
                or budget_raw > policy_budget
            ):
                violations.append(
                    Violation(
                        "/proposed_response_budget_minutes",
                        "range",
                        f"positive and at most the policy budget ({policy_budget} minutes)",
                    )
                )
            else:
                budget = budget_raw
        supersedes: Notice | None = None
        raw_supersedes = data.get("supersedes_notice_id")
        if raw_supersedes is not None:
            try:
                supersedes = (
                    Notice.objects.select_for_update(of=("self",))
                    .filter(pk=UUID(str(raw_supersedes)), application=target, type=notice_type)
                    .first()
                )
            except ValueError:
                supersedes = None
            if supersedes is None or supersedes.state != NoticeState.PUBLISHED:
                violations.append(
                    Violation(
                        "/supersedes_notice_id",
                        "invalid",
                        "must be a PUBLISHED notice of the same type on this case",
                    )
                )
        if violations:
            raise ValidationFailed(violations=violations)
        if budget <= 0:
            raise InvalidTransition("The pinned policy defines no applicant response budget")

        command = (
            "request-information"
            if notice_type == NoticeType.INFORMATION
            else ("issue-deficiencies")
        )
        waiting_state = (
            "INFO_REQUIRED" if notice_type == NoticeType.INFORMATION else ("COMPLIANCE_PENDING")
        )
        new_version = target.version + 1
        stage: StageInstance
        if supersedes is not None:
            # Correction round: the case already waits for the applicant; no transition.
            if target.status != waiting_state:
                raise InvalidTransition("A superseding notice needs the case to be waiting")
            event_type = "notice.published.v1"
            current_stage = target.current_stage_instance
            if current_stage is None:
                raise InvalidTransition("The case has no open stage")
            stage = current_stage
        else:
            target_state, event_type = _transition(uow, target, command)
            target.status = target_state
        round_number = Notice.objects.filter(application=target, type=notice_type).count() + 1
        event = record_event(
            uow,
            target,
            event_type,
            {
                "notice_type": notice_type,
                "round_number": round_number,
                "item_codes": [i["code"] for i in items],
                "supersedes_notice_id": str(supersedes.pk) if supersedes else None,
                "response_budget_minutes": budget,
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        if supersedes is None:
            stage = enter_stage(target, target.status, event, uow.now, target.policy_version_id)
            _satisfy(
                target,
                ObligationKind.SCRUTINY_TASK if not deficiency else ObligationKind.REVIEW_TASK,
                event,
            )
        else:
            supersedes.state = NoticeState.SUPERSEDED
            supersedes.closed_at = uow.now
            supersedes.version += 1
            supersedes.save(update_fields=["state", "closed_at", "version", "updated_at"])
            if supersedes.due_obligation_id:
                Obligation.objects.filter(
                    pk=supersedes.due_obligation_id, state=ObligationState.ACTIVE
                ).update(state=ObligationState.CANCELLED, satisfied_event=event)
        obligation = _open_obligation(
            target,
            stage,
            ObligationKind.APPLICANT_RESPONSE,
            policy=policy,
            basis=TimeBasis.CALENDAR,
            budget=budget,
            event=event,
            now=uow.now,
            responsible=target.applicant,
        )
        notice = Notice.objects.create(
            application=target,
            round_number=round_number,
            type=notice_type,
            state=NoticeState.PUBLISHED,
            policy_version=policy,
            published_by=uow.actor,
            published_at=uow.now,
            due_obligation=obligation,
            supersedes=supersedes,
            public_reason=public_reason,
            internal_note=internal_note.strip(),
            response_budget_minutes=budget,
        )
        NoticeItem.objects.bulk_create(
            [
                NoticeItem(
                    notice=notice,
                    code=i["code"],
                    finding=open_findings[i["finding_id"]] if i["finding_id"] else None,
                    title=i["title"],
                    description=i["description"],
                    required=i["required"],
                    acceptable_evidence_types=i["acceptable_evidence_types"],
                    public_guidance=i["public_guidance"],
                )
                for i in items
            ]
        )
        target.version = new_version
        target.save(update_fields=["status", "current_stage_instance", "version", "updated_at"])
        body = {
            **notice_body(notice, staff=True),
            "application_status": target.status,
            "application_version": new_version,
        }
        return CommandOutcome(
            status=201,
            body=body,
            aggregate=target,
            created=True,  # version already advanced explicitly (events reference it)
            audits=[
                AuditEntry(
                    "notice",
                    notice.pk,
                    "notice.published",
                    {
                        "application_id": str(target.pk),
                        "type": notice_type,
                        "round_number": round_number,
                        "items": len(items),
                        "supersedes": str(supersedes.pk) if supersedes else None,
                    },
                ),
                AuditEntry(
                    "application",
                    target.pk,
                    "application.notice_published",
                    {"notice_id": str(notice.pk), "status": target.status},
                ),
            ],
            intents=[_intent(event, uow)],
        )


# ---- FR-16: applicant response (API-056) ---------------------------------------------------


class SubmitResponse(CommandHandler[Notice]):
    """A new response revision per item. Evidence must be CLEAN files of this case; the item
    moves to RESPONSE_RECEIVED (never to ACCEPTED); a linked finding records the response."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.APPLICANT:
            raise Forbidden("Only the applicant side responds to notices")

    def lock_target(self, uow: UnitOfWork) -> Notice | None:
        notice = (
            Notice.objects.select_for_update(of=("self",))
            .select_related("application__owner_queue", "due_obligation")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if notice is None or not can_respond_to_notices(uow.actor, notice.application, uow.now):
            raise ResourceNotFound("Notice not found")
        return notice

    def apply(self, uow: UnitOfWork, target: Notice | None) -> CommandOutcome[Notice]:
        if target is None:
            raise ResourceNotFound("Notice not found")
        application = target.application
        data = dict(uow.envelope.payload)
        allowed = {"application_version", "responses", "declaration_accepted"}
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, application, violations)
        if target.state != NoticeState.PUBLISHED:
            # A closed round is a state fact, reported before any field-level detail.
            raise NoticeNotOpen(
                "This notice no longer accepts responses",
                extensions={"notice_state": target.state},
            )
        if data.get("declaration_accepted") is not True:
            violations.append(
                Violation("/declaration_accepted", "required", "the declaration must be accepted")
            )
        raw = data.get("responses")
        if not isinstance(raw, list) or not raw:
            violations.append(Violation("/responses", "required", "at least one item response"))
            raw = []
        items = {str(i.pk): i for i in target.items.select_related("finding").all()}
        cleaned: list[tuple[NoticeItem, str, list[str]]] = []
        seen: set[str] = set()
        for index, entry in enumerate(raw):
            pointer = f"/responses/{index}"
            if not isinstance(entry, dict):
                violations.append(Violation(pointer, "invalid", "must be an object"))
                continue
            item_id = str(entry.get("notice_item_id", ""))
            item = items.get(item_id)
            if item is None:
                violations.append(
                    Violation(f"{pointer}/notice_item_id", "unknown", "not an item of this notice")
                )
                continue
            if item_id in seen:
                violations.append(
                    Violation(f"{pointer}/notice_item_id", "duplicate", "item repeated")
                )
                continue
            seen.add(item_id)
            explanation = entry.get("explanation")
            if not isinstance(explanation, str) or not (10 <= len(explanation.strip()) <= 4000):
                violations.append(
                    Violation(f"{pointer}/explanation", "length", "10 to 4000 characters")
                )
                explanation = ""
            docs = _uuid_list(
                entry.get("document_version_ids", []), f"{pointer}/document_version_ids", violations
            )
            if item.state == ItemState.ACCEPTED:
                violations.append(
                    Violation(
                        f"{pointer}/notice_item_id", "closed", "this item is already accepted"
                    )
                )
            elif item.state == ItemState.UNDER_REVIEW:
                violations.append(
                    Violation(
                        f"{pointer}/notice_item_id", "under_review", "this item is being reviewed"
                    )
                )
            cleaned.append((item, explanation.strip(), docs))
        if violations:
            raise ValidationFailed(violations=violations)
        wanted = [doc for _, _, docs in cleaned for doc in docs]
        found = _clean_case_documents(application, wanted) if wanted else {}
        for index, (_, _, docs) in enumerate(cleaned):
            for j, doc in enumerate(docs):
                if doc not in found:
                    violations.append(
                        Violation(
                            f"/responses/{index}/document_version_ids/{j}",
                            "not_clean_case_evidence",
                            "must be a CLEAN file of this case",
                        )
                    )
        if violations:
            raise ValidationFailed(violations=violations)

        receipts: list[dict[str, Any]] = []
        for item, explanation, docs in cleaned:
            number = item.responses.count() + 1
            digest = canonical_sha256(
                {
                    "notice_item_id": str(item.pk),
                    "number": number,
                    "explanation": explanation,
                    "documents": sorted((doc, found[doc].sha256) for doc in docs),
                }
            )
            revision = ResponseRevision.objects.create(
                notice_item=item,
                number=number,
                submitted_by=uow.actor,
                explanation=explanation,
                declaration_accepted=True,
                accepted_at=uow.now,
                sha256=digest,
            )
            ResponseDocument.objects.bulk_create(
                [ResponseDocument(response=revision, document_version=found[doc]) for doc in docs]
            )
            item.state = ItemState.RESPONSE_RECEIVED
            item.current_response = revision
            item.version += 1
            item.save(update_fields=["state", "current_response", "version", "updated_at"])
            finding = item.finding
            if finding is not None:
                finding.state = FindingState.RESPONSE_RECEIVED
                finding.current_response = revision
                finding.version += 1
                finding.save(update_fields=["state", "current_response", "version", "updated_at"])
            receipts.append(
                {
                    "notice_item_id": str(item.pk),
                    "code": item.code,
                    "response_revision_id": str(revision.pk),
                    "number": number,
                    "sha256": digest,
                    "item_state": item.state,
                }
            )
        event = _case_event(
            uow,
            application,
            "notice.response_received.v1",
            {
                "notice_id": str(target.pk),
                "round_number": target.round_number,
                "item_codes": [r["code"] for r in receipts],
            },
            EventAudience.PUBLIC_CASE,
        )
        body = {
            **notice_body(target, staff=False),
            "responses": receipts,
            "application_version": application.version,
        }
        return CommandOutcome(
            status=201,
            body=body,
            aggregate=target,
            audits=[
                AuditEntry(
                    "notice",
                    target.pk,
                    "notice.response_received",
                    {"items": [r["code"] for r in receipts], "revisions": len(receipts)},
                )
            ],
            intents=[_intent(event, uow)],
        )


# ---- FR-17: item review (API-058) -----------------------------------------------------------


class ReviewItem(CommandHandler[NoticeItem]):
    """Accept or return one item against its current response. A deficiency item is accepted only
    once its finding is VERIFIED_CLOSED (API-060); a return keeps prior replies and reopens the
    finding with a public reason."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff review responses")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> NoticeItem | None:
        item = (
            NoticeItem.objects.select_for_update(of=("self",))
            .select_related(
                "notice__application__owner_queue__jurisdiction", "finding", "current_response"
            )
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if item is None:
            raise ResourceNotFound("Notice item not found")
        _supervisor_here(uow, item.notice.application)
        return item

    def apply(self, uow: UnitOfWork, target: NoticeItem | None) -> CommandOutcome[NoticeItem]:
        if target is None:
            raise ResourceNotFound("Notice item not found")
        notice = target.notice
        application = notice.application
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "response_revision_id",
            "outcome",
            "reason",
            "evidence_refs",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, application, violations)
        outcome = str(data.get("outcome") or "")
        if outcome not in ItemReviewOutcome.values:
            violations.append(Violation("/outcome", "invalid", "ACCEPTED or RETURNED"))
        reason = _reason(data, violations)
        revision_raw = data.get("response_revision_id")
        current = target.current_response
        if current is None or str(revision_raw) != str(current.pk):
            violations.append(
                Violation(
                    "/response_revision_id",
                    "stale",
                    "must be the item's current response revision",
                )
            )
        evidence_refs = _uuid_list(data.get("evidence_refs"), "/evidence_refs", violations)
        if violations:
            raise ValidationFailed(violations=violations)
        if notice.state != NoticeState.PUBLISHED:
            raise NoticeNotOpen("This notice is closed", extensions={"notice_state": notice.state})
        if target.state not in (ItemState.RESPONSE_RECEIVED, ItemState.UNDER_REVIEW):
            raise InvalidTransition("Only a received response can be reviewed")
        if current is not None and current.submitted_by_id == uow.actor.pk:
            raise SeparationOfDuties("The reviewer cannot be the responder")
        finding = target.finding
        if outcome == ItemReviewOutcome.ACCEPTED:
            if finding is not None and finding.state != FindingState.VERIFIED_CLOSED:
                raise ResponseNotVerified(
                    "Verify the linked finding before accepting this item",
                    extensions={"finding_id": str(finding.pk), "finding_state": finding.state},
                )
            target.state = ItemState.ACCEPTED
            target.verified_by = uow.actor
            target.verified_at = uow.now
            target.reviewer_feedback = ""
        else:
            target.state = ItemState.RETURNED
            target.reviewer_feedback = reason
            if finding is not None and finding.state != FindingState.VERIFIED_CLOSED:
                finding.state = FindingState.OPEN
                finding.last_review_reason = reason
                finding.version += 1
                finding.save(update_fields=["state", "last_review_reason", "version", "updated_at"])
        target.save(
            update_fields=["state", "verified_by", "verified_at", "reviewer_feedback", "updated_at"]
        )
        NoticeItemReview.objects.create(
            notice_item=target,
            response_revision=current,
            reviewer=uow.actor,
            outcome=outcome,
            reason=reason,
            evidence_refs=evidence_refs,
            accepted_at=uow.now,
        )
        event = _case_event(
            uow,
            application,
            "notice.item_reviewed.v1",
            {
                "notice_id": str(notice.pk),
                "item_code": target.code,
                "outcome": outcome,
                "public_reason": reason,
            },
            EventAudience.PUBLIC_CASE,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body={**item_body(target, staff=True), "application_version": application.version},
            aggregate=target,
            audits=[
                AuditEntry(
                    "notice_item",
                    target.pk,
                    "notice.item_reviewed",
                    {
                        "outcome": outcome,
                        "response_revision_id": str(current.pk) if current else None,
                    },
                )
            ],
            intents=[_intent(event, uow)],
        )


# ---- FR-17: finding verification (API-060) --------------------------------------------------


class VerifyFinding(CommandHandler[Finding]):
    """Only an authorised reviewer closes a finding, and only against evidence they attribute:
    a PASS observation of an accepted (re)inspection report or reviewer-cited CLEAN documents.
    An applicant upload or checkbox alone never closes a MANDATORY finding."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff verify findings")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Finding | None:
        finding = (
            Finding.objects.select_for_update(of=("self",))
            .select_related(
                "application__owner_queue__jurisdiction",
                "originating_report",
                "current_response",
            )
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if finding is None:
            raise ResourceNotFound("Finding not found")
        _publisher_here(uow, finding.application)
        return finding

    def apply(self, uow: UnitOfWork, target: Finding | None) -> CommandOutcome[Finding]:
        if target is None:
            raise ResourceNotFound("Finding not found")
        application = target.application
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "response_revision_id",
            "outcome",
            "reason",
            "evidence_document_ids",
            "report_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, application, violations)
        outcome = str(data.get("outcome") or "")
        if outcome not in ReviewOutcome.values:
            violations.append(
                Violation(
                    "/outcome", "invalid", "VERIFIED_CLOSED, RETURNED or REINSPECTION_REQUIRED"
                )
            )
        reason = _reason(data, violations)
        revision_raw = data.get("response_revision_id")
        revision: ResponseRevision | None = None
        if revision_raw is not None:
            if target.current_response is None or str(revision_raw) != str(
                target.current_response_id
            ):
                violations.append(
                    Violation(
                        "/response_revision_id",
                        "stale",
                        "must be the finding's current response revision or null",
                    )
                )
            else:
                revision = target.current_response
        doc_ids = _uuid_list(
            data.get("evidence_document_ids"), "/evidence_document_ids", violations
        )
        report_raw = data.get("report_id")
        report: Any = None
        report_pass = False
        if report_raw is not None:
            from agni.inspections.models import InspectionReport

            try:
                report = (
                    InspectionReport.objects.filter(
                        pk=UUID(str(report_raw)), inspection__application=application
                    )
                    .select_related("inspection")
                    .first()
                )
            except ValueError:
                report = None
            if report is None:
                violations.append(
                    Violation("/report_id", "unknown", "must be an accepted report of this case")
                )
            else:
                observation = next(
                    (
                        o
                        for o in report.observations
                        if o.get("item_code") == target.checklist_item_code
                    ),
                    None,
                )
                if observation is None:
                    violations.append(
                        Violation(
                            "/report_id",
                            "no_observation",
                            "the report has no observation for this item",
                        )
                    )
                else:
                    report_pass = observation.get("result") == "PASS"
        if violations:
            raise ValidationFailed(violations=violations)
        if target.state == FindingState.VERIFIED_CLOSED:
            raise InvalidTransition("This finding is already verified closed")
        if target.originating_report.submitted_by_id == uow.actor.pk:
            raise SeparationOfDuties("The inspecting officer cannot verify their own finding")
        found = _clean_case_documents(application, doc_ids) if doc_ids else {}
        missing = [d for d in doc_ids if d not in found]
        if missing:
            raise ValidationFailed(
                violations=[
                    Violation(
                        f"/evidence_document_ids/{doc_ids.index(d)}",
                        "not_clean_case_evidence",
                        "must be a CLEAN file of this case",
                    )
                    for d in missing
                ]
            )
        if outcome == ReviewOutcome.VERIFIED_CLOSED:
            if report is not None and not report_pass:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/report_id",
                            "not_passed",
                            "the cited report does not record PASS for this item",
                        )
                    ]
                )
            reviewer_basis = bool(found) or report_pass
            if target.severity == "MANDATORY" and not reviewer_basis:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/evidence_document_ids",
                            "verification_basis_required",
                            "a mandatory finding closes only against reviewer-cited evidence "
                            "or a passing reinspection report, never a response alone",
                        )
                    ]
                )
            if not reviewer_basis and revision is None:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/response_revision_id",
                            "verification_basis_required",
                            "cite the response revision, evidence documents or a report",
                        )
                    ]
                )
            target.state = FindingState.VERIFIED_CLOSED
            target.closed_by = uow.actor
            target.closed_at = uow.now
            target.reinspection_required = False
            target.closure_evidence = {
                "response_revision_id": str(revision.pk) if revision else None,
                "report_id": str(report.pk) if report else None,
                "evidence_documents": [
                    {"document_version_id": d, "sha256": found[d].sha256} for d in doc_ids
                ],
                "reason": reason,
            }
            for item in NoticeItem.objects.filter(
                finding=target, notice__state=NoticeState.PUBLISHED
            ).exclude(state=ItemState.ACCEPTED):
                item.state = ItemState.ACCEPTED
                item.verified_by = uow.actor
                item.verified_at = uow.now
                item.reviewer_feedback = ""
                item.version += 1
                item.save(
                    update_fields=[
                        "state",
                        "verified_by",
                        "verified_at",
                        "reviewer_feedback",
                        "version",
                        "updated_at",
                    ]
                )
        elif outcome == ReviewOutcome.RETURNED:
            target.state = FindingState.OPEN
            target.last_review_reason = reason
            for item in NoticeItem.objects.filter(
                finding=target, notice__state=NoticeState.PUBLISHED
            ).exclude(state=ItemState.ACCEPTED):
                item.state = ItemState.RETURNED
                item.reviewer_feedback = reason
                item.version += 1
                item.save(update_fields=["state", "reviewer_feedback", "version", "updated_at"])
        else:
            target.reinspection_required = True
            target.last_review_reason = reason
        target.save(
            update_fields=[
                "state",
                "closed_by",
                "closed_at",
                "closure_evidence",
                "reinspection_required",
                "last_review_reason",
                "updated_at",
            ]
        )
        FindingReview.objects.create(
            finding=target,
            response_revision=revision,
            reviewer=uow.actor,
            outcome=outcome,
            reason=reason,
            evidence_snapshot={
                "report_id": str(report.pk) if report else None,
                "evidence_documents": [
                    {"document_version_id": d, "sha256": found[d].sha256} for d in doc_ids
                ],
            },
            accepted_at=uow.now,
        )
        event = _case_event(
            uow,
            application,
            "finding.reviewed.v1",
            {
                "finding_id": str(target.pk),
                "item_code": target.checklist_item_code,
                "severity": target.severity,
                "outcome": outcome,
                "public_reason": reason,
            },
            EventAudience.PUBLIC_CASE,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body={**finding_body(target, staff=True), "application_version": application.version},
            aggregate=target,
            audits=[
                AuditEntry(
                    "finding",
                    target.pk,
                    "finding.reviewed",
                    {
                        "outcome": outcome,
                        "report_id": str(report.pk) if report else None,
                        "evidence_documents": doc_ids,
                    },
                )
            ],
            intents=[_intent(event, uow)],
        )


# ---- TR-04 accept-information (API-057) -----------------------------------------------------


class AcceptInformation(CommandHandler[Notice]):
    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff accept information rounds")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Notice | None:
        notice = (
            Notice.objects.select_for_update(of=("self",)).filter(pk=uow.envelope.target_id).first()
        )
        if notice is None:
            raise ResourceNotFound("Notice not found")
        application = _lock_application(notice.application_id)
        if application is None:
            raise ResourceNotFound("Notice not found")
        _supervisor_here(uow, application)
        notice.application = application
        return notice

    def apply(self, uow: UnitOfWork, target: Notice | None) -> CommandOutcome[Notice]:
        if target is None:
            raise ResourceNotFound("Notice not found")
        application = target.application
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason", "application_version"})
        ]
        reason = _reason(data, violations)
        if data.get("application_version") is not None:
            _application_version(data, application, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        if target.type != NoticeType.INFORMATION or target.state != NoticeState.PUBLISHED:
            raise NoticeNotOpen("Only the current published information notice can be accepted")
        pending = pending_required_items(list(target.items.all()))
        if pending:
            raise ResponseNotVerified(
                "Every required item must be accepted first",
                extensions={"pending_items": pending},
            )
        target_state, event_type = _transition(uow, application, "accept-information")
        new_version = application.version + 1
        application.status = target_state
        event = record_event(
            uow,
            application,
            event_type,
            {"notice_id": str(target.pk), "round_number": target.round_number},
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        note = record_event(
            uow,
            application,
            "scrutiny.note.v1",
            {"reason": reason},
            audience=EventAudience.INTERNAL,
            ordinal=1,
            version=new_version,
        )
        stage = enter_stage(
            application, target_state, event, uow.now, application.policy_version_id
        )
        application.version = new_version
        application.save(
            update_fields=["status", "current_stage_instance", "version", "updated_at"]
        )
        target.state = NoticeState.SATISFIED
        target.closed_at = uow.now
        target.save(update_fields=["state", "closed_at", "updated_at"])
        _satisfy(application, ObligationKind.APPLICANT_RESPONSE, event)
        policy = _pinned_policy(application)
        _open_obligation(
            application,
            stage,
            ObligationKind.SCRUTINY_TASK,
            policy=policy,
            basis=TimeBasis.WORKING,
            budget=_task_budget(policy, "scrutiny_working_minutes"),
            event=event,
            now=uow.now,
        )
        return CommandOutcome(
            status=200,
            body={
                **notice_body(target, staff=True),
                "application_status": application.status,
                "application_version": new_version,
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    application.pk,
                    "application.information_accepted",
                    {"notice_id": str(target.pk), "reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow), _intent(note, uow)],
        )


# ---- TR-08 complete-corrections (API-061) ---------------------------------------------------


class CompleteCorrections(CommandHandler[Application]):
    """Prototype 'return-review': COMPLIANCE_PENDING -> REVIEW_PENDING only when every MANDATORY
    finding is VERIFIED_CLOSED and no reinspection is outstanding."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff complete correction cycles")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = _lock_application(uow.envelope.target_id)
        if application is None or application.status == "DRAFT":
            raise ResourceNotFound("Application not found")
        _supervisor_here(uow, application)
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason"})
        ]
        reason = _reason(data, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        target_state, event_type = _transition(uow, target, "complete-corrections")
        findings = list(Finding.objects.filter(application=target))
        open_codes = open_mandatory_findings(findings)
        outstanding = reinspection_outstanding(findings)
        if open_codes or outstanding:
            raise MandatoryFindingsOpen(
                "Mandatory findings are not yet verified closed",
                extensions={"open_mandatory": open_codes, "reinspection_outstanding": outstanding},
            )
        if Inspection.objects.filter(
            application=target,
            status__in=[
                InspectionStatus.REQUESTED,
                InspectionStatus.SCHEDULED,
                InspectionStatus.IN_PROGRESS,
            ],
        ).exists():
            raise InvalidTransition("An inspection attempt is still open")
        new_version = target.version + 1
        target.status = target_state
        event = record_event(
            uow,
            target,
            event_type,
            {
                "verified_findings": [
                    f.checklist_item_code for f in findings if f.state == "VERIFIED_CLOSED"
                ]
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        note = record_event(
            uow,
            target,
            "scrutiny.note.v1",
            {"reason": reason},
            audience=EventAudience.INTERNAL,
            ordinal=1,
            version=new_version,
        )
        stage = enter_stage(target, target_state, event, uow.now, target.policy_version_id)
        target.version = new_version
        target.save(update_fields=["status", "current_stage_instance", "version", "updated_at"])
        Notice.objects.filter(
            application=target, type=NoticeType.DEFICIENCY, state=NoticeState.PUBLISHED
        ).update(state=NoticeState.SATISFIED, closed_at=uow.now)
        _satisfy(target, ObligationKind.APPLICANT_RESPONSE, event)
        policy = _pinned_policy(target)
        _open_obligation(
            target,
            stage,
            ObligationKind.REVIEW_TASK,
            policy=policy,
            basis=TimeBasis.WORKING,
            budget=_task_budget(policy, "review_working_minutes"),
            event=event,
            now=uow.now,
        )
        return CommandOutcome(
            status=200,
            body={
                "application_id": str(target.pk),
                "public_reference": target.public_reference,
                "status": target.status,
                "version": new_version,
            },
            aggregate=target,
            created=True,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "application.corrections_completed",
                    {"reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow), _intent(note, uow)],
        )


# ---- TR-09 require-reinspection (API-062) ---------------------------------------------------


class RequireReinspection(CommandHandler[Application]):
    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff require reinspections")
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = _lock_application(uow.envelope.target_id)
        if application is None or application.status == "DRAFT":
            raise ResourceNotFound("Application not found")
        _supervisor_here(uow, application)
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"finding_ids", "reason", "previous_inspection_id"})
        ]
        reason = _reason(data, violations)
        finding_ids = _uuid_list(data.get("finding_ids"), "/finding_ids", violations)
        if not finding_ids:
            violations.append(Violation("/finding_ids", "required", "choose at least one finding"))
        findings = {
            str(f.pk): f
            for f in Finding.objects.filter(
                application=target, pk__in=[UUID(x) for x in finding_ids]
            ).exclude(state=FindingState.VERIFIED_CLOSED)
        }
        for j, fid in enumerate(finding_ids):
            if fid not in findings:
                violations.append(
                    Violation(
                        f"/finding_ids/{j}", "unknown_finding", "not an open finding of this case"
                    )
                )
        previous: Inspection | None = None
        try:
            previous = (
                Inspection.objects.filter(
                    pk=UUID(str(data.get("previous_inspection_id"))), application=target
                )
                .select_related("checklist_artifact")
                .first()
            )
        except ValueError:
            previous = None
        if previous is None or previous.status != InspectionStatus.COMPLETED:
            violations.append(
                Violation(
                    "/previous_inspection_id", "invalid", "must be a completed attempt of this case"
                )
            )
        if violations:
            raise ValidationFailed(violations=violations)
        if previous is None:  # for the type checker; validated above
            raise ResourceNotFound("Inspection not found")
        target_state, event_type = _transition(uow, target, "require-reinspection")
        new_version = target.version + 1
        target.status = target_state
        inspection = _new_attempt(
            uow,
            target,
            purpose=InspectionPurpose.REINSPECTION,
            parent=previous,
            checklist=previous.checklist_artifact,
            reason=reason,
        )
        for finding in findings.values():
            finding.reinspection_required = True
            finding.last_review_reason = reason
            finding.version += 1
            finding.save(
                update_fields=[
                    "reinspection_required",
                    "last_review_reason",
                    "version",
                    "updated_at",
                ]
            )
        event = record_event(
            uow,
            target,
            event_type,
            {
                "inspection_id": str(inspection.pk),
                "attempt_number": inspection.attempt_number,
                "previous_inspection_id": str(previous.pk),
                "finding_item_codes": [f.checklist_item_code for f in findings.values()],
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        stage = enter_stage(target, target_state, event, uow.now, target.policy_version_id)
        target.version = new_version
        target.save(update_fields=["status", "current_stage_instance", "version", "updated_at"])
        policy = _pinned_policy(target)
        _open_obligation(
            target,
            stage,
            ObligationKind.INSPECTION_TASK,
            policy=policy,
            basis=TimeBasis.CALENDAR,
            budget=_task_budget(policy, "inspection_calendar_minutes"),
            event=event,
            now=uow.now,
        )
        inspection.refresh_from_db()
        return CommandOutcome(
            status=201,
            body={**inspection_body(inspection), "application_version": new_version},
            aggregate=target,
            created=True,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "application.reinspection_required",
                    {
                        "inspection_id": str(inspection.pk),
                        "findings": [f.checklist_item_code for f in findings.values()],
                        "reason": reason[:200],
                    },
                )
            ],
            intents=[_intent(event, uow)],
        )
