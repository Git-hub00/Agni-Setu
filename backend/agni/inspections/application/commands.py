"""Inspection attempt, assignment and appointment commands (FR-08, FR-11; API-029, 041..044,
046, 094). None of these change the application state except TR-05 (require-inspection); they
mutate their own resources, keep every attempt and assignment version, and never reset the case
clock. Booking safety: officer scheduling fence + availability check + half-open GiST exclusion
(the constraint violation surfaces as APPOINTMENT_CONFLICT)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils.dateparse import parse_datetime

from agni.cases.application.submission import enter_stage, event_envelope, record_event
from agni.cases.domain.states import ApplicationStatus, transition_for
from agni.cases.models import Application, CaseEvent, EventAudience
from agni.identity.authz import load_snapshot, require_role
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.obligations.domain.clock import due_instant
from agni.obligations.models import Obligation, ObligationKind, ObligationState, TimeBasis
from agni.platform.commands import (
    AuditEntry,
    CommandHandler,
    CommandOutcome,
    OutboxIntent,
    UnitOfWork,
)
from agni.platform.errors import (
    AppointmentConflict,
    AuthorityRevoked,
    Forbidden,
    InvalidTransition,
    OfficerUnavailable,
    ResourceNotFound,
    RoutingUnresolved,
    ValidationFailed,
    VersionConflict,
    Violation,
)
from agni.platform.locks import lock_principal_fences
from agni.policies.models import PolicyArtifact, PolicyVersion
from agni.routing.models import RoutingException, RoutingExceptionState

from ..eligibility import is_eligible, overlapping_bookings, unavailable_between
from ..models import (
    FAILED_VISIT_REASONS,
    Assignment,
    AssignmentState,
    Availability,
    AvailabilityKind,
    Inspection,
    InspectionPurpose,
    InspectionStatus,
)

# ---- projections ----------------------------------------------------------------------------


def assignment_body(a: Assignment | None) -> dict[str, Any] | None:
    if a is None:
        return None
    return {
        "assignment_id": str(a.pk),
        "number": a.number,
        "state": a.state,
        "officer_id": str(a.officer_id),
        "officer_name": a.officer.display_name,
        "assigned_by": str(a.assigned_by_id),
        "reason": a.reason,
        "booking_start": a.booking_start.isoformat() if a.booking_start else None,
        "booking_end": a.booking_end.isoformat() if a.booking_end else None,
        "starts_at": a.starts_at.isoformat(),
        "ends_at": a.ends_at.isoformat() if a.ends_at else None,
        "version": a.version,
    }


def inspection_body(i: Inspection) -> dict[str, Any]:
    application = i.application
    return {
        "inspection_id": str(i.pk),
        "application_id": str(application.pk),
        "public_reference": application.public_reference,
        "application_status": application.status,
        "application_version": application.version,
        "attempt_number": i.attempt_number,
        "purpose": i.purpose,
        "parent_inspection_id": str(i.parent_inspection_id) if i.parent_inspection_id else None,
        "status": i.status,
        "checklist_ref": i.checklist_artifact.reference,
        "premises": {
            "display_name": application.premises.display_name,
            "locality": application.premises.locality,
            "category_key": application.premises.category_key,
            "ward_key": application.premises.ward_key,
        },
        "owner_queue": application.owner_queue.queue_key,
        "scheduled_start": i.scheduled_start.isoformat() if i.scheduled_start else None,
        "scheduled_end": i.scheduled_end.isoformat() if i.scheduled_end else None,
        "appointment_timezone": i.appointment_timezone,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "finished_at": i.finished_at.isoformat() if i.finished_at else None,
        "check_in": i.check_in or None,
        "failed_reason_code": i.failed_reason_code,
        "failed_notes": i.failed_notes,
        "cancel_reason": i.cancel_reason,
        "current_assignment": assignment_body(i.current_assignment),
        "version": i.version,
        "updated_at": i.updated_at.isoformat(),
    }


# ---- helpers --------------------------------------------------------------------------------


def _reason(
    data: dict[str, Any], violations: list[Violation], key: str = "reason", maximum: int = 4000
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not (10 <= len(value.strip()) <= maximum):
        violations.append(Violation(f"/{key}", "length", f"10 to {maximum} characters"))
        return ""
    return value.strip()


def _instant(
    data: dict[str, Any], key: str, violations: list[Violation], *, required: bool
) -> datetime | None:
    raw = data.get(key)
    if raw in (None, ""):
        if required:
            violations.append(Violation(f"/{key}", "required", "is required"))
        return None
    parsed = parse_datetime(str(raw))
    if parsed is None or parsed.tzinfo is None:
        violations.append(Violation(f"/{key}", "format", "must be an ISO 8601 UTC timestamp"))
        return None
    return parsed


def _application_version(
    data: dict[str, Any], application: Application, violations: list[Violation]
) -> None:
    value = data.get("application_version")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        violations.append(Violation("/application_version", "invalid", "positive integer required"))
        return
    if value != application.version:
        raise VersionConflict(
            "The case changed since it was read",
            extensions={"current_version": application.version, "resource": "application"},
        )


def _next_ordinal(application: Application, version: int) -> int:
    current = CaseEvent.objects.filter(
        application=application, aggregate_version=version
    ).aggregate(m=Max("ordinal"))["m"]
    return 0 if current is None else current + 1


def _case_event(
    uow: UnitOfWork,
    application: Application,
    event_type: str,
    payload: dict[str, Any],
    audience: str,
) -> CaseEvent:
    version = application.version
    return record_event(
        uow,
        application,
        event_type,
        payload,
        audience=audience,
        ordinal=_next_ordinal(application, version),
        version=version,
    )


def _intent(event: CaseEvent, uow: UnitOfWork) -> OutboxIntent:
    return OutboxIntent(
        event_type=event.event_type,
        aggregate_type="application",
        aggregate_id=event.application_id,
        payload=event_envelope(event, uow),
        logical_action_id=event.pk,
    )


def _supervisor_for(uow: UnitOfWork, application: Application) -> None:
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
    ):
        raise ResourceNotFound("Inspection not found")


def _lock_inspection(uow: UnitOfWork) -> Inspection:
    inspection = (
        Inspection.objects.select_for_update(of=("self",))
        .select_related(
            "application__owner_queue__jurisdiction",
            "application__premises",
            "checklist_artifact",
            "current_assignment__officer",
        )
        .filter(pk=uow.envelope.target_id)
        .first()
    )
    if inspection is None:
        raise ResourceNotFound("Inspection not found")
    return inspection


def _new_attempt(
    uow: UnitOfWork,
    application: Application,
    *,
    purpose: str,
    parent: Inspection | None,
    checklist: PolicyArtifact,
    reason: str,
) -> Inspection:
    number = (
        Inspection.objects.filter(application=application).aggregate(m=Max("attempt_number"))["m"]
        or 0
    ) + 1
    return Inspection.objects.create(
        application=application,
        attempt_number=number,
        purpose=purpose,
        parent_inspection=parent,
        status=InspectionStatus.REQUESTED,
        checklist_artifact=checklist,
        requested_by=uow.actor,
        request_reason=reason,
    )


# ---- TR-05 require-inspection (API-029) -----------------------------------------------------


class RequireInspection(CommandHandler[Application]):
    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Application | None:
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
        _supervisor_for(uow, application)
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:
            raise ResourceNotFound("Application not found")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(
                set(data) - {"purpose", "reason", "preferred_window_start", "preferred_window_end"}
            )
        ]
        if data.get("purpose", "INITIAL") != InspectionPurpose.INITIAL:
            violations.append(Violation("/purpose", "invalid", "only INITIAL at this stage"))
        reason = _reason(data, violations)
        window_start = _instant(data, "preferred_window_start", violations, required=False)
        window_end = _instant(data, "preferred_window_end", violations, required=False)
        if (window_start is None) != (window_end is None):
            violations.append(
                Violation("/preferred_window_end", "pair", "give both window ends or neither")
            )
        elif window_start and window_end and window_end <= window_start:
            violations.append(
                Violation("/preferred_window_end", "interval", "must be after the start")
            )
        if violations:
            raise ValidationFailed(violations=violations)
        transition = transition_for("require-inspection", target.status_enum)
        if transition is None:
            raise InvalidTransition("An inspection can only be required during SCRUTINY")
        from agni.cases.application.holds import ensure_not_on_hold

        ensure_not_on_hold(target, scope="transition")
        if RoutingException.objects.filter(
            application=target, state=RoutingExceptionState.OPEN
        ).exists():
            raise RoutingUnresolved("Resolve the open routing exception first")
        pinned_id = target.policy_version_id
        if pinned_id is None:
            raise InvalidTransition("The case has no pinned policy")
        policy = PolicyVersion.objects.filter(pk=pinned_id).first()
        if policy is None:
            raise InvalidTransition("The case has no pinned policy")
        if not policy.payload.get("inspection_required", False):
            raise InvalidTransition("The pinned policy does not require a site inspection")
        checklist = (
            PolicyArtifact.objects.filter(
                kind="CHECKLIST", key=str(policy.payload.get("checklist_key", ""))
            )
            .order_by("-number")
            .first()
        )
        if checklist is None:
            raise InvalidTransition("The pinned policy references no published checklist")

        _, target_state, event_type = transition
        new_version = target.version + 1
        target.status = target_state.value
        inspection = _new_attempt(
            uow,
            target,
            purpose=InspectionPurpose.INITIAL,
            parent=None,
            checklist=checklist,
            reason=reason,
        )
        inspection.preferred_window_start = window_start
        inspection.preferred_window_end = window_end
        inspection.save(
            update_fields=["preferred_window_start", "preferred_window_end", "updated_at"]
        )
        event = record_event(
            uow,
            target,
            event_type,
            {
                "inspection_id": str(inspection.pk),
                "attempt_number": inspection.attempt_number,
                "checklist_ref": checklist.reference,
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
        stage = enter_stage(target, target_state.value, event, uow.now, target.policy_version_id)
        target.save(update_fields=["status", "current_stage_instance", "updated_at"])
        # Scrutiny task satisfied; inspection task opens on the new stage (case target untouched).
        Obligation.objects.filter(
            application=target, kind=ObligationKind.SCRUTINY_TASK, state=ObligationState.ACTIVE
        ).update(state=ObligationState.SATISFIED, satisfied_event=event)
        budget = int(
            policy.payload.get("internal_targets", {}).get("inspection_calendar_minutes", 0)
        )
        calendar_artifact = (
            PolicyArtifact.objects.filter(
                kind="CALENDAR", key=str(policy.payload.get("calendar_key", ""))
            )
            .order_by("-number")
            .first()
        )
        if budget > 0:
            Obligation.objects.create(
                application=target,
                application_stage_instance=stage,
                kind=ObligationKind.INSPECTION_TASK,
                owner_queue=target.owner_queue,
                policy_version=policy,
                calendar_artifact=calendar_artifact,
                time_basis=TimeBasis.CALENDAR,
                start_event=event,
                started_at=uow.now,
                budget_minutes=budget,
                due_at=due_instant(basis="CALENDAR", started_at=uow.now, budget_minutes=budget),
            )
        inspection.refresh_from_db()
        body = {**inspection_body(inspection), "application_version": new_version}
        return CommandOutcome(
            status=201,
            body=body,
            aggregate=target,
            audits=[
                AuditEntry(
                    "application",
                    target.pk,
                    "application.inspection_required",
                    {"inspection_id": str(inspection.pk), "reason": reason[:200]},
                )
            ],
            intents=[_intent(event, uow), _intent(note, uow)],
        )


# ---- schedule / reassign (API-041 / API-042) ------------------------------------------------


def _book(
    uow: UnitOfWork,
    inspection: Inspection,
    officer: Principal,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
) -> Assignment:
    """Create the next ACTIVE assignment under the officer fence. Availability is checked here;
    booking overlap is checked here for a clear message and enforced by the exclusion constraint."""
    lock_principal_fences([officer.pk])
    if unavailable_between(officer.pk, starts_at, ends_at):
        raise OfficerUnavailable("The officer is marked unavailable for that interval")
    clash = overlapping_bookings(
        officer.pk, starts_at, ends_at, exclude_inspection_id=inspection.pk
    ).first()
    if clash is not None:
        raise AppointmentConflict(
            "The officer already has a booking in that interval",
            extensions={
                "conflicting_interval": {
                    "start": clash.booking_start.isoformat() if clash.booking_start else None,
                    "end": clash.booking_end.isoformat() if clash.booking_end else None,
                }
            },
        )
    number = (
        Assignment.objects.filter(inspection=inspection).aggregate(m=Max("number"))["m"] or 0
    ) + 1
    try:
        with transaction.atomic():
            return Assignment.objects.create(
                inspection=inspection,
                officer=officer,
                assigned_by=uow.actor,
                number=number,
                state=AssignmentState.ACTIVE,
                starts_at=uow.now,
                reason=reason,
                booking_start=starts_at,
                booking_end=ends_at,
            )
    except IntegrityError as exc:
        raise AppointmentConflict("The officer already has a booking in that interval") from exc


def _retire_current(inspection: Inspection, state: str, now: datetime) -> Assignment | None:
    current = inspection.current_assignment
    if current is None or current.state != AssignmentState.ACTIVE:
        return None
    current.state = state
    current.ends_at = now
    current.version += 1
    current.save(update_fields=["state", "ends_at", "version", "updated_at"])
    return current


def _schedule_payload(
    data: dict[str, Any], application: Application, *, require_officer: bool, require_time: bool
) -> tuple[dict[str, Any], list[Violation]]:
    violations: list[Violation] = []
    out: dict[str, Any] = {}
    officer_raw = data.get("officer_id", data.get("new_officer_id"))
    if officer_raw in (None, ""):
        if require_officer:
            violations.append(Violation("/officer_id", "required", "is required"))
    else:
        try:
            out["officer_id"] = UUID(str(officer_raw))
        except ValueError:
            violations.append(Violation("/officer_id", "invalid", "must be a UUID"))
    starts = _instant(data, "starts_at", violations, required=require_time)
    ends = _instant(data, "ends_at", violations, required=require_time)
    if starts and ends and ends <= starts:
        violations.append(
            Violation("/ends_at", "interval", "The appointment must end after it starts")
        )
    out["starts_at"], out["ends_at"] = starts, ends
    tz = data.get("appointment_timezone")
    if tz is not None:
        try:
            ZoneInfo(str(tz))
            out["timezone"] = str(tz)
        except (ZoneInfoNotFoundError, ValueError):
            violations.append(
                Violation("/appointment_timezone", "invalid", "unknown IANA timezone")
            )
    out["reason"] = _reason(data, violations)
    note = data.get("notification_note")
    if note is not None and (not isinstance(note, str) or len(note) > 1000):
        violations.append(Violation("/notification_note", "length", "at most 1000 characters"))
    out["note"] = note if isinstance(note, str) else None
    _application_version(data, application, violations)
    return out, violations


class ScheduleInspection(CommandHandler[Inspection]):
    """API-041: book an eligible officer for an unstarted attempt (REQUESTED or SCHEDULED)."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        _supervisor_for(uow, inspection.application)
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "officer_id",
            "starts_at",
            "ends_at",
            "appointment_timezone",
            "reason",
            "application_version",
            "notification_note",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        parsed, more = _schedule_payload(
            data, target.application, require_officer=True, require_time=True
        )
        violations.extend(more)
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status not in (InspectionStatus.REQUESTED, InspectionStatus.SCHEDULED):
            raise InvalidTransition("Only an unstarted attempt can be scheduled")
        application = target.application
        officer = Principal.objects.filter(pk=parsed["officer_id"]).first()
        if officer is None or not is_eligible(
            officer.pk, application.owner_queue.jurisdiction_id, uow.now
        ):
            raise OfficerUnavailable(
                "The officer is not an eligible active officer for this jurisdiction"
            )
        starts_at, ends_at = parsed["starts_at"], parsed["ends_at"]
        previous = _retire_current(target, AssignmentState.SUPERSEDED, uow.now)
        assignment = _book(uow, target, officer, starts_at, ends_at, parsed["reason"])
        target.current_assignment = assignment
        target.status = InspectionStatus.SCHEDULED
        target.scheduled_start = starts_at
        target.scheduled_end = ends_at
        target.appointment_timezone = (
            parsed.get("timezone") or target.appointment_timezone or "Asia/Kolkata"
        )
        target.save(
            update_fields=[
                "current_assignment",
                "status",
                "scheduled_start",
                "scheduled_end",
                "appointment_timezone",
                "updated_at",
            ]
        )
        public = _case_event(
            uow,
            application,
            "inspection.scheduled.v1",
            {
                "inspection_id": str(target.pk),
                "attempt_number": target.attempt_number,
                "scheduled_start": starts_at.isoformat(),
                "scheduled_end": ends_at.isoformat(),
                "timezone": target.appointment_timezone,
                "note": parsed["note"],
            },
            EventAudience.PUBLIC_CASE,
        )
        internal = _case_event(
            uow,
            application,
            "inspection.assignment_changed.v1",
            {
                "inspection_id": str(target.pk),
                "assignment_number": assignment.number,
                "officer_id": str(officer.pk),
                "superseded_number": previous.number if previous else None,
            },
            EventAudience.INTERNAL,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body=inspection_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.scheduled",
                    {
                        "assignment_number": assignment.number,
                        "officer_id": str(officer.pk),
                        "start": starts_at.isoformat(),
                        "end": ends_at.isoformat(),
                        "reason": parsed["reason"][:200],
                    },
                )
            ],
            intents=[_intent(public, uow), _intent(internal, uow)],
        )


