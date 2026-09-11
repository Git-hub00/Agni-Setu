"""Hold guard and projection (FR-18 holds; workflow s.7). Imports models only so every command
module can call `ensure_not_on_hold` without import cycles."""

from __future__ import annotations

from typing import Any

from agni.platform.errors import InvalidTransition

from ..models import Application, CaseHold, HoldState

BLOCK_SCOPES = ("TRANSITIONS", "DECISIONS")


def active_holds(application: Application) -> list[CaseHold]:
    return list(
        CaseHold.objects.filter(application=application, state=HoldState.ACTIVE).order_by(
            "starts_at"
        )
    )


def ensure_not_on_hold(application: Application, *, scope: str) -> None:
    """`scope` is "transition" (any application transition) or "decision" (TR-10/TR-12).
    A hold listing TRANSITIONS blocks both; DECISIONS blocks only decisions; an empty list
    pauses clocks without blocking commands."""
    for hold in active_holds(application):
        blocks = {str(s) for s in (hold.command_block_scope or [])}
        if "TRANSITIONS" in blocks or (scope == "decision" and "DECISIONS" in blocks):
            raise InvalidTransition(
                "The case is on hold; this command is blocked until the hold is released",
                extensions={
                    "hold_id": str(hold.pk),
                    "hold_kind": hold.kind,
                    "block_scope": sorted(blocks),
                },
            )


def hold_body(hold: CaseHold) -> dict[str, Any]:
    return {
        "hold_id": str(hold.pk),
        "application_id": str(hold.application_id),
        "kind": hold.kind,
        "state": hold.state,
        "reason": hold.reason,
        "basis_document_id": str(hold.basis_document_id) if hold.basis_document_id else None,
        "authorized_by": str(hold.authorized_by_id),
        "starts_at": hold.starts_at.isoformat(),
        "requested_end_at": hold.requested_end_at.isoformat() if hold.requested_end_at else None,
        "ends_at": hold.ends_at.isoformat() if hold.ends_at else None,
        "affected_obligation_ids": [str(x) for x in hold.affected_obligations],
        "command_block_scope": list(hold.command_block_scope),
        "released_by": str(hold.released_by_id) if hold.released_by_id else None,
        "release_reason": hold.release_reason or None,
        "version": hold.version,
        "etag": hold.etag,
    }
