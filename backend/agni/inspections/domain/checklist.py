"""Checklist observations and deterministic evaluation (FR-14, docs/24 s.4).

Pure functions over the pinned CHECKLIST artifact payload and the submitted observations.
Results are PASS, FAIL, NOT_VERIFIED or policy-permitted NOT_APPLICABLE. A mandatory FAIL, a
mandatory NOT_VERIFIED or an unauthorised NOT_APPLICABLE blocks eligibility for a favourable
decision; there is deliberately no numeric score that could compensate for a blocker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime

from agni.platform.errors import Violation

RESULTS = ("PASS", "FAIL", "NOT_VERIFIED", "NOT_APPLICABLE")
NOTE_REQUIRED_FOR = ("FAIL", "NOT_VERIFIED", "NOT_APPLICABLE")


@dataclass(frozen=True)
class ChecklistItem:
    code: str
    title: str
    mandatory: bool
    evidence_required: bool
    na_permitted: bool


def checklist_items(payload: dict[str, Any]) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for raw in payload.get("items", []):
        items.append(
            ChecklistItem(
                code=str(raw["code"]),
                title=str(raw.get("title", "")),
                mandatory=bool(raw.get("mandatory", False)),
                evidence_required=bool(raw.get("evidence_required", False)),
                na_permitted=bool(raw.get("na_permitted", False)),
            )
        )
    return items


def validate_observations(
    items: list[ChecklistItem], observations: Any, *, complete: bool
) -> tuple[list[dict[str, Any]], list[Violation]]:
    """Shape and rule validation. `complete=True` (submission) additionally requires every
    checklist item exactly once and forbids invented codes."""
    violations: list[Violation] = []
    if not isinstance(observations, list):
        return [], [Violation("/observations", "invalid", "must be a list")]
    known = {i.code: i for i in items}
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(observations):
        pointer = f"/observations/{index}"
        if not isinstance(raw, dict):
            violations.append(Violation(pointer, "invalid", "must be an object"))
            continue
        code = raw.get("item_code")
        item = known.get(str(code))
        if item is None:
            violations.append(Violation(f"{pointer}/item_code", "unknown", "not in this checklist"))
            continue
        if item.code in seen:
            violations.append(Violation(f"{pointer}/item_code", "duplicate", "item repeated"))
            continue
        seen.add(item.code)
        result = raw.get("result")
        if result not in RESULTS:
            violations.append(
                Violation(
                    f"{pointer}/result", "invalid", "PASS, FAIL, NOT_VERIFIED or NOT_APPLICABLE"
                )
            )
            continue
        note = raw.get("note", "")
        if note is None:
            note = ""
        if not isinstance(note, str) or len(note) > 2000:
            violations.append(Violation(f"{pointer}/note", "length", "at most 2000 characters"))
            note = ""
        elif result in NOTE_REQUIRED_FOR and len(note.strip()) < 10:
            violations.append(
                Violation(
                    f"{pointer}/note",
                    "required",
                    f"Explain the {result.lower().replace('_', ' ')} observation "
                    "(10 to 2000 characters)",
                )
            )
        if result == "NOT_APPLICABLE" and not item.na_permitted:
            violations.append(
                Violation(
                    f"{pointer}/result",
                    "na_not_permitted",
                    "this item cannot be marked not applicable",
                )
            )
        doc_ids_raw = raw.get("document_version_ids", [])
        doc_ids: list[str] = []
        if not isinstance(doc_ids_raw, list):
            violations.append(
                Violation(f"{pointer}/document_version_ids", "invalid", "must be a list")
            )
        else:
            for j, value in enumerate(doc_ids_raw):
                try:
                    doc_ids.append(str(UUID(str(value))))
                except ValueError:
                    violations.append(
                        Violation(
                            f"{pointer}/document_version_ids/{j}", "invalid", "must be a UUID"
                        )
                    )
            if len(set(doc_ids)) != len(doc_ids):
                violations.append(
                    Violation(f"{pointer}/document_version_ids", "duplicate", "ids must be unique")
                )
        captured_at = raw.get("captured_at")
        if captured_at is not None:
            parsed = parse_datetime(str(captured_at))
            if parsed is None or parsed.tzinfo is None:
                violations.append(
                    Violation(
                        f"{pointer}/captured_at", "format", "must be an ISO 8601 UTC timestamp"
                    )
                )
        location = raw.get("location")
        if location is not None:
            if not isinstance(location, dict) or not {"latitude", "longitude", "accuracy_m"} <= set(
                location
            ):
                violations.append(
                    Violation(
                        f"{pointer}/location",
                        "invalid",
                        "latitude, longitude and accuracy_m together",
                    )
                )
        cleaned.append(
            {
                "item_code": item.code,
                "result": result,
                "note": note.strip(),
                "document_version_ids": doc_ids,
                "captured_at": captured_at,
                "location": location,
            }
        )
    if complete:
        missing = [i.code for i in items if i.code not in seen]
        for code in missing:
            violations.append(
                Violation("/observations", "missing", f"observation for {code} is required")
            )
    return cleaned, violations


@dataclass(frozen=True)
class Blocker:
    code: str
    item_code: str
    message: str


@dataclass(frozen=True)
class Finding:
    item_code: str
    severity: str  # MANDATORY | ADVISORY
    result: str
    note: str


@dataclass(frozen=True)
class Evaluation:
    eligible_for_review: bool
    blockers: tuple[Blocker, ...]
    findings: tuple[Finding, ...]
    na_requiring_review: tuple[str, ...]
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible_for_review": self.eligible_for_review,
            "blockers": [
                {"code": b.code, "item_code": b.item_code, "message": b.message}
                for b in self.blockers
            ],
            "findings": [
                {
                    "item_code": f.item_code,
                    "severity": f.severity,
                    "result": f.result,
                    "note": f.note,
                }
                for f in self.findings
            ],
            "na_requiring_review": list(self.na_requiring_review),
            "counts": dict(self.counts),
            "scoring": "none - mandatory blockers cannot be compensated",
        }


def evaluate(items: list[ChecklistItem], observations: list[dict[str, Any]]) -> Evaluation:
    """Deterministic: identical inputs give identical output; ordering follows the checklist."""
    by_code = {o["item_code"]: o for o in observations}
    blockers: list[Blocker] = []
    findings: list[Finding] = []
    na_review: list[str] = []
    counts = dict.fromkeys(RESULTS, 0)
    for item in items:
        observation = by_code.get(item.code)
        if observation is None:
            if item.mandatory:
                blockers.append(
                    Blocker(
                        "MANDATORY_NOT_VERIFIED",
                        item.code,
                        f"{item.title}: no observation recorded",
                    )
                )
            continue
        result = observation["result"]
        counts[result] = counts.get(result, 0) + 1
        severity = "MANDATORY" if item.mandatory else "ADVISORY"
        if result == "FAIL":
            findings.append(Finding(item.code, severity, result, observation["note"]))
            if item.mandatory:
                blockers.append(
                    Blocker("MANDATORY_FAIL", item.code, f"{item.title}: mandatory item failed")
                )
        elif result == "NOT_VERIFIED":
            if item.mandatory:
                blockers.append(
                    Blocker(
                        "MANDATORY_NOT_VERIFIED",
                        item.code,
                        f"{item.title}: mandatory item not verified",
                    )
                )
            else:
                findings.append(Finding(item.code, severity, result, observation["note"]))
        elif result == "NOT_APPLICABLE":
            if not item.na_permitted:
                blockers.append(
                    Blocker(
                        "NA_NOT_PERMITTED",
                        item.code,
                        f"{item.title}: not applicable is not permitted",
                    )
                )
            else:
                na_review.append(item.code)  # permitted with rationale, but always reviewed
        elif (
            result == "PASS" and item.evidence_required and not observation["document_version_ids"]
        ):
            blockers.append(
                Blocker(
                    "EVIDENCE_MISSING",
                    item.code,
                    f"{item.title}: evidence is required for this item",
                )
            )
    return Evaluation(
        eligible_for_review=not blockers,
        blockers=tuple(blockers),
        findings=tuple(findings),
        na_requiring_review=tuple(na_review),
        counts=counts,
    )
