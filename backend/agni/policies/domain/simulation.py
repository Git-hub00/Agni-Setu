"""Deterministic policy simulation suites (workflow s.12; DTO catalogue s.10).

A suite is server-owned data + pure checks over the frozen candidate payload and its referenced
artifacts. It never touches live applications and never proves legal approval; a passed result
for the exact candidate hash is a precondition for approval, nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .schema import required_documents, validate_policy_payload

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class SimulationCheck:
    key: str
    passed: bool
    expected: str
    actual: str
    safe_explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "safe_explanation": self.safe_explanation,
        }


@dataclass(frozen=True)
class SuiteContext:
    """Artifacts resolved by the application layer so the suite stays ORM-free."""

    checklist_items: list[dict[str, Any]] = field(default_factory=list)
    calendar: Mapping[str, Any] = field(default_factory=dict)
    routing_entries: list[dict[str, Any]] = field(default_factory=list)
    form_present: bool = False


@dataclass(frozen=True)
class Suite:
    key: str
    version: str


SUITES: dict[str, Suite] = {"demo-baseline-v1": Suite("demo-baseline-v1", "1")}


def run_suite(
    suite_key: str, payload: Mapping[str, Any], context: SuiteContext
) -> tuple[bool, list[SimulationCheck]]:
    if suite_key not in SUITES:
        raise KeyError(suite_key)
    checks: list[SimulationCheck] = []

    violations = validate_policy_payload(payload)
    checks.append(
        SimulationCheck(
            "schema.valid",
            not violations,
            "0 violations",
            f"{len(violations)} violation(s)",
            "The candidate must satisfy the versioned policy schema.",
        )
    )

    checks.append(
        SimulationCheck(
            "artifacts.form_present",
            context.form_present,
            "form schema artifact resolvable",
            "present" if context.form_present else "missing",
            "The referenced form schema key/number must exist.",
        )
    )

    mandatory = [i for i in context.checklist_items if i.get("mandatory")]
    checks.append(
        SimulationCheck(
            "checklist.mandatory_items",
            len(context.checklist_items) >= 1 and len(mandatory) >= 1,
            ">=1 item and >=1 mandatory item",
            f"{len(context.checklist_items)} items, {len(mandatory)} mandatory",
            "An inspection checklist without mandatory items cannot block unsafe premises.",
        )
    )
    codes = [i.get("code") for i in context.checklist_items]
    checks.append(
        SimulationCheck(
            "checklist.unique_codes",
            len(codes) == len(set(codes)),
            "unique item codes",
            f"{len(codes)} codes, {len(set(codes))} unique",
            "Duplicate checklist codes make observations ambiguous.",
        )
    )

    hours = context.calendar.get("working_hours") if isinstance(context.calendar, Mapping) else None
    checks.append(
        SimulationCheck(
            "calendar.working_hours",
            isinstance(hours, Mapping) and bool(hours),
            "working hours defined per weekday",
            "defined" if isinstance(hours, Mapping) and hours else "missing",
            "Working-minute budgets need a working calendar.",
        )
    )

    for category in payload.get("allowed_categories", []):
        docs = required_documents(payload, str(category))
        checks.append(
            SimulationCheck(
                f"documents.{category}",
                len(docs) >= 1,
                ">=1 required document",
                f"{len(docs)} document(s): {', '.join(docs)}",
                "Every allowed category resolves to a concrete evidence list.",
            )
        )

    routed = {str(e.get("ward_key")) for e in context.routing_entries}
    checks.append(
        SimulationCheck(
            "routing.entries_present",
            len(context.routing_entries) >= 1,
            ">=1 routing entry",
            f"{len(context.routing_entries)} entries covering wards {sorted(routed)[:8]}",
            "Submissions need at least one ward mapping or they all become routing exceptions.",
        )
    )
    same_priority_dupes = _duplicate_routes(context.routing_entries)
    checks.append(
        SimulationCheck(
            "routing.no_equal_priority_overlap",
            not same_priority_dupes,
            "no equal-priority overlapping matches",
            f"{len(same_priority_dupes)} conflicting (ward, category, priority) tuple(s)",
            "Equal-priority overlapping matches are rejected at policy review (data model s.3).",
        )
    )

    targets = payload.get("internal_targets", {})
    total_internal = sum(int(v) for v in targets.values()) if isinstance(targets, Mapping) else 0
    case_target = int(payload.get("case_target_calendar_minutes", 0) or 0)
    checks.append(
        SimulationCheck(
            "clocks.case_target_covers_stages",
            case_target >= total_internal > 0,
            "case target >= sum of internal stage targets",
            f"case={case_target} internal_sum={total_internal}",
            "A case target shorter than its stage budgets is unreachable.",
        )
    )

    checks.append(
        SimulationCheck(
            "transitions.reject_from_subset",
            set(payload.get("reject_from", []))
            <= {"SCRUTINY", "INFO_REQUIRED", "REVIEW_PENDING", "COMPLIANCE_PENDING"},
            "reject_from within TR-12 stages",
            str(payload.get("reject_from")),
            "Rejection is only lawful from the TR-12 stages the profile enables.",
        )
    )
    checks.append(
        SimulationCheck(
            "transitions.withdraw_not_after_approval",
            not (
                {"REVIEW_PENDING", "APPROVED_PENDING_ISSUE", "COMPLETED", "REJECTED", "WITHDRAWN"}
                & set(payload.get("withdraw_from", []))
            ),
            "no withdrawal from REVIEW_PENDING/approval/terminal stages",
            str(payload.get("withdraw_from")),
            "Demo withdrawal is not allowed once review or approval has begun (workflow s.3).",
        )
    )

    passed = all(c.passed for c in checks)
    return passed, checks


def _duplicate_routes(entries: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    seen: dict[tuple[str, str, int], int] = {}
    for entry in entries:
        key = (
            str(entry.get("ward_key")),
            str(entry.get("category_key") or "*"),
            int(entry.get("priority", 0)),
        )
        seen[key] = seen.get(key, 0) + 1
    return [k for k, n in seen.items() if n > 1]