class ReassignInspection(CommandHandler[Inspection]):
    """API-042: supersede the ACTIVE assignment with a new eligible officer (and optionally a new
    time). The case clock is untouched; stale offline authority is revoked by the version bump."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        _supervisor_for(uow, inspection.application)
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        data = dict(uow.envelope.payload)
        allowed = {
            "new_officer_id",
            "reason",
            "application_version",
            "starts_at",
            "ends_at",
            "appointment_timezone",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        parsed, more = _schedule_payload(
            data, target.application, require_officer=True, require_time=False
        )
        violations.extend(more)
        if violations:
            raise ValidationFailed(violations=violations)
        if (
            target.status not in (InspectionStatus.SCHEDULED, InspectionStatus.REQUESTED)
            or target.current_assignment is None
        ):
            raise InvalidTransition(
                "Only a scheduled, unstarted attempt with an active assignment can be reassigned"
            )
        application = target.application
        officer = Principal.objects.filter(pk=parsed["officer_id"]).first()
        if officer is None or not is_eligible(
            officer.pk, application.owner_queue.jurisdiction_id, uow.now
        ):
            raise OfficerUnavailable(
                "The officer is not an eligible active officer for this jurisdiction"
            )
        starts_at = parsed["starts_at"] or target.scheduled_start
        ends_at = parsed["ends_at"] or target.scheduled_end
        if starts_at is None or ends_at is None:
            raise ValidationFailed(
                violations=[
                    Violation("/starts_at", "required", "the attempt has no appointment yet")
                ]
            )
        previous = _retire_current(target, AssignmentState.SUPERSEDED, uow.now)
        assignment = _book(uow, target, officer, starts_at, ends_at, parsed["reason"])
        target.current_assignment = assignment
        target.scheduled_start = starts_at
        target.scheduled_end = ends_at
        if parsed.get("timezone"):
            target.appointment_timezone = parsed["timezone"]
        target.save(
            update_fields=[
                "current_assignment",
                "scheduled_start",
                "scheduled_end",
                "appointment_timezone",
                "updated_at",
            ]
        )
        internal = _case_event(
            uow,
            application,
            "inspection.assignment_changed.v1",
            {
                "inspection_id": str(target.pk),
                "assignment_number": assignment.number,
                "officer_id": str(officer.pk),
                "superseded_number": previous.number if previous else None,
                "revoked_package_for": str(previous.officer_id) if previous else None,
            },
            EventAudience.INTERNAL,
        )
        intents = [_intent(internal, uow)]
        if parsed["starts_at"] or parsed["ends_at"]:
            public = _case_event(
                uow,
                application,
                "inspection.rescheduled.v1",
                {
                    "inspection_id": str(target.pk),
                    "scheduled_start": starts_at.isoformat(),
                    "scheduled_end": ends_at.isoformat(),
                    "timezone": target.appointment_timezone,
                },
                EventAudience.PUBLIC_CASE,
            )
            intents.append(_intent(public, uow))
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body=inspection_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.reassigned",
                    {
                        "from_officer": str(previous.officer_id) if previous else None,
                        "to_officer": str(officer.pk),
                        "assignment_number": assignment.number,
                        "reason": parsed["reason"][:200],
                    },
                )
            ],
            intents=intents,
        )


# ---- cancel (API-043) -----------------------------------------------------------------------


class CancelInspection(CommandHandler[Inspection]):
    """Cancel an uncompleted attempt; the record stays and a new REQUESTED attempt (the required
    next action) is created because the case still needs a visit."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        _supervisor_for(uow, inspection.application)
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"reason", "application_version"})
        ]
        reason = _reason(data, violations)
        _application_version(data, target.application, violations)
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status not in (InspectionStatus.REQUESTED, InspectionStatus.SCHEDULED):
            raise InvalidTransition("Only an unstarted attempt can be cancelled")
        revoked = _retire_current(target, AssignmentState.REVOKED, uow.now)
        target.status = InspectionStatus.CANCELLED
        target.cancel_reason = reason
        target.finished_at = uow.now
        target.save(update_fields=["status", "cancel_reason", "finished_at", "updated_at"])
        follow_up = _new_attempt(
            uow,
            target.application,
            purpose=target.purpose,
            parent=target,
            checklist=target.checklist_artifact,
            reason=f"Follow-up after cancelled attempt {target.attempt_number}",
        )
        public = _case_event(
            uow,
            target.application,
            "inspection.cancelled.v1",
            {
                "inspection_id": str(target.pk),
                "attempt_number": target.attempt_number,
                "next_attempt_id": str(follow_up.pk),
            },
            EventAudience.PUBLIC_CASE,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body={**inspection_body(target), "next_attempt_id": str(follow_up.pk)},
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.cancelled",
                    {
                        "reason": reason[:200],
                        "revoked_assignment": revoked.number if revoked else None,
                        "next_attempt_id": str(follow_up.pk),
                    },
                )
            ],
            intents=[_intent(public, uow)],
        )


