"""TR-01 submit (FR-06), TR-02 start-scrutiny and routing exception resolution (FR-07).

Submission follows the atomic transition algorithm (workflow s.9): the kernel locks the
principal fence, `lock_target` locks the service activation fence and then the application,
guards are re-evaluated against current facts, and one transaction writes the immutable
submission revision, the pinned policy, the owner queue (or a visible routing exception), the
stage instance, events, obligations, audit, outbox intents and the receipt. Any failure leaves
the draft untouched and returns no receipt."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import PrincipalKind
from agni.obligations.domain.clock import WorkingCalendar, due_instant
from agni.obligations.models import Obligation, ObligationKind, ObligationState, TimeBasis
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import (
    AuditEntry,
    CommandHandler,
    CommandOutcome,
    OutboxIntent,
    UnitOfWork,
)
from agni.platform.errors import (
    EvidenceIncomplete,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    RoutingUnresolved,
    ValidationFailed,
    VersionConflict,
    Violation,
)
from agni.policies.models import PolicyArtifact
from agni.policies.selection import lock_service_fence, select_policy
from agni.routing.models import (
    DutyQueue,
    RoutingEntry,
    RoutingException,
    RoutingExceptionState,
)
from agni.routing.resolution import RoutingUnresolvedError, resolve_route

from ..domain.drafts import (
    DECLARATION_CODES,
    DEMO_DECLARATIONS,
    REQUIREMENT_LABELS,
    validate_draft_fields,
)
from ..domain.states import ApplicationStatus, transition_for
from ..models import (
    Application,
    CaseEvent,
    EventAudience,
    StageInstance,
    SubmissionDocument,
    SubmissionRevision,
)
from .access import can_edit_draft, editable_draft_for_actor

REQUIRED_FIELDS = (
    "display_name",
    "address_line1",
    "locality",
    "ward_key",
    "postal_code",
    "category_key",
    "area_sqm",
    "height_m",
    "floor_count",
)


# ---- shared helpers ---------------------------------------------------------------------------


def record_event(
    uow: UnitOfWork,
    application: Application,
    event_type: str,
    payload: dict[str, Any],
    *,
    audience: str,
    ordinal: int,
    version: int,
) -> CaseEvent:
    return CaseEvent.objects.create(
        application=application,
        aggregate_version=version,
        ordinal=ordinal,
        event_type=event_type,
        actor=uow.actor,
        actor_kind=uow.actor.kind,
        occurred_at=uow.now,
        payload=payload,
        audience=audience,
        request_id=uow.request_id,
        command_receipt_id=uow.command_id,
    )


def enter_stage(
    application: Application,
    state: str,
    event: CaseEvent,
    now: datetime,
    policy_version_id: UUID | None,
) -> StageInstance:
    """Close the open stage instance (if any) and open the next cycle."""
    current = application.current_stage_instance
    if current is not None and current.exited_at is None:
        current.exited_event = event
        current.exited_at = now
        current.save(update_fields=["exited_event", "exited_at"])
    cycle = (
        StageInstance.objects.filter(application=application)
        .order_by("-cycle_number")
        .values_list("cycle_number", flat=True)
        .first()
        or 0
    ) + 1
    stage = StageInstance.objects.create(
        application=application,
        state=state,
        cycle_number=cycle,
        policy_version_id=policy_version_id,
        entered_event=event,
        entered_at=now,
    )
    application.current_stage_instance = stage
    return stage


def event_envelope(event: CaseEvent, uow: UnitOfWork) -> dict[str, Any]:
    """Outbox payload shaped like the event contract (API s.8)."""
    return {
        "event_id": str(event.pk),
        "event_type": event.event_type,
        "schema_version": 1,
        "aggregate_type": "application",
        "aggregate_id": str(event.application_id),
        "aggregate_version": event.aggregate_version,
        "event_ordinal": event.ordinal,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_id": str(uow.actor.pk),
        "command_id": str(uow.command_id),
        "correlation_id": str(uow.request_id),
        "payload": event.payload,
    }


def _public_reference(year: int, sequence: int) -> str:
    return f"AS-{year}-{1000 + sequence}"


def _allocate_public_reference(application: Application, now: datetime) -> None:
    """Sequential demo reference `AS-<year>-<n>`; collisions under concurrency retry inside a
    savepoint so the outer transaction stays valid."""
    year = now.year
    for attempt in range(6):
        count = Application.objects.filter(public_reference__startswith=f"AS-{year}-").count()
        candidate = _public_reference(year, count + 1 + attempt)
        try:
            with transaction.atomic():
                Application.objects.filter(pk=application.pk).update(public_reference=candidate)
            application.public_reference = candidate
            return
        except IntegrityError:
            continue
    application.public_reference = f"AS-{year}-{secrets.token_hex(3).upper()}"
    Application.objects.filter(pk=application.pk).update(
        public_reference=application.public_reference
    )


def _obligation_body(o: Obligation) -> dict[str, Any]:
    return {
        "obligation_id": str(o.pk),
        "kind": o.kind,
        "state": o.state,
        "time_basis": o.time_basis,
        "budget_minutes": o.budget_minutes,
        "started_at": o.started_at.isoformat(),
        "due_at": o.due_at.isoformat() if o.due_at else None,
        "owner_queue": o.owner_queue.queue_key,
    }


def receipt_body(
    application: Application,
    revision: SubmissionRevision,
    *,
    routing_exception: RoutingException | None,
    obligations: list[Obligation],
) -> dict[str, Any]:
    queue = application.owner_queue
    return {
        "application_id": str(application.pk),
        "public_reference": application.public_reference,
        "draft_reference": application.draft_reference,
        "status": application.status,
        "accepted_at": revision.accepted_at.isoformat(),
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "submission_revision": revision.number,
        "submission_sha256": revision.sha256,
        "policy_version_id": str(revision.policy_version_id),
        "policy_number": revision.policy_version.number,
        "owner_queue": {
            "queue_key": queue.queue_key,
            "display_name": queue.display_name,
            "jurisdiction_code": queue.jurisdiction.code,
        },
        "routing": {
            "resolved": routing_exception is None,
            "exception_code": routing_exception.code if routing_exception else None,
            "exception_id": str(routing_exception.pk) if routing_exception else None,
        },
        "obligations": [_obligation_body(o) for o in obligations],
    }


# ---- TR-01 ------------------------------------------------------------------------------------


class SubmitApplication(CommandHandler[Application]):
    """API-024: one accepted command, one receipt, SUBMITTED with accountable ownership."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.APPLICANT:
            raise Forbidden("Only applicant accounts submit applications")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        probe = (
            Application.objects.filter(pk=uow.envelope.target_id).select_related("service").first()
        )
        if probe is None or not can_edit_draft(uow.actor, probe, uow.now):
            raise ResourceNotFound("Application not found")
        # Fence order (workflow s.9): service activation fence before the application row so a
        # concurrent policy activation and this submission never interleave.
        lock_service_fence(probe.service_id)
        application = editable_draft_for_actor(
            uow.actor, uow.envelope.target_id, uow.now, lock=True
        )
        if application is None:
            raise ResourceNotFound("Application not found")
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        if target.status != ApplicationStatus.DRAFT.value:
            raise InvalidTransition("Only a DRAFT application can be submitted")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(
                set(data)
                - {
                    "draft_revision",
                    "reviewed_policy_version_id",
                    "declaration_acceptances",
                    "document_version_ids",
                }
            )
        ]
        current = target.current_draft_revision
        current_number = current.revision_number if current else 0
        expected = data.get("draft_revision")
        if not isinstance(expected, int) or isinstance(expected, bool):
            violations.append(Violation("/draft_revision", "invalid", "must be an integer"))
        reviewed = data.get("reviewed_policy_version_id")
        try:
            reviewed_id = UUID(str(reviewed))
        except ValueError:
            violations.append(Violation("/reviewed_policy_version_id", "invalid", "must be a UUID"))
            reviewed_id = None
        acceptances = data.get("declaration_acceptances")
        if not isinstance(acceptances, list):
            violations.append(Violation("/declaration_acceptances", "invalid", "must be a list"))
            acceptances = []
        doc_ids_raw = data.get("document_version_ids")
        if not isinstance(doc_ids_raw, list):
            violations.append(Violation("/document_version_ids", "invalid", "must be a list"))
            doc_ids_raw = []
        if violations:
            raise ValidationFailed(violations=violations)
        if expected != current_number or current is None:
            raise VersionConflict(
                "The draft changed since it was reviewed",
                extensions={
                    "current_version": target.version,
                    "current_draft_revision": current_number,
                },
            )

        # Policy: select and pin under the fence; the reviewed version must still be the one.
        service = target.service
        policy = select_policy(service.pk, service.owner_queue.jurisdiction_id, uow.now)
        if reviewed_id != policy.pk:
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/reviewed_policy_version_id",
                        "policy_changed",
                        "Requirements changed before submission; review the updated checklist",
                    )
                ],
                extensions={"current_policy_version_id": str(policy.pk)},
            )
        payload = policy.payload
        fields = dict((current.editable_payload or {}).get("fields", {}))
        cleaned, field_violations = validate_draft_fields(fields)
        violations.extend(field_violations)
        for key in REQUIRED_FIELDS:
            if key not in cleaned or cleaned[key] in ("", None):
                violations.append(Violation(f"/fields/{key}", "required", "is required"))
        if cleaned.get("application_type") == "RENEWAL" and not cleaned.get(
            "prior_certificate_reference"
        ):
            violations.append(
                Violation(
                    "/fields/prior_certificate_reference", "required", "required for a renewal"
                )
            )
        allowed = [str(c) for c in payload.get("allowed_categories", [])]
        category = next(
            (c for c in allowed if c.casefold() == str(cleaned.get("category_key", "")).casefold()),
            None,
        )
        if category is None:
            violations.append(
                Violation(
                    "/fields/category_key", "not_covered", "category is not covered by the policy"
                )
            )

        # Declarations: every demo declaration explicitly accepted at its current version.
        accepted: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(acceptances):
            pointer = f"/declaration_acceptances/{index}"
            if not isinstance(item, dict) or item.get("code") not in DECLARATION_CODES:
                violations.append(Violation(pointer, "unknown", "unknown declaration"))
                continue
            expected_version = next(v for c, v, _ in DEMO_DECLARATIONS if c == item["code"])
            if str(item.get("version")) != expected_version:
                violations.append(
                    Violation(f"{pointer}/version", "stale", "declaration version changed")
                )
                continue
            if item.get("accepted") is not True:
                violations.append(Violation(f"{pointer}/accepted", "required", "must be accepted"))
                continue
            accepted[str(item["code"])] = {"code": item["code"], "version": expected_version}
        for code in sorted(DECLARATION_CODES - set(accepted)):
            violations.append(
                Violation("/declaration_acceptances", "missing", f"declaration {code} not accepted")
            )
        if violations or category is None:
            raise ValidationFailed(violations=violations)

        # Evidence: every referenced version belongs to this case and is CLEAN; every required
        # requirement is covered. Missing evidence is EVIDENCE_INCOMPLETE, never a partial submit.
        from agni.documents.models import DocumentVersion, ScanState
        from agni.policies.domain.schema import required_documents

        doc_ids: list[UUID] = []
        for index, raw in enumerate(doc_ids_raw):
            try:
                doc_ids.append(UUID(str(raw)))
            except ValueError:
                violations.append(
                    Violation(f"/document_version_ids/{index}", "invalid", "must be a UUID")
                )
        if len(set(doc_ids)) != len(doc_ids):
            violations.append(Violation("/document_version_ids", "duplicate", "ids must be unique"))
        if violations:
            raise ValidationFailed(violations=violations)
        found = {
            d.pk: d for d in DocumentVersion.objects.filter(pk__in=doc_ids, application=target)
        }
        evidence: list[Violation] = []
        covered: dict[str, DocumentVersion] = {}
        for index, doc_id in enumerate(doc_ids):
            doc = found.get(doc_id)
            pointer = f"/document_version_ids/{index}"
            if doc is None:
                evidence.append(Violation(pointer, "not_found", "not a file of this application"))
            elif doc.scan_state == ScanState.QUARANTINED:
                label = REQUIREMENT_LABELS.get(doc.requirement_code, doc.requirement_code).lower()
                evidence.append(
                    Violation(
                        pointer, "quarantined", f"The {label} is still waiting for a security scan"
                    )
                )
            elif doc.scan_state == ScanState.REJECTED:
                evidence.append(
                    Violation(pointer, "rejected", "rejected files cannot support a submission")
                )
            else:
                covered.setdefault(doc.requirement_code, doc)
        required = list(required_documents(payload, category))
        for code in required:
            if code not in covered:
                evidence.append(
                    Violation(
                        "/document_version_ids",
                        "missing",
                        f"{REQUIREMENT_LABELS.get(code, code)} ({code}) is required",
                    )
                )
        if evidence:
            raise EvidenceIncomplete(
                "Required evidence is missing or not yet accepted", violations=evidence
            )

        # Routing (FR-07): exactly one target or a visible owned exception on the central queue.
        routing_artifact = (
            PolicyArtifact.objects.filter(kind="ROUTING", key=str(payload.get("routing_key", "")))
            .order_by("-number")
            .first()
        )
        entries = (
            list(
                RoutingEntry.objects.filter(artifact=routing_artifact).select_related(
                    "target_queue"
                )
            )
            if routing_artifact
            else []
        )
        ward_key = str(cleaned["ward_key"])
        routing_exception: RoutingException | None = None
        route_payload: dict[str, Any]
        try:
            route = resolve_route(entries, ward_key=ward_key, category_key=category, at=uow.now)
            owner_queue = DutyQueue.objects.select_related("jurisdiction").get(
                pk=route.target_queue_id
            )
            route_payload = {
                "resolved": True,
                "entry_id": str(route.entry_id),
                "priority": route.priority,
            }
        except RoutingUnresolvedError as exc:
            owner_queue = DutyQueue.objects.select_related("jurisdiction").get(
                pk=service.owner_queue_id
            )
            route_payload = {"resolved": False, "code": exc.code.value, "detail": exc.detail}

        # Freeze the submission.
        now = uow.now
        number = (
            SubmissionRevision.objects.filter(application=target)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
            or 0
        ) + 1
        premises = target.premises
        premise_snapshot = {
            "premises_id": str(premises.pk),
            "display_name": premises.display_name,
            "address_line1": premises.address_line1,
            "address_line2": premises.address_line2,
            "locality": premises.locality,
            "ward_key": premises.ward_key,
            "postal_code": premises.postal_code,
            "category_key": premises.category_key,
            "area_sqm": str(premises.area_sqm),
            "height_m": str(premises.height_m),
            "floor_count": premises.floor_count,
            "occupancy_count": premises.occupancy_count,
            "premises_version": premises.version,
        }
        declaration_snapshot = [
            {"code": c, "version": v, "text": t, "accepted": True, "accepted_at": now.isoformat()}
            for c, v, t in DEMO_DECLARATIONS
        ]
        selection_explanation = {
            "service_id": str(service.pk),
            "jurisdiction_id": str(service.owner_queue.jurisdiction_id),
            "legally_relevant_at": now.isoformat(),
            "policy_version_id": str(policy.pk),
            "policy_number": policy.number,
            "policy_sha256": policy.payload_sha256,
            "category_key": category,
            "ward_key": ward_key,
            "routing": route_payload,
        }
        frozen_payload = {"fields": {**cleaned, "category_key": category}}
        digest = canonical_sha256(
            {
                "payload": frozen_payload,
                "premise_snapshot": premise_snapshot,
                "declaration_snapshot": declaration_snapshot,
                "document_version_ids": sorted(str(d.pk) for d in covered.values()),
                "policy_version_id": str(policy.pk),
            }
        )
        revision = SubmissionRevision.objects.create(
            application=target,
            number=number,
            payload=frozen_payload,
            premise_snapshot=premise_snapshot,
            policy_version=policy,
            schema_ref=current.form_schema_ref,
            declaration_snapshot=declaration_snapshot,
            selection_explanation=selection_explanation,
            submitted_by=uow.actor,
            beneficiary=target.applicant,
            accepted_at=now,
            sha256=digest,
        )
        SubmissionDocument.objects.bulk_create(
            [
                SubmissionDocument(
                    submission_revision=revision, document_version=doc, requirement_code=code
                )
                for code, doc in covered.items()
            ]
        )

        # Canonical state.
        transition = transition_for("submit", ApplicationStatus.DRAFT)
        if transition is None:  # the catalogue always defines TR-01; defensive
            raise InvalidTransition("submit is not defined for DRAFT")
        _, target_state, event_type = transition
        new_version = target.version + 1  # the kernel increments after apply; events carry it
        target.status = target_state.value
        target.submitted_at = now
        target.submitted_revision_id = revision.pk
        target.policy_version_id = policy.pk
        target.owner_queue = owner_queue
        target.jurisdiction_id = owner_queue.jurisdiction_id
        _allocate_public_reference(target, now)
        submitted_event = record_event(
            uow,
            target,
            event_type,
            {
                "submission_revision": number,
                "policy_version": policy.number,
                "owner_queue_key": owner_queue.queue_key,
                "public_reference": target.public_reference,
            },
            audience=EventAudience.PUBLIC_CASE,
            ordinal=0,
            version=new_version,
        )
        stage = enter_stage(target, target_state.value, submitted_event, now, policy.pk)
        events = [submitted_event]
        if not route_payload["resolved"]:
            routing_exception = RoutingException.objects.create(
                application=target,
                code=route_payload["code"],
                input_snapshot={
                    "ward_key": ward_key,
                    "category_key": category,
                    "artifact": routing_artifact.reference if routing_artifact else None,
                    "detail": route_payload["detail"],
                },
                routing_artifact=routing_artifact,
                owner_queue=owner_queue,
            )
            events.append(
                record_event(
                    uow,
                    target,
                    "routing.exception_opened.v1",
                    {
                        "code": route_payload["code"],
                        "exception_id": str(routing_exception.pk),
                        "owner_queue_key": owner_queue.queue_key,
                    },
                    audience=EventAudience.INTERNAL,
                    ordinal=1,
                    version=new_version,
                )
            )
        target.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_revision_id",
                "policy_version_id",
                "owner_queue",
                "jurisdiction",
                "current_stage_instance",
                "updated_at",
            ]
        )

        # Obligations (workflow s.8): the case target and the current stage's task.
        calendar_artifact = (
            PolicyArtifact.objects.filter(kind="CALENDAR", key=str(payload.get("calendar_key", "")))
            .order_by("-number")
            .first()
        )
        calendar = (
            WorkingCalendar.from_artifact(calendar_artifact.payload) if calendar_artifact else None
        )
        obligations: list[Obligation] = []
        case_budget = int(payload.get("case_target_calendar_minutes", 0))
        if case_budget > 0:
            obligations.append(
                Obligation.objects.create(
                    application=target,
                    application_stage_instance=stage,
                    kind=ObligationKind.CASE_TARGET,
                    owner_queue=owner_queue,
                    policy_version=policy,
                    calendar_artifact=calendar_artifact,
                    time_basis=TimeBasis.CALENDAR,
                    start_event=submitted_event,
                    started_at=now,
                    budget_minutes=case_budget,
                    due_at=due_instant(
                        basis="CALENDAR", started_at=now, budget_minutes=case_budget
                    ),
                )
            )
        scrutiny_budget = int(
            payload.get("internal_targets", {}).get("scrutiny_working_minutes", 0)
        )
        if scrutiny_budget > 0 and calendar is not None:
            obligations.append(
                Obligation.objects.create(
                    application=target,
                    application_stage_instance=stage,
                    kind=ObligationKind.SCRUTINY_TASK,
                    owner_queue=owner_queue,
                    policy_version=policy,
                    calendar_artifact=calendar_artifact,
                    time_basis=TimeBasis.WORKING,
                    start_event=submitted_event,
                    started_at=now,
                    budget_minutes=scrutiny_budget,
                    due_at=due_instant(
                        basis="WORKING",
                        started_at=now,
                        budget_minutes=scrutiny_budget,
                        calendar=calendar,
                    ),
                )
            )

        body = receipt_body(
            target, revision, routing_exception=routing_exception, obligations=obligations
        )
        audits = [
            AuditEntry(
                "application",
                target.pk,
                "application.submitted",
                {
                    "public_reference": target.public_reference,
                    "submission_revision": number,
                    "submission_sha256": digest,
                    "policy_version_id": str(policy.pk),
                    "owner_queue": owner_queue.queue_key,
                    "routing": route_payload,
                    "documents": sorted(covered),
                },
            )
        ]
        if routing_exception is not None:
            audits.append(
                AuditEntry(
                    "routing_exception",
                    routing_exception.pk,
                    "routing.exception_opened",
                    {"code": routing_exception.code, "application_id": str(target.pk)},
                )
            )
        return CommandOutcome(
            status=200,
            body=body,
            aggregate=target,
            audits=audits,
            intents=[
                OutboxIntent(
                    event_type=e.event_type,
                    aggregate_type="application",
                    aggregate_id=target.pk,
                    payload=event_envelope(e, uow),
                    logical_action_id=e.pk,
                )
                for e in events
            ],
        )


