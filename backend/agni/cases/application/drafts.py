"""Draft autosave and document linking commands (FR-04 API-023, FR-05 API-037).

Every save is a new append-only `DraftRevision`; the client sends the revision it edited and
the application's If-Match. A stale second tab receives VERSION_CONFLICT with the current
numbers instead of overwriting newer values. Saving never changes the case state and never
creates a receipt or clock (a draft is not a received case)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    Forbidden,
    InvalidTransition,
    ResourceNotFound,
    ValidationFailed,
    VersionConflict,
    Violation,
)

from ..domain.drafts import (
    DEMO_DECLARATIONS,
    draft_blockers,
    evaluate_requirements,
    validate_declarations,
    validate_draft_fields,
)
from ..domain.states import ApplicationStatus
from ..models import Application, DraftRevision
from .access import editable_draft_for_actor

PATCH_KEYS = frozenset(
    {"draft_revision", "form_schema_key", "fields", "declaration_drafts", "attachment_links"}
)


def draft_projection(application: Application, at: Any) -> dict[str, Any]:
    """Canonical draft view shared by commands and the detail endpoint."""
    from agni.documents.application.commands import document_body
    from agni.documents.models import DocumentVersion

    revision = application.current_draft_revision
    payload = dict(revision.editable_payload) if revision else {}
    fields = dict(payload.get("fields", {}))
    declarations = list(payload.get("declaration_drafts", []))
    links = [str(x) for x in payload.get("attachment_links", [])]
    documents = list(DocumentVersion.objects.filter(application=application).order_by("created_at"))
    requirements = evaluate_requirements(application, at, documents=documents, links=links)
    blockers = draft_blockers(fields, declarations, requirements)
    return {
        "draft_revision": revision.revision_number if revision else 0,
        "form_schema_ref": revision.form_schema_ref if revision else "",
        "saved_at": revision.saved_at.isoformat() if revision else None,
        "fields": fields,
        "declaration_drafts": declarations,
        "declarations": [{"code": c, "version": v, "text": t} for c, v, t in DEMO_DECLARATIONS],
        "attachment_links": links,
        "documents": [document_body(d) for d in documents],
        "requirements": [
            {
                "code": r.code,
                "label": r.label,
                "required": r.required,
                "status": r.status,
                "document_version_id": r.document_version_id,
            }
            for r in requirements
        ],
        "blockers": blockers,
    }


def _save_revision(
    uow: UnitOfWork, application: Application, payload: dict[str, Any], changed: list[str]
) -> CommandOutcome[Application]:
    current = application.current_draft_revision
    number = (current.revision_number if current else 0) + 1
    revision = DraftRevision.objects.create(
        application=application,
        revision_number=number,
        editable_payload=payload,
        form_schema_ref=current.form_schema_ref if current else "",
        form_schema_artifact=current.form_schema_artifact if current else None,
        saved_by=uow.actor,
        saved_at=uow.now,
    )
    application.current_draft_revision = revision
    application.save(update_fields=["current_draft_revision", "updated_at"])
    body = {
        "application_id": str(application.pk),
        "draft_reference": application.draft_reference,
        "status": application.status,
        **draft_projection(application, uow.now),
    }
    return CommandOutcome(
        status=200,
        body=body,
        aggregate=application,
        audits=[
            AuditEntry(
                "application",
                application.pk,
                "application.draft_saved",
                {"draft_revision": number, "changed": changed[:40]},
            )
        ],
    )


class PatchDraft(CommandHandler[Application]):
    """API-023."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != "APPLICANT":
            raise Forbidden("Only applicant accounts edit drafts")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = editable_draft_for_actor(
            uow.actor, uow.envelope.target_id, uow.now, lock=True
        )
        if application is None:
            raise ResourceNotFound("Application not found")
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:  # lock_target always returns or raises; defensive for the Protocol
            raise ResourceNotFound("Application not found")
        if target.status != ApplicationStatus.DRAFT.value:
            raise InvalidTransition("Only a DRAFT application can be edited")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - PATCH_KEYS)
        ]
        current = target.current_draft_revision
        current_number = current.revision_number if current else 0
        expected = data.get("draft_revision")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValidationFailed(
                violations=[
                    *violations,
                    Violation("/draft_revision", "invalid", "must be a non-negative integer"),
                ]
            )
        if expected != current_number:
            raise VersionConflict(
                "The draft was saved elsewhere since you loaded it",
                extensions={
                    "current_version": target.version,
                    "current_draft_revision": current_number,
                    "current_fields": dict((current.editable_payload or {}).get("fields", {}))
                    if current
                    else {},
                },
            )
        payload = dict(current.editable_payload) if current else {}
        changed: list[str] = []

        if "fields" in data:
            if not isinstance(data["fields"], dict):
                raise ValidationFailed(
                    violations=[*violations, Violation("/fields", "invalid", "must be an object")]
                )
            cleaned, field_violations = validate_draft_fields(data["fields"])
            violations.extend(field_violations)
            merged = dict(payload.get("fields", {}))
            for key, value in data["fields"].items():
                if value is None:
                    merged.pop(key, None)
                    changed.append(key)
                elif key in cleaned:
                    if merged.get(key) != cleaned[key]:
                        changed.append(key)
                    merged[key] = cleaned[key]
            payload["fields"] = merged
        if "declaration_drafts" in data:
            declarations, decl_violations = validate_declarations(data["declaration_drafts"])
            violations.extend(decl_violations)
            payload["declaration_drafts"] = declarations
            changed.append("declaration_drafts")
        if "attachment_links" in data:
            links, link_violations = self._validate_links(target, data["attachment_links"])
            violations.extend(link_violations)
            payload["attachment_links"] = links
            changed.append("attachment_links")
        if "form_schema_key" in data and current is not None:
            pinned = current.form_schema_ref.split("#", 1)[0]
            if pinned and str(data["form_schema_key"]) != pinned:
                violations.append(
                    Violation("/form_schema_key", "pinned", f"draft is pinned to {pinned}")
                )
        if violations:
            raise ValidationFailed(violations=violations)
        return _save_revision(uow, target, payload, changed)

    @staticmethod
    def _validate_links(target: Application, raw: Any) -> tuple[list[str], list[Violation]]:
        from agni.documents.models import DocumentVersion, ScanState

        violations: list[Violation] = []
        if not isinstance(raw, list):
            return [], [Violation("/attachment_links", "invalid", "must be a list of ids")]
        ids: list[UUID] = []
        for index, value in enumerate(raw):
            try:
                ids.append(UUID(str(value)))
            except ValueError:
                violations.append(
                    Violation(f"/attachment_links/{index}", "invalid", "must be a UUID")
                )
        if violations:
            return [], violations
        found = {d.pk: d for d in DocumentVersion.objects.filter(pk__in=ids, application=target)}
        links: list[str] = []
        for index, doc_id in enumerate(ids):
            doc = found.get(doc_id)
            if doc is None:
                violations.append(
                    Violation(f"/attachment_links/{index}", "not_found", "not a file of this draft")
                )
            elif doc.scan_state == ScanState.REJECTED:
                violations.append(
                    Violation(
                        f"/attachment_links/{index}",
                        "rejected",
                        "rejected files cannot be attached",
                    )
                )
            elif str(doc_id) not in links:
                links.append(str(doc_id))
        return links, violations