# ---- officer actions: check-in (API-044), fail-visit (API-046) -------------------------------


def _assigned_officer_only(uow: UnitOfWork, inspection: Inspection) -> Assignment:
    current = inspection.current_assignment
    if (
        current is None
        or current.state != AssignmentState.ACTIVE
        or current.officer_id != uow.actor.pk
    ):
        raise ResourceNotFound("Inspection not found")  # unassigned actors learn nothing
    # Current-authority fence (B11): an assignment is not authority. The officer role for the
    # case jurisdiction must still be in force at command time - a binding revoked while the
    # device was offline blocks the local submission (docs/09 s.7 AUTHORITY_REVOKED).
    snapshot = load_snapshot(uow.actor, uow.now)
    if not snapshot.active or not snapshot.has_role(
        RoleKey.OFFICER, jurisdiction_id=inspection.application.owner_queue.jurisdiction_id
    ):
        raise AuthorityRevoked("Your officer authority for this case is no longer current")
    return current


def _assignment_version(
    data: dict[str, Any], assignment: Assignment, violations: list[Violation]
) -> None:
    value = data.get("assignment_version")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        violations.append(Violation("/assignment_version", "invalid", "positive integer required"))
        return
    if value != assignment.version:
        from agni.platform.errors import AssignmentChanged

        raise AssignmentChanged(
            "The assignment changed since it was read",
            extensions={"current_assignment_version": assignment.version},
        )


