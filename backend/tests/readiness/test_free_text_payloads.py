"""Free text x security payload family (PRODUCTION_READY_TEST.md s.13 "Free text x security
payload family"; SEC-1062..1071, SEC-1079..1082): markup, template syntax, SQL-like text, CR/LF,
formula-leading text, Unicode / control characters, max length and over-max length in the
applicant-facing free-text inputs. Expected: stored and returned as data (never interpreted),
JSON responses never carry raw `<`/`>`, over-max length is a 422 with a pointer, a NUL byte is a
validation failure and never a 500.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from agni.cases.models import Premises
from agni.identity.models import Principal
from agni.routing.models import DutyQueue
from tests.integration.test_premises_api import VALID as VALID_PREMISES
from tests.integration.test_submission import cmd

JSON = "application/json"
PAYLOADS: dict[str, str] = {
    "markup": "<script>alert('x')</script><img src=x onerror=alert(1)>",
    "template": "{{7*7}} ${7*7} <%= 7*7 %> {% raw %}",
    "sql": "Demo'; DROP TABLE cases_premises; -- ' OR 1=1 --",
    "crlf": "Demo\r\nX-Injected: header\nSet-Cookie: a=b",
    "formula-equals": '=HYPERLINK("https://example.test","click")',
    "formula-plus": "+cmd|' /C calc'!A0",
    "formula-minus": "-2+3+cmd|' /C calc'!A0",
    "formula-at": "@SUM(1+1)*cmd|' /C calc'!A0",
    "unicode": "नमस्ते 🔥 Ωmega ‮RTL‬ ﬁ",
}


def _create_premises(client: Client, display_name: str) -> Any:
    return client.post(
        "/api/v1/premises",
        data={**VALID_PREMISES, "display_name": display_name},
        content_type=JSON,
        headers=cmd(),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("family", sorted(PAYLOADS))
def test_premises_name_payloads_are_stored_as_inert_data(
    family: str, applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    text = PAYLOADS[family]
    created = _create_premises(client, text)
    assert created.status_code == 201, (family, created.content)
    premises_id = created.json()["data"]["premises_id"]
    stored = Premises.objects.get(pk=premises_id).display_name
    assert stored == text.strip(), family
    detail = client.get(f"/api/v1/premises/{premises_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["display_name"] == text.strip()
    raw = detail.content.decode()
    # SafeJSONRenderer: no raw angle brackets or ampersands leave the API inside JSON strings.
    assert "<" not in raw and ">" not in raw, family
    # Header injection through stored text is impossible: headers are never derived from it.
    assert "X-Injected" not in "".join(f"{k}:{v}" for k, v in detail.headers.items())
    listing = client.get("/api/v1/premises")
    assert listing.status_code == 200 and "<script" not in listing.content.decode()


@pytest.mark.django_db
def test_premises_name_boundaries_and_control_characters(
    applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    at_max = "A" * 160
    assert _create_premises(client, at_max).status_code == 201
    over = _create_premises(client, "A" * 161)
    assert over.status_code == 422 and over.json()["code"] == "VALIDATION_FAILED"
    assert any(x["pointer"] == "/display_name" for x in over.json()["violations"])
    nul = _create_premises(client, "Demo\x00Mall")
    assert nul.status_code == 422, nul.content
    assert nul.json()["code"] == "VALIDATION_FAILED"
    assert any(x["pointer"] == "/display_name" for x in nul.json()["violations"])
    wrong_type = client.post(
        "/api/v1/premises",
        data={**VALID_PREMISES, "display_name": ["not", "a", "string"]},
        content_type=JSON,
        headers=cmd(),
    )
    assert wrong_type.status_code == 422
    assert Premises.objects.filter(owner=applicant).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("family", sorted(PAYLOADS))
def test_support_ticket_text_payloads_are_stored_as_inert_data(
    family: str,
    applicant: Principal,
    duty_queue: DutyQueue,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    text = PAYLOADS[family]
    created = client.post(
        "/api/v1/tickets",
        data={
            "category": "TECHNICAL",
            "subject": f"Probe {text}"[:160],
            "description": f"Description probe: {text} and enough words to pass the minimum.",
        },
        content_type=JSON,
        headers=cmd(),
    )
    assert created.status_code == 201, (family, created.content)
    tid = created.json()["data"]["ticket_id"]
    view = client.get(f"/api/v1/tickets/{tid}")
    assert view.status_code == 200
    body = view.json()["data"]
    assert body["subject"] == f"Probe {text}"[:160].strip()
    assert text in body["messages"][0]["body"]
    raw = view.content.decode()
    assert "<" not in raw and ">" not in raw, family


@pytest.mark.django_db
def test_search_parameters_are_treated_as_data(
    applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    for value in (*PAYLOADS.values(), "%", "_", "\\", "a" * 2000):
        response = client.get("/api/v1/applications", {"q": value})
        assert response.status_code in (200, 422), (value[:40], response.status_code)
        assert response.status_code != 500
        if response.status_code == 200:
            assert response.json()["data"]["items"] == []
    # A NUL byte in the search term is a malformed request, never a database error.
    nul = client.get("/api/v1/applications", {"q": "demo\x00mall"})
    assert nul.status_code in (400, 422), nul.content
    assert nul.json()["code"] in ("MALFORMED_REQUEST", "VALIDATION_FAILED")
