"""RFC 6266 file-name header construction (security s.9): user-supplied names never reach the
header raw; the fallback is inert ASCII and `filename*` carries the exact name encoded."""

from __future__ import annotations

import pytest

from agni.documents.api.views import content_disposition


@pytest.mark.parametrize(
    ("name", "fallback"),
    [
        ("layout.pdf", "layout.pdf"),
        ("../../etc/passwd.pdf", "etc_passwd.pdf"),
        ("plan\r\nX-Injected: yes.pdf", "plan_X-Injected_yes.pdf"),
        ("<script>alert(1)</script>.pdf", "script_alert_1_script_.pdf"),
        ('plan "quoted" name.pdf', "plan_quoted_name.pdf"),
        ("योजना-🔥-plan.pdf", "plan.pdf"),
        ("....pdf", "pdf"),
        ("///", "document"),
    ],
)
def test_fallback_is_inert_ascii(name: str, fallback: str) -> None:
    header = content_disposition("attachment", name)
    assert header.startswith(f"attachment; filename=\"{fallback}\"; filename*=UTF-8''")
    # Only the two quotes around the fallback survive; markup and control characters never do.
    assert header.count('"') == 2
    assert "\r" not in header and "\n" not in header and "<" not in header and ">" not in header


def test_extended_parameter_round_trips_the_exact_name() -> None:
    from urllib.parse import unquote

    name = 'योजना-🔥-<plan> "final".pdf'
    header = content_disposition("inline", name)
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name
    assert header.startswith("inline; ")