class CheckIn(CommandHandler[Inspection]):
    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff perform inspections")

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        _assigned_officer_only(uow, inspection)
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        assignment = _assigned_officer_only(uow, target)
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "assignment_version",
            "captured_at",
            "latitude",
            "longitude",
            "accuracy_m",
            "location_unavailable_reason",
            "notes",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, target.application, violations)
        _assignment_version(data, assignment, violations)
        captured_at = _instant(data, "captured_at", violations, required=True)
        coords = [data.get("latitude"), data.get("longitude"), data.get("accuracy_m")]
        present = [c is not None for c in coords]
        if any(present) and not all(present):
            violations.append(
                Violation(
                    "/latitude",
                    "pair",
                    "latitude, longitude and accuracy_m are given together or not at all",
                )
            )
        if all(present):
            try:
                lat, lon, acc = float(coords[0]), float(coords[1]), float(coords[2])  # type: ignore[arg-type]
                if not (-90 <= lat <= 90 and -180 <= lon <= 180 and acc >= 0):
                    raise ValueError
            except (TypeError, ValueError):
                violations.append(Violation("/latitude", "range", "coordinates out of range"))
        else:
            reason = data.get("location_unavailable_reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(
                    Violation(
                        "/location_unavailable_reason",
                        "required",
                        "required when no location is captured",
                    )
                )
        notes = data.get("notes")
        if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
            violations.append(Violation("/notes", "length", "at most 2000 characters"))
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status != InspectionStatus.SCHEDULED:
            raise InvalidTransition("Check-in is only possible for a scheduled attempt")
        target.status = InspectionStatus.IN_PROGRESS
        target.started_at = uow.now
        target.check_in = {
            "captured_at": captured_at.isoformat() if captured_at else None,
            "server_received_at": uow.now.isoformat(),
            "location": {"latitude": coords[0], "longitude": coords[1], "accuracy_m": coords[2]}
            if all(present)
            else None,
            "location_unavailable_reason": data.get("location_unavailable_reason"),
            "notes": notes,
        }
        target.save(update_fields=["status", "started_at", "check_in", "updated_at"])
        event = _case_event(
            uow,
            target.application,
            "inspection.checked_in.v1",
            {
                "inspection_id": str(target.pk),
                "started_at": uow.now.isoformat(),
                "location_captured": all(present),
            },
            EventAudience.INTERNAL,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body=inspection_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.checked_in",
                    {
                        "location_captured": all(present),
                        "reason": data.get("location_unavailable_reason"),
                    },
                )
            ],
            intents=[_intent(event, uow)],
        )


