"""Pure notice rules (FR-15..FR-17; docs/24 NoticeItemInput). No persistence, no HTTP."""

from __future__ import annotations

import re
from typing import Any

from agni.platform.errors import Violation

# Approved (synthetic, demo) evidence type codes an item may ask for. Not a legal taxonomy.
EVIDENCE_TYPES: tuple[str, ...] = (
    "DOCUMENT",
    "PHOTOGRAPH",
    "TEST_CERTIFICATE",
    "INVOICE_OR_RECEIPT",
    "WRITTEN_EXPLANATION",
)
ITEM_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,39}$")


def validate_items(
    raw: Any, *, deficiency: bool, known_findings: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[Violation]]:
    """Shape rules for `items`; deficiency items must point at an open finding of this case,
    information items must not carry a finding."""
    violations: list[Violation] = []
    if not isinstance(raw, list) or not raw:
        return [], [Violation("/items", "required", "at least one item is required")]
    codes: set[str] = set()
    findings_used: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        pointer = f"/items/{index}"
        if not isinstance(item, dict):
            violations.append(Violation(pointer, "invalid", "must be an object"))
            continue
        code = item.get("code")
        if not isinstance(code, str) or not ITEM_CODE.match(code):
            violations.append(
                Violation(f"{pointer}/code", "format", "uppercase code, 2 to 40 characters")
            )
            code = ""
        elif code in codes:
            violations.append(Violation(f"{pointer}/code", "duplicate", "item code repeated"))
        codes.add(code)
        title = item.get("title")
        if not isinstance(title, str) or not (5 <= len(title.strip()) <= 200):
            violations.append(Violation(f"{pointer}/title", "length", "5 to 200 characters"))
        description = item.get("description")
        if not isinstance(description, str) or not (10 <= len(description.strip()) <= 4000):
            violations.append(
                Violation(f"{pointer}/description", "length", "10 to 4000 characters")
            )
        required = item.get("required", True)
        if not isinstance(required, bool):
            violations.append(Violation(f"{pointer}/required", "invalid", "true or false"))
        types = item.get("acceptable_evidence_types")
        if (
            not isinstance(types, list)
            or not types
            or any(t not in EVIDENCE_TYPES for t in types)
            or len(set(types)) != len(types)
        ):
            violations.append(
                Violation(
                    f"{pointer}/acceptable_evidence_types",
                    "allowlist",
                    f"non-empty unique codes from {', '.join(EVIDENCE_TYPES)}",
                )
            )
        guidance = item.get("public_guidance", "") or ""
        if not isinstance(guidance, str) or len(guidance) > 2000:
            violations.append(
                Violation(f"{pointer}/public_guidance", "length", "at most 2000 characters")
            )
        finding_id = item.get("finding_id")
        if deficiency:
            if not isinstance(finding_id, str) or finding_id not in known_findings:
                violations.append(
                    Violation(
                        f"{pointer}/finding_id",
                        "unknown_finding",
                        "must reference an open finding of this case",
                    )
                )
            elif finding_id in findings_used:
                violations.append(
                    Violation(f"{pointer}/finding_id", "duplicate", "finding already itemised")
                )
            else:
                findings_used.add(finding_id)
        elif finding_id is not None:
            violations.append(
                Violation(
                    f"{pointer}/finding_id",
                    "not_allowed",
                    "information requests concern completeness, not findings",
                )
            )
        cleaned.append(
            {
                "code": code,
                "title": str(title).strip() if isinstance(title, str) else "",
                "description": str(description).strip() if isinstance(description, str) else "",
                "required": bool(required) if isinstance(required, bool) else True,
                "acceptable_evidence_types": list(types) if isinstance(types, list) else [],
                "public_guidance": guidance.strip() if isinstance(guidance, str) else "",
                "finding_id": finding_id if deficiency else None,
            }
        )
    return cleaned, violations


def pending_required_items(items: list[Any]) -> list[str]:
    """Codes of required items that are not yet ACCEPTED (TR-04 guard)."""
    return [i.code for i in items if i.required and i.state != "ACCEPTED"]


def open_mandatory_findings(findings: list[Any]) -> list[str]:
    """Item codes of MANDATORY findings not VERIFIED_CLOSED (TR-08 guard)."""
    return [
        f.checklist_item_code
        for f in findings
        if f.severity == "MANDATORY" and f.state != "VERIFIED_CLOSED"
    ]


def reinspection_outstanding(findings: list[Any]) -> list[str]:
    return [
        f.checklist_item_code
        for f in findings
        if f.reinspection_required and f.state != "VERIFIED_CLOSED"
    ]
