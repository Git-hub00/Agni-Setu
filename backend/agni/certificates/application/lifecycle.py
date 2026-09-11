"""Certificate lifecycle (FR-24): status instruments (API-071) and linked renewals (API-070).

A status action needs a supervisor of the case jurisdiction holding the `certificate.status`
grant, a reason, a public reason and - for adverse actions - cited evidence. Admissibility comes
from the pure rules in `domain/lifecycle.py`; an expired record is never reinstated. A renewal is
a new linked DRAFT for the same premises; the source certificate is not modified."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils.dateparse import parse_datetime

from agni.cases.application.commands import (
    _create_initial_revision,
    _create_with_unique_reference,
)
from agni.cases.domain.states import ApplicationStatus
from agni.cases.models import Application, CaseEvent, EventAudience, StageInstance
from agni.documents.models import DocumentVersion, ScanState
from agni.identity.authz import AuthzSnapshot, load_snapshot, require_capability
from agni.identity.domain.roles import Capability, RoleKey
from agni.identity.models import PrincipalKind
from agni.inspections.application.commands import _case_event, _intent
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    CertificateStatusConflict,
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ServiceDisabled,
    ValidationFailed,
    Violation,
)
from agni.policies.models import Service

from ..domain.lifecycle import ACTIONS, admissible_actions, requires_evidence, status_after
from ..models import Certificate, CertificateStatusInstrument, RecordedStatus
from .registry import certificate_summary, effective_status

_TERMINAL = ("COMPLETED", "REJECTED", "WITHDRAWN")


def instrument_body(instrument: CertificateStatusInstrument) -> dict[str, Any]:
    return {
        "instrument_id": str(instrument.pk),
        "certificate_id": str(instrument.certificate_id),
        "action": instrument.action,
        "effective_at": instrument.effective_at.isoformat(),
        "public_reason": instrument.public_reason,
        "status_before": instrument.status_before,
        "status_after": instrument.status_after,
        "successor_certificate_id": str(instrument.successor_certificate_id)
        if instrument.successor_certificate_id
        else None,
        "evidence_document_id": str(instrument.evidence_id) if instrument.evidence_id else None,
        "recorded_at": instrument.created_at.isoformat(),
    }


def internal_instrument_body(instrument: CertificateStatusInstrument) -> dict[str, Any]:
    return {
        **instrument_body(instrument),
        "reason": instrument.reason,
        "actor_id": str(instrument.actor_id),
        "authority_grant_id": str(instrument.authority_grant_id),
    }


def allowed_status_actions(
    certificate: Certificate, snapshot: AuthzSnapshot, now: datetime
) -> list[dict[str, Any]]:
    """UI-17 status dialog: only policy-permitted transitions, each with its reason code."""
    jurisdiction_id = certificate.application.owner_queue.jurisdiction_id
    supervisor = snapshot.kind == PrincipalKind.STAFF and snapshot.has_role(
        RoleKey.SUPERVISOR, jurisdiction_id=jurisdiction_id
    )
    grant = snapshot.grant_for(Capability.CERTIFICATE_STATUS, jurisdiction_id=jurisdiction_id)
    admissible = admissible_actions(
        str(certificate.recorded_status), effective_status(certificate, now)
    )
    out: list[dict[str, Any]] = []
    for action in ACTIONS:
        if not supervisor:
            reason: str | None = "NOT_AUTHORIZED"
        elif grant is None:
            reason = "AUTHORITY_MISSING"
        elif action not in admissible:
            reason = "NOT_ADMISSIBLE"
        else:
            reason = None
        out.append({"action": action, "enabled": reason is None, "reason_code": reason})
    return out


def _text(data: dict[str, Any], key: str, violations: list[Violation], lo: int, hi: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not (lo <= len(value.strip()) <= hi):
        violations.append(Violation(f"/{key}", "length", f"{lo} to {hi} characters"))
        return ""
    return value.strip()


class RecordStatusAction(CommandHandler[Certificate]):
    """API-071: SUSPEND / REINSTATE / REVOKE / SUPERSEDE with reason, public reason, cited
    evidence for adverse actions and the successor for a supersession. Never resurrects an
    expired or revoked record; the instrument is append-only and the effect applied under the
    certificate lock."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.STAFF:
            raise Forbidden("Only staff record certificate status actions")

    def lock_target(self, uow: UnitOfWork) -> Certificate | None:
        certificate = (
            Certificate.objects.select_for_update(of=("self",))
            .select_related("application__owner_queue__jurisdiction", "application__premises")
            .filter(pk=uow.envelope.target_id)
            .first()
        )
        if certificate is None:
            raise ResourceNotFound("Certificate not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        if not snapshot.has_role(
            RoleKey.SUPERVISOR,
            jurisdiction_id=certificate.application.owner_queue.jurisdiction_id,
        ):
            raise ResourceNotFound("Certificate not found")
        return certificate

    def apply(self, uow: UnitOfWork, target: Certificate | None) -> CommandOutcome[Certificate]:
        if target is None:
            raise ResourceNotFound("Certificate not found")
        snapshot = load_snapshot(uow.actor, uow.now)
        grant = require_capability(
            snapshot,
            Capability.CERTIFICATE_STATUS,
            jurisdiction_id=target.application.owner_queue.jurisdiction_id,
        )
        data = dict(uow.envelope.payload)
        allowed = {
            "action",
            "effective_at",
            "reason",
            "public_reason",
            "evidence_document_id",
            "successor_certificate_id",
        }
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - allowed)
        ]
        action = str(data.get("action") or "")
        if action not in ACTIONS:
            violations.append(
                Violation("/action", "invalid", "SUSPEND, REINSTATE, REVOKE or SUPERSEDE")
            )
        reason = _text(data, "reason", violations, 10, 4000)
        public_reason = _text(data, "public_reason", violations, 10, 4000)
        effective_at = uow.now
        if data.get("effective_at") not in (None, ""):
            parsed = parse_datetime(str(data.get("effective_at")))
            if parsed is None or parsed.tzinfo is None:
                violations.append(
                    Violation("/effective_at", "format", "must be an ISO 8601 UTC timestamp")
                )
            elif parsed > uow.now:
                violations.append(
                    Violation("/effective_at", "future", "a status action cannot be post-dated")
                )
            elif parsed < target.issued_at:
                violations.append(
                    Violation("/effective_at", "before_issue", "cannot precede the issue date")
                )
            else:
                effective_at = parsed
        evidence: DocumentVersion | None = None
        raw_evidence = data.get("evidence_document_id")
        if raw_evidence not in (None, ""):
            try:
                evidence = DocumentVersion.objects.filter(
                    pk=UUID(str(raw_evidence)),
                    application=target.application,
                    scan_state=ScanState.CLEAN,
                ).first()
            except ValueError:
                evidence = None
            if evidence is None:
                violations.append(
                    Violation(
                        "/evidence_document_id",
                        "not_clean_case_evidence",
                        "must be a CLEAN file of the certificate's case",
                    )
                )
        elif action in ACTIONS and requires_evidence(action):
            violations.append(
                Violation("/evidence_document_id", "required", f"{action} cites its basis")
            )
        successor: Certificate | None = None
        raw_successor = data.get("successor_certificate_id")
        if action == "SUPERSEDE":
            if raw_successor in (None, ""):
                violations.append(
                    Violation("/successor_certificate_id", "required", "required for SUPERSEDE")
                )
            else:
                try:
                    successor = (
                        Certificate.objects.select_for_update(of=("self",))
                        .filter(
                            pk=UUID(str(raw_successor)),
                            application__premises=target.application.premises,
                        )
                        .exclude(pk=target.pk)
                        .first()
                    )
                except ValueError:
                    successor = None
                if (
                    successor is None
                    or successor.recorded_status != RecordedStatus.ACTIVE
                    or effective_status(successor, uow.now) != "ACTIVE"
                    or successor.predecessor_id is not None
                ):
                    violations.append(
                        Violation(
                            "/successor_certificate_id",
                            "invalid",
                            "an ACTIVE, in-force certificate of the same premises without a "
                            "predecessor",
                        )
                    )
        elif raw_successor not in (None, ""):
            violations.append(
                Violation("/successor_certificate_id", "unexpected", "only for SUPERSEDE")
            )
        if violations:
            raise ValidationFailed(violations=violations)

        current_effective = effective_status(target, uow.now)
        admissible = admissible_actions(str(target.recorded_status), current_effective)
        if action not in admissible:
            raise CertificateStatusConflict(
                f"{action} is not admissible for a {current_effective} certificate",
                extensions={
                    "recorded_status": target.recorded_status,
                    "effective_status": current_effective,
                    "admissible": list(admissible),
                },
            )
        before = str(target.recorded_status)
        after = status_after(action)
        instrument = CertificateStatusInstrument.objects.create(
            certificate=target,
            action=action,
            authority_grant_id=grant.grant_id,
            actor=uow.actor,
            effective_at=effective_at,
            reason=reason,
            public_reason=public_reason,
            evidence=evidence,
            successor_certificate=successor,
            status_before=before,
            status_after=after,
        )
        target.recorded_status = after
        target.save(update_fields=["recorded_status", "updated_at"])
        if successor is not None:
            successor.predecessor = target
            successor.version += 1
            successor.save(update_fields=["predecessor", "version", "updated_at"])
        event = _case_event(
            uow,
            target.application,
            "certificate.status_changed.v1",
            {
                "certificate_id": str(target.pk),
                "certificate_number": target.certificate_number,
                "action": action,
                "effective_at": effective_at.isoformat(),
                "public_reason": public_reason,
                "status_after": after,
                "successor_certificate_number": successor.certificate_number if successor else None,
            },
            EventAudience.PUBLIC_CASE,
        )
        return CommandOutcome(
            status=201,
            body={
                "instrument": internal_instrument_body(instrument),
                "certificate": certificate_summary(target, uow.now),
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "certificate",
                    target.pk,
                    f"certificate.{action.lower()}",
                    {
                        "instrument_id": str(instrument.pk),
                        "status_before": before,
                        "status_after": after,
                        "effective_at": effective_at.isoformat(),
                        "evidence_document_id": str(evidence.pk) if evidence else None,
                        "successor_certificate_id": str(successor.pk) if successor else None,
                        "reason": reason[:200],
                    },
                    authority_grant_id=grant.grant_id,
                )
            ],
            intents=[_intent(event, uow)],
        )


