"""Payload hygiene shared by every command endpoint (security s.9 "input handling").

PostgreSQL text columns refuse NUL, and other C0 control characters have no place in names,
reasons or observations; the per-command validators check type and length, so this boundary
check turns such input into a 422 with a JSON Pointer instead of a database error (500).
Tab, newline and carriage return stay allowed - multi-line explanations are legitimate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import ValidationFailed, Violation

_ALLOWED_CONTROL = frozenset({"\t", "\n", "\r"})


def has_control_characters(text: str) -> bool:
    return any((ch < " " and ch not in _ALLOWED_CONTROL) or ch == "\x7f" for ch in text)


def _escape(token: str) -> str:
    """RFC 6901 pointer token escaping."""
    return token.replace("~", "~0").replace("/", "~1")


def control_character_pointers(value: Any, pointer: str = "") -> list[str]:
    """JSON Pointers of every string inside `value` that carries a forbidden control character."""
    if isinstance(value, str):
        return [pointer or "/"] if has_control_characters(value) else []
    if isinstance(value, Mapping):
        found: list[str] = []
        for key, item in value.items():
            found.extend(control_character_pointers(item, f"{pointer}/{_escape(str(key))}"))
        return found
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        found = []
        for index, item in enumerate(value):
            found.extend(control_character_pointers(item, f"{pointer}/{index}"))
        return found
    return []


def reject_control_characters(payload: Mapping[str, Any]) -> None:
    pointers = control_character_pointers(payload)
    if pointers:
        raise ValidationFailed(
            violations=[
                Violation(pointer, "control_characters", "must not contain control characters")
                for pointer in pointers
            ]
        )
