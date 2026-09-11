"""Draft field rules, demo declarations and evidence requirement evaluation (docs/24 s.2-3,
FR-04/FR-05). Pure functions over canonical data; the frontend renders these results and never
keeps its own list of mandatory documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agni.platform.errors import Violation
from agni.policies.selection import evaluate_applicability

from ..application.commands import validate_premises_fields
from ..models import Application

APPLICATION_TYPES = ("NEW", "RENEWAL")
PREMISES_FIELDS = (
    "display_name",
    "address_line1",
    "address_line2",
    "locality",
    "ward_key",
    "postal_code",
    "category_key",
    "area_sqm",
    "height_m",
    "floor_count",
    "occupancy_count",
)
DRAFT_FIELDS = frozenset(
    {*PREMISES_FIELDS, "beneficiary_name", "application_type", "prior_certificate_reference"}
)

# Demonstration declarations (docs/24 s.2: individually labelled, never prechecked; the exact
# code/version/text is snapshotted at submission). Not legal text.
DEMO_DECLARATIONS: tuple[tuple[str, str, str], ...] = (
    ("D01", "1", "I declare that the information provided is true and complete to my knowledge."),
    ("D02", "1", "I am the owner of these premises or an authorised representative of the owner."),
    (
        "D03",
        "1",
        "I understand this is a demonstration service and its outcome has no legal effect.",
    ),
)
DECLARATION_CODES = frozenset(code for code, _, _ in DEMO_DECLARATIONS)

REQUIREMENT_LABELS = {
    "ownership": "Premises authorization",
    "plan": "Fire-safety layout",
    "electrical": "Electrical inspection record",
    "evacuation": "Evacuation plan",
    "occupancy": "Occupancy/capacity statement",
}


def validate_draft_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[Violation]]:
    """Validate the fields present (autosave may be partial). Returns (cleaned, violations)."""
    violations: list[Violation] = [
        Violation(f"/fields/{k}", "unknown_field", "unknown field")
        for k in sorted(set(fields) - DRAFT_FIELDS)
    ]
    cleaned: dict[str, Any] = {}
    premises_part = {k: v for k, v in fields.items() if k in PREMISES_FIELDS and v is not None}
    if premises_part:
        # Reuse the premises rules, but only for the keys actually present.
        probe = {**_PREMISES_PROBE, **premises_part}
        try:
            validated = validate_premises_fields(probe)
        except Exception as exc:  # ValidationFailed carries pointers relative to the payload
            from agni.platform.errors import ValidationFailed

            if isinstance(exc, ValidationFailed):
                violations.extend(
                    Violation(f"/fields{v.pointer}", v.code, v.message)
                    for v in exc.violations
                    if v.pointer.lstrip("/") in premises_part
                )
                validated = {}
            else:
                raise
        for key in premises_part:
            if key in validated:
                value = validated[key]
                cleaned[key] = str(value) if key in ("area_sqm", "height_m") else value
    name = fields.get("beneficiary_name")
    if name is not None:
        if not isinstance(name, str) or not (2 <= len(name.strip()) <= 160):
            violations.append(
                Violation("/fields/beneficiary_name", "length", "2 to 160 characters")
            )
        else:
            cleaned["beneficiary_name"] = name.strip()
    app_type = fields.get("application_type")
    if app_type is not None:
        if app_type not in APPLICATION_TYPES:
            violations.append(Violation("/fields/application_type", "invalid", "NEW or RENEWAL"))
        else:
            cleaned["application_type"] = app_type
    prior = fields.get("prior_certificate_reference")
    if prior is not None:
        if not isinstance(prior, str) or len(prior.strip()) > 40:
            violations.append(
                Violation("/fields/prior_certificate_reference", "length", "at most 40 characters")
            )
        else:
            cleaned["prior_certificate_reference"] = prior.strip()
    return cleaned, violations


_PREMISES_PROBE: dict[str, Any] = {
    "display_name": "probe",
    "address_line1": "probe address",
    "locality": "probe",
    "ward_key": "W-00",
    "postal_code": "000000",
    "category_key": "probe",
    "area_sqm": "1.00",
    "height_m": "1.00",
    "floor_count": 1,
}


def validate_declarations(items: Any) -> tuple[list[dict[str, Any]], list[Violation]]:
    violations: list[Violation] = []
    cleaned: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return [], [Violation("/declaration_drafts", "invalid", "must be a list")]
    seen: set[str] = set()
    for index, item in enumerate(items):
        pointer = f"/declaration_drafts/{index}"
        if not isinstance(item, dict):
            violations.append(Violation(pointer, "invalid", "must be an object"))
            continue
        code, version, accepted = item.get("code"), item.get("version"), item.get("accepted")
        if code not in DECLARATION_CODES:
            violations.append(Violation(f"{pointer}/code", "unknown", "unknown declaration"))
            continue
        if str(version) != next(v for c, v, _ in DEMO_DECLARATIONS if c == code):
            violations.append(
                Violation(f"{pointer}/version", "stale", "declaration version changed")
            )
            continue
        if not isinstance(accepted, bool):
            violations.append(Violation(f"{pointer}/accepted", "invalid", "must be true or false"))
            continue
        if code in seen:
            violations.append(Violation(f"{pointer}/code", "duplicate", "declaration repeated"))
            continue
        seen.add(str(code))
        cleaned.append({"code": code, "version": str(version), "accepted": accepted})
    return cleaned, violations


@dataclass(frozen=True)
class Requirement:
    code: str
    label: str
    required: bool
    status: str  # MISSING | PENDING_SCAN | REJECTED | SATISFIED
    document_version_id: str | None


def requirement_codes_for(application: Application, at: datetime) -> set[str]:
    """Codes an upload may target: the policy's documents for the declared category (or the
    premises category until the draft says otherwise) plus the optional sample statement."""
    codes = {r.code for r in evaluate_requirements(application, at, documents=[], links=[])}
    return codes | {"occupancy"}


def evaluate_requirements(
    application: Application,
    at: datetime,
    *,
    documents: list[Any],
    links: list[str],
) -> list[Requirement]:
    """Requirements from the policy effective now, matched against linked document versions.
    Only a CLEAN linked version satisfies a slot (FR-05)."""
    fields = current_fields(application)
    category = str(fields.get("category_key") or application.premises.category_key)
    applicability = evaluate_applicability(
        application.service,
        jurisdiction_id=application.service.owner_queue.jurisdiction_id,
        category_key=category,
        at=at,
    )
    linked = [d for d in documents if str(d.pk) in set(links)]
    by_code: dict[str, list[Any]] = {}
    for doc in linked:
        by_code.setdefault(doc.requirement_code, []).append(doc)
    required_codes = list(applicability.required_documents)
    rows: list[Requirement] = []
    for code in [*required_codes, *(c for c in by_code if c not in required_codes)]:
        docs = sorted(by_code.get(code, []), key=lambda d: d.created_at, reverse=True)
        status, chosen = "MISSING", None
        for doc in docs:
            if doc.scan_state == "CLEAN":
                status, chosen = "SATISFIED", doc
                break
        if status == "MISSING" and docs:
            newest = docs[0]
            status = "PENDING_SCAN" if newest.scan_state == "QUARANTINED" else "REJECTED"
            chosen = newest
        rows.append(
            Requirement(
                code=code,
                label=REQUIREMENT_LABELS.get(code, code),
                required=code in required_codes,
                status=status,
                document_version_id=str(chosen.pk) if chosen else None,
            )
        )
    return rows


def current_fields(application: Application) -> dict[str, Any]:
    revision = application.current_draft_revision
    if revision is None:
        return {}
    payload = revision.editable_payload or {}
    fields = payload.get("fields", {})
    return dict(fields) if isinstance(fields, dict) else {}


def draft_blockers(
    fields: dict[str, Any], declarations: list[dict[str, Any]], requirements: list[Requirement]
) -> list[dict[str, str]]:
    """Why the draft cannot be submitted yet (UI hints; B06 revalidates on submit)."""
    blockers: list[dict[str, str]] = []
    for key in (
        "display_name",
        "address_line1",
        "locality",
        "ward_key",
        "postal_code",
        "category_key",
        "area_sqm",
        "height_m",
        "floor_count",
    ):
        if key not in fields or fields[key] in ("", None):
            blockers.append({"code": "FIELD_MISSING", "pointer": f"/fields/{key}"})
    if fields.get("application_type") == "RENEWAL" and not fields.get(
        "prior_certificate_reference"
    ):
        blockers.append({"code": "FIELD_MISSING", "pointer": "/fields/prior_certificate_reference"})
    accepted = {d["code"] for d in declarations if d.get("accepted") is True}
    for code in sorted(DECLARATION_CODES - accepted):
        blockers.append({"code": "DECLARATION_MISSING", "pointer": f"/declaration_drafts/{code}"})
    for req in requirements:
        if req.required and req.status != "SATISFIED":
            blockers.append(
                {"code": f"EVIDENCE_{req.status}", "pointer": f"/document_version_ids/{req.code}"}
            )
    return blockers
