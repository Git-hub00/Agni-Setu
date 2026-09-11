"""Inspection endpoints API-038..044/046 and API-094, plus the scoped officer roster used by the
scheduling dialog (UI-11)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.identity.authz import load_snapshot
from agni.identity.domain.roles import RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import (
    AuthenticationRequired,
    Forbidden,
    MalformedRequest,
    ResourceNotFound,
)

from ..application.commands import (
    CancelInspection,
    CheckIn,
    FailVisit,
    ReassignInspection,
    RecordAvailability,
    RequireInspection,
    ScheduleInspection,
    inspection_body,
)
from ..application.reports import SaveReportDraft, SubmitReport, draft_body, report_body
from ..eligibility import eligible_officers
from ..models import (
    Assignment,
    AssignmentState,
    Availability,
    InspectionDraft,
    InspectionPurpose,
    InspectionStatus,
)
from ..selectors import visible_inspections

PAGE_SIZE = 20
MAX_WINDOW = timedelta(days=31)


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _staff_scope(request: Request) -> tuple[Principal, Any, Any]:
    principal = _principal(request)
    now = get_clock().now()
    snapshot = load_snapshot(principal, now)
    if snapshot.kind != PrincipalKind.STAFF:
        raise Forbidden("Inspections are a staff workspace")
    return principal, now, snapshot


def _instant(raw: str | None, name: str) -> Any:
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None or parsed.tzinfo is None:
        raise MalformedRequest(f"{name} must be an ISO 8601 UTC timestamp")
    return parsed


class InspectionListView(ApiView):
    """API-038."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _, now, snapshot = _staff_scope(request)
        queryset = visible_inspections(snapshot, now).select_related(
            "application__premises",
            "application__owner_queue",
            "checklist_artifact",
            "current_assignment__officer",
        )
        states = [s for s in request.query_params.getlist("state") if s]
        if states:
            if any(s not in InspectionStatus.values for s in states):
                raise MalformedRequest("unknown state filter")
            queryset = queryset.filter(status__in=states)
        purpose = request.query_params.get("purpose")
        if purpose:
            if purpose not in InspectionPurpose.values:
                raise MalformedRequest("unknown purpose filter")
            queryset = queryset.filter(purpose=purpose)
        officer = request.query_params.get("officer_id")
        if officer:
            try:
                queryset = queryset.filter(current_assignment__officer_id=UUID(officer))
            except ValueError as exc:
                raise MalformedRequest("officer_id must be a UUID") from exc
        appt_from = _instant(request.query_params.get("appointment_from"), "appointment_from")
        appt_to = _instant(request.query_params.get("appointment_to"), "appointment_to")
        if appt_from:
            queryset = queryset.filter(scheduled_end__gt=appt_from)
        if appt_to:
            queryset = queryset.filter(scheduled_start__lt=appt_to)
        if request.query_params.get("unassigned") == "true":
            queryset = queryset.filter(
                current_assignment__isnull=True, status=InspectionStatus.REQUESTED
            )
        rows = list(queryset.order_by("-created_at", "-id")[: PAGE_SIZE + 1])
        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        return ok(
            {
                "items": [inspection_body(i) for i in rows],
                "next_cursor": None,
                "has_more": has_more,
                "as_of": now.isoformat(),
            },
            request,
        )


