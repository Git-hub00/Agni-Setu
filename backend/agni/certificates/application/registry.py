"""Registry projections and the effective-status rule (FR-22; integrations s.7).

Status precedence for display: REVOKED and SUPERSEDED are final administrative states; an
expired validity interval shows EXPIRED even while the administrative state is ACTIVE or
SUSPENDED (a suspension never establishes valid current service after expiry); otherwise the
recorded state stands. Nothing here resurrects a record."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..adapters import DEMO_ISSUER, WATERMARK
from ..models import Certificate, IssuanceRequest, RecordedStatus

EFFECTIVE_STATUSES = ("ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED", "SUPERSEDED")


def effective_status(certificate: Certificate, now: datetime) -> str:
    recorded = str(certificate.recorded_status)
    if recorded in (RecordedStatus.REVOKED, RecordedStatus.SUPERSEDED):
        return recorded
    if certificate.valid_until is not None and certificate.valid_until <= now:
        return "EXPIRED"
    return recorded


def public_projection(certificate: Certificate, now: datetime) -> dict[str, Any]:
    """The approved public subset only (API s.7 'Public Verification'): no applicant contacts,
    no private case ids, no evidence references."""
    premises = certificate.application.premises
    body: dict[str, Any] = {
        "certificate_number": certificate.certificate_number,
        "effective_status": effective_status(certificate, now),
        "premises_display_name": premises.display_name,
        "locality": premises.locality,
        "issued_at": certificate.issued_at.isoformat(),
        "valid_until": certificate.valid_until.isoformat() if certificate.valid_until else None,
        "issuer_label": certificate.issuer_reference,
        "source": "REGISTRY",
        "checked_at": now.isoformat(),
        "is_demo": certificate.is_demo,
    }
    if certificate.is_demo:
        body["notice"] = WATERMARK
    return body


def certificate_summary(certificate: Certificate, now: datetime) -> dict[str, Any]:
    application = certificate.application
    premises = application.premises
    return {
        "certificate_id": str(certificate.pk),
        "certificate_number": certificate.certificate_number,
        "application_id": str(application.pk),
        "public_reference": application.public_reference,
        "premises": {
            "display_name": premises.display_name,
            "locality": premises.locality,
            "category_key": premises.category_key,
        },
        "outcome_kind": certificate.outcome_kind,
        "recorded_status": certificate.recorded_status,
        "effective_status": effective_status(certificate, now),
        "issued_at": certificate.issued_at.isoformat(),
        "valid_until": certificate.valid_until.isoformat() if certificate.valid_until else None,
        "issuer_label": certificate.issuer_reference,
        "is_demo": certificate.is_demo,
        "artifact_available": certificate.artifact_id is not None,
        "version": certificate.version,
        "updated_at": certificate.updated_at.isoformat(),
    }


def certificate_detail(certificate: Certificate, now: datetime, *, staff: bool) -> dict[str, Any]:
    request: IssuanceRequest | None = certificate.issuance_request
    artifact = certificate.artifact
    body = certificate_summary(certificate, now)
    body.update(
        {
            "predecessor_id": str(certificate.predecessor_id)
            if certificate.predecessor_id
            else None,
            "successor_ids": [
                str(pk) for pk in certificate.successors.values_list("pk", flat=True)
            ],
            "artifact": (
                {
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "media_type": artifact.media_type,
                    "mode": artifact.mode,
                    "renderer": artifact.renderer,
                    "rendered_at": artifact.rendered_at.isoformat(),
                }
                if artifact is not None
                else None
            ),
            "issuance": (
                {
                    "issuance_request_id": str(request.pk),
                    "state": request.state,
                    "published_at": request.published_at.isoformat()
                    if request.published_at
                    else None,
                    "template": {"key": request.template_key, "version": request.template_version},
                    **(
                        {
                            "provider_request_id": request.provider_request_id,
                            "signature_verification": request.signature_verification,
                            "attempts": request.attempts,
                        }
                        if staff
                        else {}
                    ),
                }
                if request is not None
                else None
            ),
            "status_history": [
                {
                    "instrument_id": str(i.pk),
                    "action": i.action,
                    "effective_at": i.effective_at.isoformat(),
                    "public_reason": i.public_reason,
                    "status_before": i.status_before,
                    "status_after": i.status_after,
                    "successor_certificate_id": str(i.successor_certificate_id)
                    if i.successor_certificate_id
                    else None,
                    "recorded_at": i.created_at.isoformat(),
                    **({"reason": i.reason, "actor_id": str(i.actor_id)} if staff else {}),
                }
                for i in certificate.status_instruments.order_by("effective_at", "created_at")
            ],
            "renewals": _renewals(certificate),
            "allowed_actions": [
                {
                    "key": "download",
                    "enabled": artifact is not None,
                    "reason_code": None if artifact is not None else "ARTIFACT_UNAVAILABLE",
                },
                {"key": "copy-verification-link", "enabled": True, "reason_code": None},
                _renewal_action(certificate, now, staff=staff),
            ],
            "demo_notice": WATERMARK if certificate.is_demo else None,
            "issuer_reference": certificate.issuer_reference or DEMO_ISSUER,
        }
    )
    return body


def _renewals(certificate: Certificate) -> list[dict[str, Any]]:
    from agni.cases.models import Application

    return [
        {
            "application_id": str(a.pk),
            "draft_reference": a.draft_reference,
            "public_reference": a.public_reference,
            "status": a.status,
        }
        for a in Application.objects.filter(prior_certificate_id=certificate.pk).order_by(
            "created_at"
        )
    ]


def _renewal_action(certificate: Certificate, now: datetime, *, staff: bool) -> dict[str, Any]:
    """Holder-side renewal (API-070): permitted while the record is ACTIVE or EXPIRED and no
    renewal case is open; never for a revoked or superseded record."""
    from agni.cases.models import Application

    if staff:
        return {"key": "renewal", "enabled": False, "reason_code": "HOLDER_ONLY"}
    if certificate.recorded_status in (RecordedStatus.REVOKED, RecordedStatus.SUPERSEDED):
        return {"key": "renewal", "enabled": False, "reason_code": "NOT_RENEWABLE"}
    if (
        Application.objects.filter(prior_certificate_id=certificate.pk)
        .exclude(status__in=("COMPLETED", "REJECTED", "WITHDRAWN"))
        .exists()
    ):
        return {"key": "renewal", "enabled": False, "reason_code": "RENEWAL_IN_PROGRESS"}
    return {"key": "renewal", "enabled": True, "reason_code": None}


def pending_issuance_card(request: IssuanceRequest) -> dict[str, Any]:
    application = request.application
    premises = application.premises
    dependency = {
        "READY": "Waiting for the issuance worker",
        "PROCESSING": "Rendering, storing and signing the sample instrument",
        "RECONCILIATION_REQUIRED": (
            "The signing outcome is unknown or invalid; an operator must reconcile before retry"
        ),
        "FAILED": "Issuance failed permanently; see the job record",
        "PUBLISHED": "Published",
    }.get(str(request.state), str(request.state))
    return {
        "issuance_request_id": str(request.pk),
        "application_id": str(application.pk),
        "public_reference": application.public_reference,
        "premises": {
            "display_name": premises.display_name,
            "locality": premises.locality,
            "category_key": premises.category_key,
        },
        "certificate_number": request.certificate_number,
        "state": request.state,
        "attempts": request.attempts,
        "last_error_code": request.last_error_code,
        "dependency": dependency,
        "updated_at": request.updated_at.isoformat(),
        "is_demo": True,
    }