class DetachDraftDocument(CommandHandler[Application]):
    """API-037: remove a document reference from the draft (new revision). The version and its
    bytes remain; nothing is destroyed."""

    def authorize(self, uow: UnitOfWork) -> None:
        if uow.actor.kind != "APPLICANT":
            raise Forbidden("Only applicant accounts edit drafts")

    def lock_target(self, uow: UnitOfWork) -> Application | None:
        application = editable_draft_for_actor(
            uow.actor, uow.envelope.target_id, uow.now, lock=True
        )
        if application is None:
            raise ResourceNotFound("Application not found")
        return application

    def apply(self, uow: UnitOfWork, target: Application | None) -> CommandOutcome[Application]:
        if target is None:  # lock_target always returns or raises; defensive for the Protocol
            raise ResourceNotFound("Application not found")
        if target.status != ApplicationStatus.DRAFT.value:
            raise InvalidTransition("Only a DRAFT application can be edited")
        data = dict(uow.envelope.payload)
        violations: list[Violation] = [
            Violation(f"/{k}", "unknown_field", "unknown field")
            for k in sorted(set(data) - {"document_version_id", "reason"})
        ]
        reason = data.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 4000):
            violations.append(Violation("/reason", "length", "at most 4000 characters"))
        try:
            doc_id = str(UUID(str(data.get("document_version_id"))))
        except ValueError:
            violations.append(Violation("/document_version_id", "invalid", "must be a UUID"))
            doc_id = ""
        if violations:
            raise ValidationFailed(violations=violations)
        current = target.current_draft_revision
        payload = dict(current.editable_payload) if current else {}
        links = [str(x) for x in payload.get("attachment_links", [])]
        if doc_id not in links:
            raise ResourceNotFound("Document is not attached to this draft")
        payload["attachment_links"] = [x for x in links if x != doc_id]
        return _save_revision(uow, target, payload, ["attachment_links"])
