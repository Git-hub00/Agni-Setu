"""JSON renderer that never emits raw HTML metacharacters (security s.9 "stored XSS"). The API
returns data, not markup; escaping `<`, `>` and `&` as JSON unicode escapes keeps a response
inert even if a browser is ever coaxed into treating it as HTML. Clients decode identical
strings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rest_framework.renderers import JSONRenderer

_ESCAPES = ((b"<", b"\\u003c"), (b">", b"\\u003e"), (b"&", b"\\u0026"))


class SafeJSONRenderer(JSONRenderer):
    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: Mapping[str, Any] | None = None,
    ) -> bytes:
        rendered: bytes = super().render(data, accepted_media_type, renderer_context)
        for raw, escaped in _ESCAPES:
            rendered = rendered.replace(raw, escaped)
        return rendered
