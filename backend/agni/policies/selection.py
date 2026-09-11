"""Choosing and pinning a policy (workflow s.7) and applicability evaluation (FR-03).

Exactly one approved effective version must match the service, jurisdiction and legally relevant
instant. Zero matches -> POLICY_UNAVAILABLE; more than one -> POLICY_AMBIGUOUS. Callers that pin
(submission, activation) must hold the service activation fence; `lock_service_fence` does that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from agni.platform.errors import PolicyAmbiguous, PolicyIntervalOverlap, PolicyUnavailable

from .domain.schema import required_documents
from .models import EFFECTIVE_POLICY_STATES, PolicyArtifact, PolicyState, PolicyVersion, Service


def lock_service_fence(service_id: UUID) -> Service:
    return Service.objects.select_for_update().get(pk=service_id)


def effective_versions(
    service_id: UUID, jurisdiction_id: UUID | None, at: datetime
) -> QuerySet[PolicyVersion]:
    scope = Q(jurisdiction_id=jurisdiction_id) if jurisdiction_id else Q(jurisdiction__isnull=True)
    return (
        PolicyVersion.objects.filter(
            service_id=service_id, state__in=[PolicyState.ACTIVE, PolicyState.SCHEDULED]
        )
        .filter(scope)
        .filter(effective_from__lte=at)
        .filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
        .order_by("number")
    )


def select_policy(service_id: UUID, jurisdiction_id: UUID | None, at: datetime) -> PolicyVersion:
    """One approved, effective version for the instant - or an explicit error, never a guess."""
    matches = list(effective_versions(service_id, jurisdiction_id, at))
    if not matches:
        raise PolicyUnavailable("No approved policy is effective for this service at this time")
    if len(matches) > 1:
        raise PolicyAmbiguous(
            "More than one policy is effective; policy owner must resolve",
            extensions={"policy_version_ids": [str(m.pk) for m in matches]},
        )
    return matches[0]


def check_no_overlap(
    service_id: UUID,
    jurisdiction_id: UUID | None,
    effective_from: datetime,
    effective_until: datetime | None,
    *,
    exclude_id: UUID | None = None,
) -> None:
    """Reject an interval that intersects another approved/scheduled/active version of the same
    service+jurisdiction partition (half-open intervals)."""
    scope = Q(jurisdiction_id=jurisdiction_id) if jurisdiction_id else Q(jurisdiction__isnull=True)
    candidates = PolicyVersion.objects.filter(
        service_id=service_id, state__in=list(EFFECTIVE_POLICY_STATES)
    ).filter(scope)
    if exclude_id:
        candidates = candidates.exclude(pk=exclude_id)
    # other.from < new.until (or new open) AND (other.until is null OR other.until > new.from)
    if effective_until is not None:
        candidates = candidates.filter(effective_from__lt=effective_until)
    candidates = candidates.filter(
        Q(effective_until__isnull=True) | Q(effective_until__gt=effective_from)
    )
    clash = candidates.first()
    if clash is not None:
        raise PolicyIntervalOverlap(
            "The effective interval overlaps an approved version",
            extensions={
                "conflicting_policy_version_id": str(clash.pk),
                "conflicting_number": clash.number,
            },
        )


@dataclass(frozen=True)
class Applicability:
    applicable: bool
    explanation: str
    policy_version_id: UUID | None = None
    policy_number: int | None = None
    payload_sha256: str | None = None
    form_schema_ref: str | None = None
    checklist_ref: str | None = None
    required_documents: tuple[str, ...] = ()
    inspection_required: bool | None = None
    allowed_categories: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "applicable": self.applicable,
            "explanation": self.explanation,
            "policy_version_id": str(self.policy_version_id) if self.policy_version_id else None,
            "policy_number": self.policy_number,
            "payload_sha256": self.payload_sha256,
            "form_schema_ref": self.form_schema_ref,
            "checklist_ref": self.checklist_ref,
            "required_documents": list(self.required_documents),
            "inspection_required": self.inspection_required,
            "allowed_categories": list(self.allowed_categories),
            "binding": False,
        }


def artifact_ref(kind: str, key: str) -> str | None:
    artifact = PolicyArtifact.objects.filter(kind=kind, key=key).order_by("-number").first()
    return artifact.reference if artifact else None


def evaluate_applicability(
    service: Service, *, jurisdiction_id: UUID | None, category_key: str, at: datetime
) -> Applicability:
    """Nonbinding preview of the applicable form and evidence list (API-019). Unsupported
    categories return uncertainty, never an invented determination."""
    if not service.active:
        return Applicability(False, "This service is not currently accepting applications.")
    try:
        version = select_policy(service.pk, jurisdiction_id, at)
    except PolicyUnavailable:
        return Applicability(
            False, "No approved policy is effective for this service and jurisdiction."
        )
    except PolicyAmbiguous:
        return Applicability(
            False,
            "Policy configuration needs review by the policy owner before applications "
            "can proceed.",
        )
    payload = version.payload
    allowed = tuple(str(c) for c in payload.get("allowed_categories", []))
    # Category keys are matched case-insensitively against the policy's canonical spelling;
    # the canonical key drives the document list.
    canonical = next((c for c in allowed if c.casefold() == str(category_key).casefold()), None)
    if canonical is None:
        return Applicability(
            False,
            "This premises category is not covered by the current policy; contact the "
            "service desk for guidance.",
            policy_version_id=version.pk,
            policy_number=version.number,
            payload_sha256=version.payload_sha256,
            allowed_categories=allowed,
        )
    return Applicability(
        True,
        f"Policy version {version.number} applies; requirements shown are a preview and are "
        "revalidated at submission.",
        policy_version_id=version.pk,
        policy_number=version.number,
        payload_sha256=version.payload_sha256,
        form_schema_ref=artifact_ref("FORM", str(payload["form_schema_key"])),
        checklist_ref=artifact_ref("CHECKLIST", str(payload["checklist_key"])),
        required_documents=tuple(required_documents(payload, canonical)),
        inspection_required=bool(payload.get("inspection_required")),
        allowed_categories=allowed,
    )
