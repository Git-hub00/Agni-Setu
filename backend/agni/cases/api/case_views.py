"""Application endpoints API-020..028 (FR-04/06/07/09) and the role overview (UI-09).
Reads start from the scoped selectors and filter events by audience; writes go through the
kernel commands."""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, QuerySet
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.certificates.application.registry import effective_status
from agni.certificates.models import Certificate, IssuanceRequest
from agni.decisions.application.commands import decision_body, readiness_body
from agni.decisions.models import Decision
from agni.identity.authz import AuthzSnapshot, load_snapshot
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import Principal, PrincipalKind
from agni.inspections.models import Inspection
from agni.obligations.models import Obligation, ObligationState
from agni.platform.api.payloads import has_control_characters
from agni.platform.api.views import ApiView, ok
from agni.platform.clock import get_clock
from agni.platform.errors import AuthenticationRequired, MalformedRequest, ResourceNotFound
from agni.policies.selection import evaluate_applicability
from agni.routing.models import RoutingException, RoutingExceptionState

from ..application.access import can_edit_draft
from ..application.commands import CreateDraftApplication
from ..application.drafts import PatchDraft, draft_projection
from ..application.holds import active_holds, hold_body
from ..application.lifecycle import (
    CreateHold,
    ReleaseHold,
    WithdrawApplication,
    owns_case,
    withdrawal_stages,
)
from ..application.submission import ResolveRoutingException, StartScrutiny, SubmitApplication
from ..domain.states import ApplicationStatus, allowed_transitions
from ..models import Application, CaseEvent, EventAudience, SubmissionRevision
from ..selectors import visible_applications
from .views import premises_projection

PAGE_SIZE = 20
TIMELINE_PAGE = 50


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _audiences(snapshot: AuthzSnapshot) -> list[str]:
    """Applicants see the public case timeline; staff also see INTERNAL. RESTRICTED (decision
    deliberation) is not exposed by any B06 projection."""
    if snapshot.kind == PrincipalKind.APPLICANT:
        return [EventAudience.PUBLIC_CASE]
    return [EventAudience.PUBLIC_CASE, EventAudience.INTERNAL]


def _obligation_summary(o: Obligation) -> dict[str, Any]:
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


def case_summary(a: Application) -> dict[str, Any]:
    active = (
        [o for o in a.obligations.all() if o.state == ObligationState.ACTIVE]
        if hasattr(a, "_prefetched_objects_cache")
        else list(a.obligations.filter(state=ObligationState.ACTIVE))
    )
    due = min((o.due_at for o in active if o.due_at), default=None)
    return {
        "application_id": str(a.pk),
        "draft_reference": a.draft_reference,
        "public_reference": a.public_reference,
        "status": a.status,
        "service_key": a.service.key,
        "premises": {
            "premises_id": str(a.premises_id),
            "display_name": a.premises.display_name,
            "category_key": a.premises.category_key,
            "locality": a.premises.locality,
        },
        "owner_queue": a.owner_queue.display_name,
        "owner_queue_key": a.owner_queue.queue_key,
        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        "next_due_at": due.isoformat() if due else None,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
        "version": a.version,
    }


def _encode_cursor(a: Application) -> str:
    raw = f"{a.created_at.isoformat()}|{a.pk}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        created, pk = base64.urlsafe_b64decode(value.encode()).decode().split("|", 1)
        UUID(pk)
        return created, pk
    except Exception as exc:  # noqa: BLE001
        raise MalformedRequest("cursor is not valid") from exc


def _scoped(principal: Principal, now: Any) -> tuple[AuthzSnapshot, QuerySet[Application]]:
    snapshot = load_snapshot(principal, now)
    queryset = (
        visible_applications(snapshot, now)
        .select_related(
            "service__owner_queue",
            "premises",
            "owner_queue__jurisdiction",
            "current_draft_revision",
        )
        .prefetch_related("obligations__owner_queue")
    )
    return snapshot, queryset