class InspectionDetailView(ApiView):
    """API-039."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, inspection_id: UUID) -> Response:
        principal, now, snapshot = _staff_scope(request)
        inspection = (
            visible_inspections(snapshot, now)
            .select_related(
                "application__premises",
                "application__owner_queue__jurisdiction",
                "checklist_artifact",
                "current_assignment__officer",
                "current_report__checklist_artifact",
            )
            .filter(pk=inspection_id)
            .first()
        )
        if inspection is None:
            raise ResourceNotFound("Inspection not found")
        supervisor_here = snapshot.has_role(
            RoleKey.SUPERVISOR, jurisdiction_id=inspection.application.owner_queue.jurisdiction_id
        )
        assigned = (
            inspection.current_assignment is not None
            and inspection.current_assignment.officer_id == principal.pk
            and inspection.current_assignment.state == AssignmentState.ACTIVE
        )
        unstarted = inspection.status in (InspectionStatus.REQUESTED, InspectionStatus.SCHEDULED)
        actions = [
            {
                "key": "schedule",
                "enabled": supervisor_here and unstarted,
                "reason_code": None
                if (supervisor_here and unstarted)
                else ("NOT_AUTHORIZED" if not supervisor_here else "ATTEMPT_CLOSED"),
            },
            {
                "key": "reassign",
                "enabled": supervisor_here
                and unstarted
                and inspection.current_assignment is not None,
                "reason_code": None,
            },
            {"key": "cancel", "enabled": supervisor_here and unstarted, "reason_code": None},
            {
                "key": "check-in",
                "enabled": assigned and inspection.status == InspectionStatus.SCHEDULED,
                "reason_code": None if assigned else "NOT_ASSIGNED",
            },
            {
                "key": "fail-visit",
                "enabled": assigned
                and inspection.status in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS),
                "reason_code": None if assigned else "NOT_ASSIGNED",
            },
            {
                "key": "save-draft",
                "enabled": assigned
                and inspection.status in (InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS),
                "reason_code": None if assigned else "NOT_ASSIGNED",
            },
            {
                "key": "submit-report",
                "enabled": assigned and inspection.status == InspectionStatus.IN_PROGRESS,
                "reason_code": None
                if (assigned and inspection.status == InspectionStatus.IN_PROGRESS)
                else ("NOT_ASSIGNED" if not assigned else "CHECK_IN_REQUIRED"),
            },
        ]
        # The officer's own server draft (never another officer's); the accepted report is read
        # by everyone who can see the attempt.
        own_draft = (
            InspectionDraft.objects.filter(inspection=inspection, officer=principal).first()
            if assigned
            else None
        )
        report = inspection.current_report
        body = {
            **inspection_body(inspection),
            "checklist_items": inspection.checklist_artifact.payload.get("items", []),
            "draft": draft_body(own_draft) if own_draft else None,
            "report": report_body(report) if report else None,
            "assignments": [
                {
                    "assignment_id": str(a.pk),
                    "number": a.number,
                    "state": a.state,
                    "officer_id": str(a.officer_id),
                    "officer_name": a.officer.display_name,
                    "booking_start": a.booking_start.isoformat() if a.booking_start else None,
                    "booking_end": a.booking_end.isoformat() if a.booking_end else None,
                    "reason": a.reason,
                }
                for a in inspection.assignments.select_related("officer").order_by("number")
            ],
            "allowed_actions": actions,
        }
        response = ok(body, request)
        response["ETag"] = inspection.etag
        return response


class _InspectionCommandView(ApiView):
    permission_classes = [IsAuthenticated]
    handler_factory: Any = None
    command_name = ""

    def post(self, request: Request, inspection_id: UUID) -> Response:
        return self.run_command(
            request,
            self.handler_factory(),
            command_name=self.command_name,
            target_type="inspection",
            target_id=inspection_id,
            etag_type="inspection",
        )


class ScheduleView(_InspectionCommandView):
    handler_factory = ScheduleInspection
    command_name = "schedule-inspection"


class ReassignView(_InspectionCommandView):
    handler_factory = ReassignInspection
    command_name = "reassign-inspection"


class CancelView(_InspectionCommandView):
    handler_factory = CancelInspection
    command_name = "cancel-inspection"


class CheckInView(_InspectionCommandView):
    handler_factory = CheckIn
    command_name = "check-in"


class FailVisitView(_InspectionCommandView):
    handler_factory = FailVisit
    command_name = "fail-visit"


class ReportDraftView(ApiView):
    """API-045: PUT the officer's server draft (guarded by the inspection ETag; the response ETag
    is the draft's own version)."""

    permission_classes = [IsAuthenticated]

    def put(self, request: Request, inspection_id: UUID) -> Response:
        return self.run_command(
            request,
            SaveReportDraft(),
            command_name="save-report-draft",
            target_type="inspection",
            target_id=inspection_id,
            etag_type="draft",
        )


class SubmitReportView(_InspectionCommandView):
    """API-047."""

    handler_factory = SubmitReport
    command_name = "submit-report"