class FailVisit(CommandHandler[Inspection]):
    """API-046: FAILED attempt with a reason code, a new REQUESTED attempt as the next action,
    the case stays INSPECTION_PENDING and its clock keeps running."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff perform inspections")

    def lock_target(self, uow: UnitOfWork) -> Inspection | None:
        inspection = _lock_inspection(uow)
        _assigned_officer_only(uow, inspection)
        return inspection

    def apply(self, uow: UnitOfWork, target: Inspection | None) -> CommandOutcome[Inspection]:
        if target is None:
            raise ResourceNotFound("Inspection not found")
        assignment = _assigned_officer_only(uow, target)
        data = dict(uow.envelope.payload)
        allowed = {
            "application_version",
            "assignment_version",
            "reason_code",
            "reason",
            "captured_at",
            "document_version_ids",
            "suggested_window",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        _application_version(data, target.application, violations)
        _assignment_version(data, assignment, violations)
        code = data.get("reason_code")
        if code not in FAILED_VISIT_REASONS:
            violations.append(
                Violation("/reason_code", "invalid", "not an approved failed-visit reason")
            )
        reason = _reason(data, violations)
        captured_at = _instant(data, "captured_at", violations, required=True)
        doc_ids_raw = data.get("document_version_ids", [])
        doc_ids: list[UUID] = []
        if not isinstance(doc_ids_raw, list):
            violations.append(Violation("/document_version_ids", "invalid", "must be a list"))
        else:
            for index, raw in enumerate(doc_ids_raw):
                try:
                    doc_ids.append(UUID(str(raw)))
                except ValueError:
                    violations.append(
                        Violation(f"/document_version_ids/{index}", "invalid", "must be a UUID")
                    )
        window = data.get("suggested_window")
        if window is not None and not (
            isinstance(window, dict) and {"start", "end"} <= set(window)
        ):
            violations.append(
                Violation("/suggested_window", "invalid", "object with start and end")
            )
        if violations:
            raise ValidationFailed(violations=violations)
        if target.status not in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS):
            raise InvalidTransition(
                "Only a scheduled or in-progress attempt can be recorded as failed"
            )
        if doc_ids:
            from agni.documents.models import DocumentVersion, ScanState

            clean = set(
                DocumentVersion.objects.filter(
                    pk__in=doc_ids, application=target.application, scan_state=ScanState.CLEAN
                ).values_list("pk", flat=True)
            )
            missing = [str(d) for d in doc_ids if d not in clean]
            if missing:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/document_version_ids",
                            "not_clean",
                            "evidence must be CLEAN files of this case",
                        )
                    ],
                    extensions={"rejected": missing},
                )
        assignment.state = AssignmentState.FULFILLED
        assignment.ends_at = uow.now
        assignment.version += 1
        assignment.save(update_fields=["state", "ends_at", "version", "updated_at"])
        target.status = InspectionStatus.FAILED
        target.failed_reason_code = str(code)
        target.failed_notes = reason
        target.finished_at = uow.now
        target.check_in = {
            **(target.check_in or {}),
            "failed_captured_at": captured_at.isoformat() if captured_at else None,
            "evidence": [str(d) for d in doc_ids],
            "suggested_window": window,
        }
        target.save(
            update_fields=[
                "status",
                "failed_reason_code",
                "failed_notes",
                "finished_at",
                "check_in",
                "updated_at",
            ]
        )
        follow_up = _new_attempt(
            uow,
            target.application,
            purpose=target.purpose,
            parent=target,
            checklist=target.checklist_artifact,
            reason=f"Rescheduling after failed attempt {target.attempt_number} ({code})",
        )
        public = _case_event(
            uow,
            target.application,
            "inspection.visit_failed.v1",
            {
                "inspection_id": str(target.pk),
                "attempt_number": target.attempt_number,
                "reason_code": code,
                "next_attempt_id": str(follow_up.pk),
            },
            EventAudience.PUBLIC_CASE,
        )
        target.refresh_from_db()
        return CommandOutcome(
            status=200,
            body={**inspection_body(target), "next_attempt_id": str(follow_up.pk)},
            aggregate=target,
            audits=[
                AuditEntry(
                    "inspection",
                    target.pk,
                    "inspection.visit_failed",
                    {
                        "reason_code": code,
                        "reason": reason[:200],
                        "next_attempt_id": str(follow_up.pk),
                    },
                )
            ],
            intents=[_intent(public, uow)],
        )


# ---- availability (API-094) -----------------------------------------------------------------


class RecordAvailability(CommandHandler[Availability]):
    """An officer records their own interval, or a supervisor of the officer's jurisdiction does.
    Existing conflicting bookings are surfaced, never silently cancelled."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff record availability")

    def lock_target(self, uow: UnitOfWork) -> Availability | None:
        return None

    def apply(self, uow: UnitOfWork, target: Availability | None) -> CommandOutcome[Availability]:
        data = dict(uow.envelope.payload)
        allowed = {"officer_id", "kind", "starts_at", "ends_at", "reason_code", "reason"}
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        try:
            officer_id = UUID(str(data.get("officer_id")))
        except ValueError:
            violations.append(Violation("/officer_id", "invalid", "must be a UUID"))
            officer_id = None
        kind = data.get("kind")
        if kind not in AvailabilityKind.values:
            violations.append(Violation("/kind", "invalid", "AVAILABLE or UNAVAILABLE"))
        starts_at = _instant(data, "starts_at", violations, required=True)
        ends_at = _instant(data, "ends_at", violations, required=True)
        if starts_at and ends_at and ends_at <= starts_at:
            violations.append(Violation("/ends_at", "interval", "must be after the start"))
        code = data.get("reason_code")
        if not isinstance(code, str) or not (2 <= len(code) <= 40):
            violations.append(Violation("/reason_code", "invalid", "approved reason key"))
        reason = _reason(data, violations, maximum=1000)
        if violations or officer_id is None or starts_at is None or ends_at is None:
            raise ValidationFailed(violations=violations)
        officer = Principal.objects.filter(pk=officer_id, kind=PrincipalKind.STAFF).first()
        if officer is None:
            raise ResourceNotFound("Officer not found")
        if officer.pk != uow.actor.pk:
            snapshot = load_snapshot(uow.actor, uow.now)
            jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
            if not jurisdictions or not is_eligible(officer.pk, next(iter(jurisdictions)), uow.now):
                # A supervisor may only manage officers of a jurisdiction they supervise.
                covered = any(is_eligible(officer.pk, j, uow.now) for j in jurisdictions)
                if not covered:
                    raise ResourceNotFound("Officer not found")
        lock_principal_fences([officer.pk])
        record = Availability.objects.create(
            officer=officer,
            kind=str(kind),
            starts_at=starts_at,
            ends_at=ends_at,
            reason_code=str(code),
            created_by=uow.actor,
            reason=reason,
        )
        affected = (
            list(
                overlapping_bookings(officer.pk, starts_at, ends_at).select_related(
                    "inspection__application"
                )
            )
            if kind == AvailabilityKind.UNAVAILABLE
            else []
        )
        return CommandOutcome(
            status=201,
            body={
                "availability_id": str(record.pk),
                "officer_id": str(officer.pk),
                "kind": record.kind,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "reason_code": record.reason_code,
                "affected_bookings": [
                    {
                        "inspection_id": str(a.inspection_id),
                        "public_reference": a.inspection.application.public_reference,
                        "booking_start": a.booking_start.isoformat() if a.booking_start else None,
                        "booking_end": a.booking_end.isoformat() if a.booking_end else None,
                    }
                    for a in affected
                ],
                "version": record.version,
            },
            aggregate=record,
            created=True,
            audits=[
                AuditEntry(
                    "availability",
                    record.pk,
                    "availability.recorded",
                    {
                        "officer_id": str(officer.pk),
                        "kind": record.kind,
                        "affected_bookings": len(affected),
                    },
                )
            ],
        )