class ApplicationListView(ApiView):
    """API-020 list (scope before filter/count; stable cursor) and API-021 create."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        _, queryset = _scoped(principal, now)
        status = request.query_params.get("status")
        if status:
            if status not in ApplicationStatus.__members__:
                raise MalformedRequest("unknown status filter")
            queryset = queryset.filter(status=status)
        query = (request.query_params.get("q") or "").strip()[:80]
        if has_control_characters(query):
            raise MalformedRequest("search term must not contain control characters")
        if query:
            queryset = queryset.filter(
                Q(draft_reference__icontains=query)
                | Q(public_reference__icontains=query)
                | Q(premises__display_name__icontains=query)
            )
        cursor = request.query_params.get("cursor")
        if cursor:
            created, pk = _decode_cursor(cursor)
            queryset = queryset.filter(Q(created_at__lt=created) | Q(created_at=created, id__lt=pk))
        rows = list(queryset.order_by("-created_at", "-id")[: PAGE_SIZE + 1])
        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        return ok(
            {
                "items": [case_summary(a) for a in rows],
                "next_cursor": _encode_cursor(rows[-1]) if has_more and rows else None,
                "has_more": has_more,
            },
            request,
        )

    def post(self, request: Request) -> Response:
        principal = _principal(request)
        return self.run_command(
            request,
            CreateDraftApplication(),
            command_name="create-draft",
            target_type="create-draft:scope",
            target_id=principal.pk,
            etag_type="application",
        )


def _notice_facts(application: Application, *, staff: bool) -> dict[str, Any]:
    """Notice/finding facts for the detail projection and its action guards (B09)."""
    from agni.notices.domain.rules import (
        open_mandatory_findings,
        pending_required_items,
        reinspection_outstanding,
    )
    from agni.notices.models import Finding, Notice

    notices = list(
        Notice.objects.filter(application=application)
        .select_related("due_obligation")
        .prefetch_related("items")
        .order_by("type", "round_number")
    )
    findings = list(Finding.objects.filter(application=application))
    current_information = next(
        (n for n in notices if n.type == "INFORMATION" and n.state == "PUBLISHED"), None
    )
    open_findings = [f for f in findings if f.state != "VERIFIED_CLOSED"]
    summary = {
        "open_mandatory": len([f for f in open_findings if f.severity == "MANDATORY"]),
        "open_advisory": len([f for f in open_findings if f.severity == "ADVISORY"]),
        "verified_closed": len(findings) - len(open_findings),
        "reinspection_outstanding": reinspection_outstanding(findings),
    }
    return {
        "notices": [
            {
                "notice_id": str(n.pk),
                "type": n.type,
                "round_number": n.round_number,
                "state": n.state,
                "published_at": n.published_at.isoformat(),
                "due_at": n.due_obligation.due_at.isoformat()
                if n.due_obligation and n.due_obligation.due_at
                else None,
                "items_total": len(n.items.all()),
                "open_items": len([i for i in n.items.all() if i.state != "ACCEPTED"]),
                "internal_note": (n.internal_note or None) if staff else None,
            }
            for n in notices
        ],
        "summary": summary,
        "open_findings": [str(f.pk) for f in open_findings],
        "open_mandatory": open_mandatory_findings(findings),
        "reinspection_outstanding": summary["reinspection_outstanding"],
        "open_attempt": Inspection.objects.filter(
            application=application, status__in=["REQUESTED", "SCHEDULED", "IN_PROGRESS"]
        ).exists(),
        "current_information_notice": (
            {
                "notice_id": str(current_information.pk),
                "pending_items": pending_required_items(list(current_information.items.all())),
            }
            if current_information
            else None
        ),
    }


class ApplicationDetailView(ApiView):
    """API-022: canonical detail with allowed actions and safe blockers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot, queryset = _scoped(principal, now)
        application = queryset.filter(pk=application_id).first()
        if application is None:
            raise ResourceNotFound("Application not found")
        staff = snapshot.kind != PrincipalKind.APPLICANT
        supervisor_here = snapshot.has_role(
            RoleKey.SUPERVISOR, jurisdiction_id=application.owner_queue.jurisdiction_id
        )
        editable = application.status == "DRAFT" and can_edit_draft(principal, application, now)
        draft = draft_projection(application, now) if application.status == "DRAFT" else None
        category = str(
            (draft or {}).get("fields", {}).get("category_key") or application.premises.category_key
        )
        applicability = evaluate_applicability(
            application.service,
            jurisdiction_id=application.service.owner_queue.jurisdiction_id,
            category_key=category,
            at=now,
        )
        open_exception = (
            RoutingException.objects.filter(
                application=application, state=RoutingExceptionState.OPEN
            ).first()
            if staff
            else None
        )
        submission = (
            SubmissionRevision.objects.filter(application=application)
            .select_related("policy_version")
            .order_by("-number")
            .first()
        )
        publisher_here = supervisor_here and (
            snapshot.grant_for(
                Capability.NOTICE_PUBLISH,
                jurisdiction_id=application.owner_queue.jurisdiction_id,
            )
            is not None
        )
        notice_facts = _notice_facts(application, staff=staff)
        # Decision readiness (API-064) drives the approve/reject controls for a supervisor of
        # the case jurisdiction; the command re-evaluates every guard under the lock.
        readiness_facts: dict[str, Any] | None = None
        if supervisor_here and application.policy_version_id is not None:
            readiness_facts = readiness_body(application, snapshot, now)
        decision = (
            Decision.objects.filter(application=application).order_by("-decision_number").first()
        )
        issuance = (
            IssuanceRequest.objects.filter(application=application).order_by("-created_at").first()
        )
        certificate = (
            Certificate.objects.filter(application=application).order_by("-issued_at").first()
        )
        holds = active_holds(application)
        withdraw_ok = owns_case(principal, application) and application.status in (
            withdrawal_stages(application)
        )
        has_accepted_report = Inspection.objects.filter(
            application=application, current_report__isnull=False
        ).exists()
        actions: list[dict[str, Any]] = [
            {
                "key": "edit-draft",
                "enabled": editable,
                "reason_code": None if editable else "NOT_EDITABLE",
            }
        ]
        for _, command, _ in allowed_transitions(application.status_enum):
            enabled = False
            reason: str | None = "NOT_AVAILABLE_YET"
            if command == "submit":
                blockers = (draft or {}).get("blockers", [])
                enabled = editable and not blockers and applicability.applicable
                reason = (
                    None
                    if enabled
                    else (
                        "DRAFT_INCOMPLETE"
                        if blockers
                        else (
                            "POLICY_UNAVAILABLE" if not applicability.applicable else "NOT_EDITABLE"
                        )
                    )
                )
            elif command == "start-scrutiny":
                enabled = supervisor_here and open_exception is None
                reason = (
                    None
                    if enabled
                    else ("ROUTING_UNRESOLVED" if open_exception else "NOT_AUTHORIZED")
                )
            elif command == "require-inspection":
                required = bool(applicability.inspection_required)
                enabled = supervisor_here and open_exception is None and required
                if enabled:
                    reason = None
                elif open_exception:
                    reason = "ROUTING_UNRESOLVED"
                elif not required:
                    reason = "NOT_REQUIRED_BY_POLICY"
                else:
                    reason = "NOT_AUTHORIZED"
            elif command == "request-information":
                enabled = publisher_here and open_exception is None
                reason = (
                    None
                    if enabled
                    else ("ROUTING_UNRESOLVED" if open_exception else "NOT_AUTHORIZED")
                )
            elif command == "issue-deficiencies":
                enabled = publisher_here and bool(notice_facts["open_findings"])
                reason = (
                    None
                    if enabled
                    else ("NO_OPEN_FINDINGS" if publisher_here else "NOT_AUTHORIZED")
                )
            elif command == "accept-information":
                current = notice_facts["current_information_notice"]
                enabled = supervisor_here and current is not None and not current["pending_items"]
                reason = (
                    None
                    if enabled
                    else (
                        "NOT_AUTHORIZED"
                        if not supervisor_here
                        else ("RESPONSE_NOT_VERIFIED" if current else "NO_OPEN_NOTICE")
                    )
                )
            elif command == "complete-corrections":
                blocked = notice_facts["open_mandatory"] or notice_facts["reinspection_outstanding"]
                enabled = supervisor_here and not blocked and not notice_facts["open_attempt"]
                reason = (
                    None
                    if enabled
                    else (
                        "NOT_AUTHORIZED"
                        if not supervisor_here
                        else ("MANDATORY_FINDINGS_OPEN" if blocked else "INSPECTION_OPEN")
                    )
                )
            elif command == "require-reinspection":
                enabled = supervisor_here and bool(notice_facts["open_findings"])
                reason = (
                    None
                    if enabled
                    else ("NO_OPEN_FINDINGS" if supervisor_here else "NOT_AUTHORIZED")
                )
            elif command in ("approve", "reject"):
                if readiness_facts is not None:
                    blockers = readiness_facts[command]["blockers"]
                    enabled = not blockers
                    reason = None if enabled else str(blockers[0]["code"])
                else:
                    enabled = False
                    reason = "NOT_AUTHORIZED"
            elif command == "publish-instrument":
                enabled = False  # TR-11 is performed by the issuance job, never by a user
                reason = "SYSTEM_JOB"
            elif command == "withdraw":
                enabled = withdraw_ok and not holds
                reason = (
                    None
                    if enabled
                    else (
                        "ON_HOLD"
                        if withdraw_ok
                        else (
                            "STAGE_NOT_PERMITTED"
                            if owns_case(principal, application)
                            else "NOT_AUTHORIZED"
                        )
                    )
                )
            elif command == "return-for-clarification":
                enabled = supervisor_here and has_accepted_report and not holds
                reason = (
                    None
                    if enabled
                    else (
                        "NOT_AUTHORIZED"
                        if not supervisor_here
                        else ("ON_HOLD" if holds else "NO_ACCEPTED_REPORT")
                    )
                )
            if holds and enabled and command not in ("withdraw", "return-for-clarification"):
                blocked = {s for h in holds for s in h.command_block_scope}
                if "TRANSITIONS" in blocked or (
                    "DECISIONS" in blocked and command in ("approve", "reject")
                ):
                    enabled, reason = False, "ON_HOLD"
            actions.append({"key": command, "enabled": enabled, "reason_code": reason})
        if staff:
            actions.append(
                {
                    "key": "resolve-routing",
                    "enabled": supervisor_here and open_exception is not None,
                    "reason_code": None
                    if (supervisor_here and open_exception)
                    else "NO_OPEN_EXCEPTION",
                }
            )
            terminal = application.status in ("COMPLETED", "REJECTED", "WITHDRAWN")
            actions.append(
                {
                    "key": "add-hold",
                    "enabled": supervisor_here and not holds and not terminal,
                    "reason_code": None
                    if (supervisor_here and not holds and not terminal)
                    else (
                        "NOT_AUTHORIZED"
                        if not supervisor_here
                        else ("HOLD_ACTIVE" if holds else "CASE_CLOSED")
                    ),
                }
            )
            actions.append(
                {
                    "key": "release-hold",
                    "enabled": supervisor_here and bool(holds),
                    "reason_code": None
                    if (supervisor_here and holds)
                    else ("NOT_AUTHORIZED" if not supervisor_here else "NO_ACTIVE_HOLD"),
                }
            )
        body: dict[str, Any] = {
            **case_summary(application),
            "premises_detail": premises_projection(application.premises),
            "policy": {
                "applicable": applicability.applicable,
                "policy_version_id": str(applicability.policy_version_id)
                if applicability.policy_version_id
                else None,
                "policy_number": applicability.policy_number,
                "explanation": applicability.explanation,
                "inspection_required": applicability.inspection_required,
                "pinned_policy_version_id": str(application.policy_version_id)
                if application.policy_version_id
                else None,
            },
            "draft": draft,
            "submission": (
                {
                    "number": submission.number,
                    "accepted_at": submission.accepted_at.isoformat(),
                    "policy_version_id": str(submission.policy_version_id),
                    "policy_number": submission.policy_version.number,
                    "sha256": submission.sha256,
                    "fields": submission.payload.get("fields", {}),
                    "documents": [
                        {
                            "requirement_code": d.requirement_code,
                            "document_version_id": str(d.document_version_id),
                        }
                        for d in submission.documents.all()
                    ],
                }
                if submission
                else None
            ),
            "obligations": [
                _obligation_summary(o)
                for o in application.obligations.all()
                if staff or o.kind == "CASE_TARGET"
            ],
            "inspections": [
                {
                    "inspection_id": str(i.pk),
                    "attempt_number": i.attempt_number,
                    "purpose": i.purpose,
                    "status": i.status,
                    "scheduled_start": i.scheduled_start.isoformat() if i.scheduled_start else None,
                    "scheduled_end": i.scheduled_end.isoformat() if i.scheduled_end else None,
                    "appointment_timezone": i.appointment_timezone,
                    # Officer identity is internal; applicants see the appointment facts only.
                    "officer_name": (
                        i.current_assignment.officer.display_name
                        if staff and i.current_assignment is not None
                        else None
                    ),
                    "failed_reason_code": i.failed_reason_code,
                    # Report facts for staff: the deterministic evaluation, never a score.
                    "report": (
                        {
                            "report_id": str(i.current_report.pk),
                            "revision_number": i.current_report.revision_number,
                            "accepted_at": i.current_report.accepted_at.isoformat(),
                            "eligible_for_review": i.current_report.evaluation.get(
                                "eligible_for_review"
                            ),
                            "blockers": i.current_report.evaluation.get("blockers", []),
                            "na_requiring_review": i.current_report.evaluation.get(
                                "na_requiring_review", []
                            ),
                        }
                        if staff and i.current_report is not None
                        else (
                            {
                                "revision_number": i.current_report.revision_number,
                                "accepted_at": i.current_report.accepted_at.isoformat(),
                            }
                            if i.current_report is not None
                            else None
                        )
                    ),
                }
                for i in Inspection.objects.filter(application=application)
                .select_related("current_assignment__officer", "current_report")
                .order_by("attempt_number")
            ],
            "notices": notice_facts["notices"],
            "findings_summary": notice_facts["summary"] if staff else None,
            # Outcome / issuance summary (API s.7 CaseDetail): the published decision for every
            # reader, internal rationale for staff, issuance progress and the registry entry.
            "decision": decision_body(decision, staff=staff) if decision is not None else None,
            "issuance": (
                {
                    "issuance_request_id": str(issuance.pk),
                    "certificate_number": issuance.certificate_number,
                    "state": issuance.state,
                    "published_at": issuance.published_at.isoformat()
                    if issuance.published_at
                    else None,
                    **(
                        {
                            "attempts": issuance.attempts,
                            "last_error_code": issuance.last_error_code,
                        }
                        if staff
                        else {}
                    ),
                }
                if issuance is not None
                else None
            ),
            "certificate": (
                {
                    "certificate_id": str(certificate.pk),
                    "certificate_number": certificate.certificate_number,
                    "effective_status": effective_status(certificate, now),
                    "issued_at": certificate.issued_at.isoformat(),
                    "valid_until": certificate.valid_until.isoformat()
                    if certificate.valid_until
                    else None,
                    "is_demo": certificate.is_demo,
                }
                if certificate is not None
                else None
            ),
            "decision_readiness": readiness_facts,
            # Holds (FR-18): staff see the records; every reader sees the flag that explains
            # blocked actions. A hold is not a case state.
            "on_hold": bool(holds),
            "holds": [hold_body(h) for h in holds] if staff else None,
            "prior_certificate_id": str(application.prior_certificate_id)
            if application.prior_certificate_id
            else None,
            "closed_at": application.closed_at.isoformat() if application.closed_at else None,
            "routing_exception": (
                {
                    "exception_id": str(open_exception.pk),
                    "code": open_exception.code,
                    "input": open_exception.input_snapshot,
                    "owner_queue": open_exception.owner_queue.queue_key,
                    "routing_artifact_id": str(open_exception.routing_artifact_id)
                    if open_exception.routing_artifact_id
                    else None,
                }
                if open_exception
                else None
            ),
            "allowed_actions": actions,
        }
        response = ok(body, request)
        response["ETag"] = application.etag
        return response


