"""Versioned JSON Schema for the policy package (workflow s.6). Policies are data: no executable
constructs are accepted; unknown properties are rejected. Pure functions, no ORM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

from agni.cases.domain.states import ApplicationStatus
from agni.platform.errors import ValidationFailed, Violation

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
STATE_VALUES = [s.value for s in ApplicationStatus]

POLICY_SCHEMA_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "key",
        "mode",
        "outcome_kind",
        "jurisdiction_key",
        "timezone",
        "calendar_key",
        "allowed_categories",
        "form_schema_key",
        "checklist_key",
        "routing_key",
        "base_documents",
        "extra_documents",
        "inspection_required",
        "reject_from",
        "withdraw_from",
        "separation_of_duties",
        "internal_targets",
        "case_target_calendar_minutes",
        "applicant_response_calendar_minutes",
        "reminder_fractions",
        "escalation_minutes_after_due",
        "permitted_pause_reasons",
        "sample_validity_days",
        "fees",
        "appeals",
        "external_registration",
        "public_fields",
    ],
    "properties": {
        "schema_version": {"const": "1.0"},
        "key": {"type": "string", "pattern": r"^[A-Z0-9][A-Z0-9-]{2,79}$"},
        "mode": {"enum": ["DEMO", "STANDALONE", "INTEGRATED_MONITORING"]},
        "outcome_kind": {"enum": ["DEMO_CERTIFICATE", "ISSUED_DEPARTMENT", "REGISTERED_EXTERNAL"]},
        "jurisdiction_key": {"type": "string", "minLength": 2, "maxLength": 40},
        "timezone": {"type": "string", "minLength": 3, "maxLength": 64},
        "calendar_key": {"type": "string", "minLength": 2, "maxLength": 80},
        "allowed_categories": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 2, "maxLength": 40},
        },
        "form_schema_key": {"type": "string", "minLength": 2, "maxLength": 80},
        "checklist_key": {"type": "string", "minLength": 2, "maxLength": 80},
        "routing_key": {"type": "string", "minLength": 2, "maxLength": 80},
        "base_documents": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_-]{1,59}$"},
        },
        "extra_documents": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_-]{1,59}$"},
            },
        },
        "inspection_required": {"type": "boolean"},
        "reject_from": {"type": "array", "uniqueItems": True, "items": {"enum": STATE_VALUES}},
        "withdraw_from": {"type": "array", "uniqueItems": True, "items": {"enum": STATE_VALUES}},
        "separation_of_duties": {
            "type": "object",
            "additionalProperties": False,
            "required": ["inspector_cannot_decide", "preparer_cannot_approve_policy"],
            "properties": {
                "inspector_cannot_decide": {"type": "boolean"},
                "preparer_cannot_approve_policy": {"const": True},
            },
        },
        "internal_targets": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "scrutiny_working_minutes",
                "inspection_calendar_minutes",
                "review_working_minutes",
                "issuance_calendar_minutes",
            ],
            "properties": {
                "scrutiny_working_minutes": {"type": "integer", "minimum": 1},
                "inspection_calendar_minutes": {"type": "integer", "minimum": 1},
                "review_working_minutes": {"type": "integer", "minimum": 1},
                "issuance_calendar_minutes": {"type": "integer", "minimum": 1},
            },
        },
        "case_target_calendar_minutes": {"type": "integer", "minimum": 1},
        "applicant_response_calendar_minutes": {"type": "integer", "minimum": 1},
        "reminder_fractions": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        },
        "escalation_minutes_after_due": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "integer", "minimum": 0},
        },
        "permitted_pause_reasons": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,59}$"},
        },
        "sample_validity_days": {"type": "integer", "minimum": 1, "maximum": 3650},
        "fees": {
            "type": "object",
            "additionalProperties": False,
            "required": ["enabled"],
            "properties": {"enabled": {"type": "boolean"}},
        },
        "appeals": {
            "type": "object",
            "additionalProperties": False,
            "required": ["enabled"],
            "properties": {
                "enabled": {"type": "boolean"},
                "referral_text": {"type": "string", "maxLength": 500},
            },
        },
        "external_registration": {
            "type": "object",
            "additionalProperties": False,
            "required": ["enabled"],
            "properties": {"enabled": {"type": "boolean"}},
        },
        "public_fields": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{1,59}$"},
        },
    },
}

_VALIDATOR = Draft202012Validator(POLICY_SCHEMA_V1)


def validate_policy_payload(payload: Mapping[str, Any]) -> list[Violation]:
    """Return schema violations (empty list when valid). Pointers address the payload."""
    violations: list[Violation] = []
    for error in sorted(_VALIDATOR.iter_errors(dict(payload)), key=lambda e: list(e.absolute_path)):
        pointer = (
            "/payload/" + "/".join(str(p) for p in error.absolute_path)
            if error.absolute_path
            else "/payload"
        )
        if (
            error.validator == "additionalProperties"
            and isinstance(error.instance, dict)
            and isinstance(error.schema, dict)
        ):
            # Point at each offending property rather than at the whole object.
            known = set(error.schema.get("properties", {}))
            for extra_key in sorted(set(error.instance) - known):
                violations.append(
                    Violation(f"{pointer}/{extra_key}", "additionalProperties", "unknown property")
                )
            continue
        violations.append(Violation(pointer, str(error.validator), error.message[:200]))
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        violations.append(
            Violation("/payload/schema_version", "unsupported", "unsupported policy schema version")
        )
    # Cross-field rules the schema cannot express.
    fractions = payload.get("reminder_fractions")
    if isinstance(fractions, list) and fractions != sorted(fractions):
        violations.append(
            Violation(
                "/payload/reminder_fractions", "order", "reminder fractions must be ascending"
            )
        )
    escalations = payload.get("escalation_minutes_after_due")
    if isinstance(escalations, list) and escalations != sorted(escalations):
        violations.append(
            Violation(
                "/payload/escalation_minutes_after_due",
                "order",
                "escalation minutes must be ascending",
            )
        )
    extra = payload.get("extra_documents")
    allowed = payload.get("allowed_categories")
    if isinstance(extra, dict) and isinstance(allowed, list):
        for category in extra:
            if category not in allowed:
                violations.append(
                    Violation(
                        f"/payload/extra_documents/{category}",
                        "unknown_category",
                        "not an allowed category",
                    )
                )
    if payload.get("mode") == "DEMO" and payload.get("outcome_kind") != "DEMO_CERTIFICATE":
        violations.append(
            Violation(
                "/payload/outcome_kind", "demo_marker", "DEMO mode must issue DEMO_CERTIFICATE"
            )
        )
    if payload.get("mode") != "DEMO" and payload.get("outcome_kind") == "DEMO_CERTIFICATE":
        violations.append(
            Violation(
                "/payload/outcome_kind", "demo_marker", "only DEMO mode may issue demo certificates"
            )
        )
    return violations


def require_valid_policy_payload(payload: Mapping[str, Any]) -> None:
    violations = validate_policy_payload(payload)
    if violations:
        raise ValidationFailed(
            detail="Policy payload does not satisfy the schema", violations=violations
        )


def required_documents(payload: Mapping[str, Any], category_key: str) -> list[str]:
    base = list(payload.get("base_documents", []))
    extra = payload.get("extra_documents", {}).get(category_key, [])
    return base + [doc for doc in extra if doc not in base]