class CreateRenewalDraft(CommandHandler[Application]):
    """API-070: the holder starts a linked renewal DRAFT under the rules current at submission.
    Reusable premises fields are copied into an editable draft; dates, documents and
    declarations are revalidated; the source certificate's validity is untouched."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != PrincipalKind.APPLICANT:
            raise Forbidden("Only the certificate holder starts a renewal")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        return None

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        certificate = (
            Certificate.objects.select_related(
                "application__premises", "application__service__owner_queue__jurisdiction"
            )
            .filter(pk=uow.envelope.target_id)
            .filter(Q(application__applicant=uow.actor) | Q(application__acting_operator=uow.actor))
            .first()
        )
        if certificate is None:
            raise ResourceNotFound("Certificate not found")
        data = dict(uow.envelope.payload)
        violations = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"declaration_of_current_details", "service_key"})
        ]
        declared = data.get("declaration_of_current_details")
        if not isinstance(declared, bool):
            violations.append(
                Violation("/declaration_of_current_details", "required", "true or false")
            )
        service_key = data.get("service_key")
        if service_key is not None and not isinstance(service_key, str):
            violations.append(Violation("/service_key", "invalid", "must be a string"))
        if violations:
            raise ValidationFailed(violations=violations)
        if certificate.recorded_status in (RecordedStatus.REVOKED, RecordedStatus.SUPERSEDED):
            raise InvalidTransition(
                f"A {certificate.recorded_status} certificate cannot be renewed; apply anew"
            )
        open_renewal = (
            Application.objects.filter(prior_certificate_id=certificate.pk)
            .exclude(status__in=_TERMINAL)
            .first()
        )
        if open_renewal is not None:
            raise InvalidTransition(
                "A renewal application for this certificate is already in progress",
                extensions={"application_id": str(open_renewal.pk)},
            )
        source = certificate.application
        service = source.service
        if isinstance(service_key, str) and service_key.strip():
            found = (
                Service.objects.select_related("owner_queue__jurisdiction")
                .filter(key=service_key.strip())
                .first()
            )
            if found is None:
                raise ResourceNotFound("Service not found")
            service = found
        if not service.active:
            raise ServiceDisabled("This service is not currently accepting applications")
        premises = source.premises
        now = uow.now
        application = _create_with_unique_reference(uow, premises, service, now)
        application.prior_certificate_id = certificate.pk
        application.save(update_fields=["prior_certificate_id", "updated_at"])
        _create_initial_revision(
            uow, application, premises, service, "RENEWAL", certificate.certificate_number
        )
        event = CaseEvent.objects.create(
            application=application,
            aggregate_version=application.version,
            ordinal=0,
            event_type="application.draft_created.v1",
            actor=uow.actor,
            actor_kind=uow.actor.kind,
            occurred_at=now,
            payload={
                "draft_reference": application.draft_reference,
                "service_key": service.key,
                "renewal_of": certificate.certificate_number,
                "declaration_of_current_details": declared,
            },
            audience=EventAudience.PUBLIC_CASE,
            request_id=uow.request_id,
            command_receipt_id=uow.command_id,
        )
        stage = StageInstance.objects.create(
            application=application,
            state=ApplicationStatus.DRAFT.value,
            cycle_number=1,
            entered_event=event,
            entered_at=now,
        )
        application.current_stage_instance = stage
        application.save(update_fields=["current_stage_instance", "updated_at"])
        return CommandOutcome(
            status=201,
            body={
                "application_id": str(application.pk),
                "draft_reference": application.draft_reference,
                "status": application.status,
                "application_type": "RENEWAL",
                "prior_certificate_id": str(certificate.pk),
                "prior_certificate_number": certificate.certificate_number,
                "source_valid_until": certificate.valid_until.isoformat()
                if certificate.valid_until
                else None,
                "note": (
                    "A renewal is a new application under the rules current at submission; the "
                    "source certificate's validity is not extended."
                ),
            },
            aggregate=application,
            created=True,
            audits=[
                AuditEntry(
                    "application",
                    application.pk,
                    "application.renewal_draft_created",
                    {
                        "draft_reference": application.draft_reference,
                        "prior_certificate_id": str(certificate.pk),
                        "service_key": service.key,
                    },
                )
            ],
        )