class DraftPatchView(ApiView):
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            PatchDraft(),
            command_name="patch-draft",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class SubmitView(ApiView):
    """API-024 / TR-01."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            SubmitApplication(),
            command_name="submit",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class StartScrutinyView(ApiView):
    """API-027 / TR-02."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            StartScrutiny(),
            command_name="start-scrutiny",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class ResolveRoutingView(ApiView):
    """API-028."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            ResolveRoutingException(),
            command_name="resolve-routing",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class WithdrawView(ApiView):
    """API-030 / TR-13."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            WithdrawApplication(),
            command_name="withdraw",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class HoldCreateView(ApiView):
    """API-031."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application_id: UUID) -> Response:
        return self.run_command(
            request,
            CreateHold(),
            command_name="create-hold",
            target_type="application",
            target_id=application_id,
            etag_type="application",
        )


class HoldReleaseView(ApiView):
    """API-032."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, hold_id: UUID) -> Response:
        return self.run_command(
            request,
            ReleaseHold(),
            command_name="release-hold",
            target_type="hold",
            target_id=hold_id,
            etag_type="hold",
        )


def _event_body(e: CaseEvent) -> dict[str, Any]:
    return {
        "event_id": str(e.pk),
        "event_type": e.event_type,
        "aggregate_version": e.aggregate_version,
        "event_ordinal": e.ordinal,
        "occurred_at": e.occurred_at.isoformat(),
        "actor_kind": e.actor_kind,
        "audience": e.audience,
        "payload": e.payload,
    }