# ---- TR-02 ------------------------------------------------------------------------------------


def _reason(data: dict[str, Any], violations: list[Violation]) -> str:
    reason = data.get("reason")
    if not isinstance(reason, str) or not (10 <= len(reason.strip()) <= 4000):
        violations.append(Violation("/reason", "length", "10 to 4000 characters"))
        return ""
    return reason.strip()


def _lock_case_for_staff(uow: UnitOfWork) -> Application:
    application = (
        Application.objects.select_for_update(of=("self",))
        .select_related(
            "owner_queue__jurisdiction", "service", "premises", "current_stage_instance"
        )
        .filter(pk=uow.envelope.target_id)
        .first()
    )
    if application is None or application.status == ApplicationStatus.DRAFT.value:
        raise ResourceNotFound("Application not found")
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
    ):
        raise ResourceNotFound("Application not found")  # out of scope == does not exist
    return application


class StartScrutiny(CommandHandler[Application]):
    """API-027 / TR-02: a scoped supervisor of the accountable queue starts scrutiny."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_role(snapshot, RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return _lock_case_for_staff(uow)

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason"})
        ]
        reason = _reason(data, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        transition = transition_for("start-scrutiny", target.status_enum)
        if transition is None:
            raise InvalidTransition("Scrutiny can only start on a SUBMITTED application")
        from .holds import ensure_not_on_hold

        ensure_not_on_hold(target, scope="transition")
        if RoutingException.objects.filter(
            application=target, state=RoutingExceptionState.OPEN
        ).exists():
            raise RoutingUnresolved("Resolve the open routing exception before starting scrutiny")
        _, target_state, event_type = transition
        new_version = target.version + 1
        target.status = target_state.value
        event = record_event(
            uow,
            target,
            event_type,
            {"owner_queue_key": target.owner_queue.queue_key},
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
        enter_stage(target, target_state.value, event, uow.now, target.policy_version_id)
        target.save(update_fields=["status", "current_stage_instance", "updated_at"])
        return CommandOutcome(
            status=200,
            body={
                "application_id": str(target.pk),
                "status": target.status,
                "public_reference": target.public_reference,
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "application.scrutiny_started",
                    {"reason": reason[:200]},
                )
            ],
            intents=[
                OutboxIntent(
                    event_type=event.event_type,
                    aggregate_type="application",
                    aggregate_id=target.pk,
                    payload=event_envelope(event, uow),
                    logical_action_id=event.pk,
                ),
                OutboxIntent(
                    event_type=note.event_type,
                    aggregate_type="application",
                    aggregate_id=target.pk,
                    payload=event_envelope(note, uow),
                    logical_action_id=note.pk,
                ),
            ],
        )


# ---- routing exception resolution (API-028) -------------------------------------------------


class ResolveRoutingException(CommandHandler[Application]):
    """A supervisor of the accountable (central) queue resolves the exception with a valid
    active mapping target; the old routing events are kept."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        require_role(snapshot, RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return _lock_case_for_staff(uow)

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        keys = {
            "target_jurisdiction_id",
            "target_queue_id",
            "routing_artifact_id",
            "reason",
            "exception_id",
        }
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field") for k in sorted(set(data) - keys)
        ]
        reason = _reason(data, violations)
        ids: dict[str, UUID] = {}
        for key in (
            "target_jurisdiction_id",
            "target_queue_id",
            "routing_artifact_id",
            "exception_id",
        ):
            try:
                ids[key] = UUID(str(data.get(key)))
            except ValueError:
                violations.append(Violation(f"/{key}", "invalid", "must be a UUID"))
        if violations:
            raise ValidationFailed(violations=violations)
        exception = (
            RoutingException.objects.select_for_update()
            .filter(pk=ids["exception_id"], application=target, state=RoutingExceptionState.OPEN)
            .first()
        )
        if exception is None:
            raise ResourceNotFound("Open routing exception not found")
        queue = (
            DutyQueue.objects.select_related("jurisdiction")
            .filter(pk=ids["target_queue_id"], active=True)
            .first()
        )
        if queue is None or queue.jurisdiction_id != ids["target_jurisdiction_id"]:
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/target_queue_id",
                        "invalid_target",
                        "queue must be active and belong to the target jurisdiction",
                    )
                ]
            )
        artifact = PolicyArtifact.objects.filter(
            pk=ids["routing_artifact_id"], kind="ROUTING"
        ).first()
        if artifact is None:
            raise ValidationFailed(
                violations=[
                    Violation("/routing_artifact_id", "not_found", "routing artifact not found")
                ]
            )
        if queue.service_id is not None and queue.service_id != target.service_id:
            raise ValidationFailed(
                violations=[
                    Violation("/target_queue_id", "scope", "queue is dedicated to another service")
                ]
            )

        new_version = target.version + 1
        previous_queue = target.owner_queue.queue_key
        target.owner_queue = queue
        target.jurisdiction_id = queue.jurisdiction_id
        event = record_event(
            uow,
            target,
            "routing.resolved.v1",
            {
                "exception_id": str(exception.pk),
                "from_queue_key": previous_queue,
                "to_queue_key": queue.queue_key,
                "routing_artifact": artifact.reference,
            },
            audience=EventAudience.INTERNAL,
            ordinal=0,
            version=new_version,
        )
        target.save(update_fields=["owner_queue", "jurisdiction", "updated_at"])
        exception.state = RoutingExceptionState.RESOLVED
        exception.resolved_by = uow.actor
        exception.resolution = reason
        exception.resolved_at = uow.now
        exception.version += 1
        exception.save(
            update_fields=[
                "state",
                "resolved_by",
                "resolution",
                "resolved_at",
                "version",
                "updated_at",
            ]
        )
        Obligation.objects.filter(application=target, state=ObligationState.ACTIVE).update(
            owner_queue=queue
        )
        return CommandOutcome(
            status=200,
            body={
                "application_id": str(target.pk),
                "status": target.status,
                "owner_queue": {
                    "queue_key": queue.queue_key,
                    "display_name": queue.display_name,
                    "jurisdiction_code": queue.jurisdiction.code,
                },
                "exception_id": str(exception.pk),
                "exception_state": exception.state,
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "routing_exception",
                    exception.pk,
                    "routing.exception_resolved",
                    {
                        "to_queue": queue.queue_key,
                        "artifact": artifact.reference,
                        "reason": reason[:200],
                    },
                )
            ],
            intents=[
                OutboxIntent(
                    event_type=event.event_type,
                    aggregate_type="application",
                    aggregate_id=target.pk,
                    payload=event_envelope(event, uow),
                    logical_action_id=event.pk,
                )
            ],
        )
