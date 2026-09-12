"""The API's JSON parser boundary: malformed and pathologically nested documents are parse
errors (400), never interpreter errors (500)."""

from __future__ import annotations

import io

import pytest
from rest_framework.exceptions import ParseError

from agni.platform.api.parsers import BoundedJSONParser


def _parse(payload: bytes) -> object:
    return BoundedJSONParser().parse(io.BytesIO(payload), "application/json", {"encoding": "utf-8"})


def test_valid_document_parses() -> None:
    assert _parse(b'{"a": [1, 2, {"b": null}]}') == {"a": [1, 2, {"b": None}]}


def test_invalid_document_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        _parse(b"{not json")


def test_deeply_nested_document_is_a_parse_error_not_a_recursion_error() -> None:
    deep = b"[" * 200_000 + b"]" * 200_000
    with pytest.raises(ParseError) as excinfo:
        _parse(deep)
    assert "nests too deeply" in str(excinfo.value.detail)


def test_nested_within_the_interpreter_limit_still_parses() -> None:
    depth = 200
    assert _parse(b"[" * depth + b"]" * depth) is not None