class TimelineView(ApiView):
    """API-025: audience-filtered chronological events ordered by aggregate version/ordinal."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot, queryset = _scoped(principal, now)
        application = queryset.filter(pk=application_id).first()
        if application is None:
            raise ResourceNotFound("Application not found")
        events = CaseEvent.objects.filter(
            application=application, audience__in=_audiences(snapshot)
        ).order_by("aggregate_version", "ordinal", "id")
        cursor = request.query_params.get("cursor")
        if cursor:
            try:
                version_str, ordinal_str = cursor.split(":", 1)
                version, ordinal = int(version_str), int(ordinal_str)
            except ValueError as exc:
                raise MalformedRequest("cursor is not valid") from exc
            events = events.filter(
                Q(aggregate_version__gt=version) | Q(aggregate_version=version, ordinal__gt=ordinal)
            )
        rows = list(events[: TIMELINE_PAGE + 1])
        has_more = len(rows) > TIMELINE_PAGE
        rows = rows[:TIMELINE_PAGE]
        return ok(
            {
                "items": [_event_body(e) for e in rows],
                "next_cursor": f"{rows[-1].aggregate_version}:{rows[-1].ordinal}"
                if has_more and rows
                else None,
                "has_more": has_more,
                "as_of": now.isoformat(),
            },
            request,
        )


class RevisionsView(ApiView):
    """API-026: immutable accepted submission revisions visible by scope."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        _, queryset = _scoped(principal, now)
        application = queryset.filter(pk=application_id).first()
        if application is None:
            raise ResourceNotFound("Application not found")
        revisions = (
            SubmissionRevision.objects.filter(application=application)
            .select_related("policy_version")
            .prefetch_related("documents")
            .order_by("number")
        )
        return ok(
            {
                "items": [
                    {
                        "number": r.number,
                        "accepted_at": r.accepted_at.isoformat(),
                        "policy_version_id": str(r.policy_version_id),
                        "policy_number": r.policy_version.number,
                        "schema_ref": r.schema_ref,
                        "sha256": r.sha256,
                        "fields": r.payload.get("fields", {}),
                        "premise_snapshot": r.premise_snapshot,
                        "declarations": r.declaration_snapshot,
                        "documents": [
                            {
                                "requirement_code": d.requirement_code,
                                "document_version_id": str(d.document_version_id),
                            }
                            for d in r.documents.all()
                        ],
                    }
                    for r in revisions
                ],
                "next_cursor": None,
                "has_more": False,
            },
            request,
        )


