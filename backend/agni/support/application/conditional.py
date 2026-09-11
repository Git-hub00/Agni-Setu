"""Profile-gated routes (FR-30 appeals, FR-24 declarations, FR-21 external registration,
fees; integrations s.9 and s.11). Read from the ACTIVE policy payload: a disabled feature is
shown as a referral, never as a fake filing form. Nothing here enables a legal flow."""

from __future__ import annotations

from typing import Any

from agni.policies.models import PolicyState, PolicyVersion

DEFAULT_REFERRAL = "Contact the demonstration support desk; this is not a legal appeal service."


def active_policy_payload() -> dict[str, Any]:
    policy = (
        PolicyVersion.objects.filter(state=PolicyState.ACTIVE)
        .order_by("-effective_from", "-number")
        .first()
    )
    return dict(policy.payload) if policy is not None else {}


def conditional_routes() -> dict[str, Any]:
    payload = active_policy_payload()
    appeals = payload.get("appeals", {}) if isinstance(payload.get("appeals"), dict) else {}
    external = (
        payload.get("external_registration", {})
        if isinstance(payload.get("external_registration"), dict)
        else {}
    )
    fees = payload.get("fees", {}) if isinstance(payload.get("fees"), dict) else {}
    declarations = (
        payload.get("continuing_declarations", {})
        if isinstance(payload.get("continuing_declarations"), dict)
        else {}
    )
    return {
        "appeals": {
            "enabled": bool(appeals.get("enabled", False)),
            "referral_text": str(appeals.get("referral_text") or DEFAULT_REFERRAL),
        },
        "external_registration": {"enabled": bool(external.get("enabled", False))},
        "fees": {"enabled": bool(fees.get("enabled", False))},
        "continuing_declarations": {"enabled": bool(declarations.get("enabled", False))},
        "policy_present": bool(payload),
    }