class RequireInspectionView(ApiView):
    """API-029 (case-level command)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            RequireInspection(),
            command_name="require-inspection",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class ScheduleWindowView(ApiView):
    """API-040: bookings and unavailability inside a bounded window for permitted officers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal, now, snapshot = _staff_scope(request)
        starts_at = _instant(request.query_params.get("starts_at"), "starts_at") or now
        ends_at = _instant(request.query_params.get("ends_at"), "ends_at") or (
            starts_at + timedelta(days=7)
        )
        if ends_at <= starts_at or ends_at - starts_at > MAX_WINDOW:
            raise MalformedRequest("window must be positive and at most 31 days")
        jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
        officers = (
            {o.pk: o for j in jurisdictions for o in eligible_officers(j, now)}
            if jurisdictions
            else ({principal.pk: principal} if snapshot.has_role(RoleKey.OFFICER) else {})
        )
        requested = [UUID(x) for x in request.query_params.getlist("officer_ids") if x]
        officer_ids = [pk for pk in officers if not requested or pk in requested]
        bookings = (
            Assignment.objects.filter(
                officer_id__in=officer_ids,
                state=AssignmentState.ACTIVE,
                booking_start__lt=ends_at,
                booking_end__gt=starts_at,
            )
            .select_related("inspection__application", "officer")
            .order_by("booking_start")
        )
        unavailable = Availability.objects.filter(
            officer_id__in=officer_ids, starts_at__lt=ends_at, ends_at__gt=starts_at
        ).order_by("starts_at")
        return ok(
            {
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "timezone": request.query_params.get("timezone") or "Asia/Kolkata",
                "officers": [
                    {"officer_id": str(pk), "display_name": o.display_name}
                    for pk, o in officers.items()
                    if pk in officer_ids
                ],
                "bookings": [
                    {
                        "assignment_id": str(a.pk),
                        "inspection_id": str(a.inspection_id),
                        "officer_id": str(a.officer_id),
                        "officer_name": a.officer.display_name,
                        "booking_start": a.booking_start.isoformat() if a.booking_start else None,
                        "booking_end": a.booking_end.isoformat() if a.booking_end else None,
                        "public_reference": a.inspection.application.public_reference,
                        "inspection_status": a.inspection.status,
                    }
                    for a in bookings
                ],
                "unavailability": [
                    {
                        "availability_id": str(u.pk),
                        "officer_id": str(u.officer_id),
                        "kind": u.kind,
                        "starts_at": u.starts_at.isoformat(),
                        "ends_at": u.ends_at.isoformat(),
                        "reason_code": u.reason_code,
                    }
                    for u in unavailable
                ],
                "as_of": now.isoformat(),
            },
            request,
        )


class OfficersView(ApiView):
    """Scoped officer roster for scheduling: the eligible officers of the supervisor's
    jurisdictions."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _, now, snapshot = _staff_scope(request)
        jurisdictions = snapshot.jurisdictions_for(RoleKey.SUPERVISOR)
        if not jurisdictions:
            raise Forbidden("Only supervisors list the officer roster")
        requested = request.query_params.get("jurisdiction_id")
        scope = jurisdictions
        if requested:
            try:
                wanted = UUID(requested)
            except ValueError as exc:
                raise MalformedRequest("jurisdiction_id must be a UUID") from exc
            scope = {wanted} & jurisdictions
        items: dict[UUID, dict[str, Any]] = {}
        for jurisdiction_id in scope:
            for officer in eligible_officers(jurisdiction_id, now):
                items[officer.pk] = {
                    "officer_id": str(officer.pk),
                    "display_name": officer.display_name,
                    "jurisdiction_id": str(jurisdiction_id),
                }
        return ok({"items": list(items.values()), "as_of": now.isoformat()}, request)


class AvailabilityView(ApiView):
    """API-094."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, staff_id: UUID) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        return self.run_command(
            request,
            RecordAvailability(),
            command_name="record-availability",
            target_type="availability:scope",
            target_id=staff_id,
            payload={**body, "officer_id": str(staff_id)},
            etag_type="availability",
        )