class OverviewView(ApiView):
    """UI-09: role-specific counts from the same scoped population as the list, one cutoff."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot, queryset = _scoped(principal, now)
        as_of = now
        by_status = {
            row["status"]: row["n"] for row in queryset.values("status").annotate(n=Count("id"))
        }
        open_statuses = [
            s.value
            for s in ApplicationStatus
            if s.value not in ("COMPLETED", "REJECTED", "WITHDRAWN", "DRAFT")
        ]
        body: dict[str, Any] = {
            "as_of": as_of.isoformat(),
            "role": "applicant" if snapshot.kind == PrincipalKind.APPLICANT else "staff",
            "counts": {
                "drafts": by_status.get("DRAFT", 0),
                "open": sum(by_status.get(s, 0) for s in open_statuses),
                "action_required": by_status.get("INFO_REQUIRED", 0)
                + by_status.get("COMPLIANCE_PENDING", 0),
                "review_waiting": by_status.get("REVIEW_PENDING", 0),
                "received": sum(v for k, v in by_status.items() if k != "DRAFT"),
                "by_status": by_status,
            },
        }
        if snapshot.kind != PrincipalKind.APPLICANT:
            active = Obligation.objects.filter(
                application__in=queryset.values("pk"), state=ObligationState.ACTIVE
            )
            soon = as_of + timedelta(hours=24)
            body["counts"]["due_soon"] = active.filter(due_at__gt=as_of, due_at__lte=soon).count()
            body["counts"]["overdue"] = active.filter(due_at__lte=as_of).count()
            body["counts"]["routing_exceptions"] = RoutingException.objects.filter(
                application__in=queryset.values("pk"), state=RoutingExceptionState.OPEN
            ).count()
            body["priority"] = [
                {
                    "application_id": str(o.application_id),
                    "public_reference": o.application.public_reference if o.application else None,
                    "kind": o.kind,
                    "due_at": o.due_at.isoformat() if o.due_at else None,
                    "owner_queue": o.owner_queue.queue_key,
                }
                for o in active.select_related("application", "owner_queue").order_by("due_at")[:10]
            ]
        body["latest_events"] = [
            {
                **_event_body(e),
                "application_id": str(e.application_id),
                "public_reference": e.application.public_reference,
            }
            for e in CaseEvent.objects.filter(
                application__in=queryset.values("pk"), audience__in=_audiences(snapshot)
            )
            .select_related("application")
            .order_by("-occurred_at", "-aggregate_version", "-ordinal")[:10]
        ]
        return ok(body, request)
