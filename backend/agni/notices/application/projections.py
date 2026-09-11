"""Read projections for notices, items, responses and findings (API-053/055/059). Applicant
projections omit internal notes and reviewer identities."""

from __future__ import annotations

from typing import Any

from ..models import Finding, Notice, NoticeItem, ResponseRevision


def response_body(r: ResponseRevision) -> dict[str, Any]:
    return {
        "response_revision_id": str(r.pk),
        "number": r.number,
        "explanation": r.explanation,
        "document_version_ids": [str(d.document_version_id) for d in r.documents.all()],
        "accepted_at": r.accepted_at.isoformat(),
        "sha256": r.sha256,
    }


def finding_body(f: Finding, *, staff: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "finding_id": str(f.pk),
        "application_id": str(f.application_id),
        "originating_report_id": str(f.originating_report_id),
        "checklist_item_code": f.checklist_item_code,
        "severity": f.severity,
        "state": f.state,
        "description": f.description,
        "reinspection_required": f.reinspection_required,
        "current_response_id": str(f.current_response_id) if f.current_response_id else None,
        "closed_at": f.closed_at.isoformat() if f.closed_at else None,
        "last_review_reason": f.last_review_reason or None,
        "version": f.version,
    }
    if staff:
        body["closed_by"] = str(f.closed_by_id) if f.closed_by_id else None
        body["closure_evidence"] = f.closure_evidence
        body["reviews"] = [
            {
                "review_id": str(r.pk),
                "outcome": r.outcome,
                "reason": r.reason,
                "response_revision_id": str(r.response_revision_id)
                if r.response_revision_id
                else None,
                "evidence_snapshot": r.evidence_snapshot,
                "accepted_at": r.accepted_at.isoformat(),
            }
            for r in f.reviews.all().order_by("created_at")
        ]
    return body


def item_body(i: NoticeItem, *, staff: bool, with_history: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {
        "notice_item_id": str(i.pk),
        "notice_id": str(i.notice_id),
        "code": i.code,
        "title": i.title,
        "description": i.description,
        "required": i.required,
        "acceptable_evidence_types": list(i.acceptable_evidence_types),
        "public_guidance": i.public_guidance or None,
        "state": i.state,
        "finding_id": str(i.finding_id) if i.finding_id else None,
        "finding_state": i.finding.state if i.finding is not None else None,
        "finding_severity": i.finding.severity if i.finding is not None else None,
        "reviewer_feedback": i.reviewer_feedback or None,
        "current_response_id": str(i.current_response_id) if i.current_response_id else None,
        "verified_at": i.verified_at.isoformat() if i.verified_at else None,
        "version": i.version,
    }
    if with_history:
        body["responses"] = [response_body(r) for r in i.responses.all().order_by("number")]
        body["reviews"] = [
            {
                "review_id": str(r.pk),
                "outcome": r.outcome,
                "reason": r.reason,
                "response_revision_id": str(r.response_revision_id)
                if r.response_revision_id
                else None,
                "accepted_at": r.accepted_at.isoformat(),
            }
            for r in i.reviews.all().order_by("created_at")
        ]
    if staff:
        body["verified_by"] = str(i.verified_by_id) if i.verified_by_id else None
    return body


def notice_body(n: Notice, *, staff: bool, with_items: bool = True) -> dict[str, Any]:
    due = n.due_obligation
    body: dict[str, Any] = {
        "notice_id": str(n.pk),
        "application_id": str(n.application_id),
        "round_number": n.round_number,
        "type": n.type,
        "state": n.state,
        "public_reason": n.public_reason,
        "published_at": n.published_at.isoformat(),
        "response_budget_minutes": n.response_budget_minutes,
        "due_at": due.due_at.isoformat() if due and due.due_at else None,
        "obligation_state": due.state if due else None,
        "supersedes_id": str(n.supersedes_id) if n.supersedes_id else None,
        "superseded_by_id": None,
        "closed_at": n.closed_at.isoformat() if n.closed_at else None,
        "version": n.version,
    }
    successor = n.superseded_by.order_by("-round_number").first()
    if successor is not None:
        body["superseded_by_id"] = str(successor.pk)
    if staff:
        body["internal_note"] = n.internal_note or None
        body["published_by"] = str(n.published_by_id)
    if with_items:
        items = list(n.items.select_related("finding").order_by("code"))
        body["items"] = [item_body(i, staff=staff) for i in items]
        body["open_items"] = sum(1 for i in items if i.state != "ACCEPTED")
        body["items_total"] = len(items)
    return body
