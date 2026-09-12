"""Boundary hygiene for command payloads: control characters are pointed at, never stored."""

from __future__ import annotations

import pytest

from agni.platform.api.payloads import (
    control_character_pointers,
    has_control_characters,
    reject_control_characters,
)
from agni.platform.errors import ValidationFailed


def test_tab_newline_and_carriage_return_are_allowed() -> None:
    assert has_control_characters("line one\nline two\r\n\tindented") is False
    assert control_character_pointers({"note": "a\tb\nc"}) == []


@pytest.mark.parametrize("bad", ["Demo\x00Mall", "\x01", "bell\x07", "esc\x1b[31m", "del\x7f"])
def test_c0_controls_and_delete_are_rejected(bad: str) -> None:
    assert has_control_characters(bad) is True


def test_pointers_walk_objects_and_arrays_with_rfc6901_escaping() -> None:
    payload = {
        "display_name": "ok",
        "items": [{"text": "fine"}, {"text": "bad\x00"}],
        "a/b~c": "\x00",
        "nested": {"deep": ["x", "\x1f"]},
    }
    assert control_character_pointers(payload) == [
        "/items/1/text",
        "/a~1b~0c",
        "/nested/deep/1",
    ]


def test_reject_raises_validation_failed_with_every_pointer() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        reject_control_characters({"reason": "x\x00", "fields": {"locality": "y\x00"}})
    violations = {v.pointer: v.code for v in excinfo.value.violations}
    assert violations == {"/reason": "control_characters", "/fields/locality": "control_characters"}
    reject_control_characters({"reason": "clean", "count": 3, "flag": None, "list": [1, "ok"]})
