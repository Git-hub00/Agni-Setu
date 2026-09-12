"""JSON request parsing with a bounded failure mode (security s.9 "resource exhaustion").

DRF's `JSONParser` maps `ValueError` to `ParseError` (-> 400 MALFORMED_REQUEST), but Python's
recursive JSON decoder raises `RecursionError` for a document that nests deeper than the
interpreter's recursion limit; without this class that error escaped the parser and surfaced
as a 500. The API is JSON-only, so this is the sole default parser (file bytes travel through
the upload route, which declares its own empty parser list).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import IO, Any

from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class BoundedJSONParser(JSONParser):
    def parse(
        self,
        stream: IO[Any],
        media_type: str | None = None,
        parser_context: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            return super().parse(stream, media_type, parser_context)
        except RecursionError as exc:
            raise ParseError("JSON document nests too deeply") from exc
