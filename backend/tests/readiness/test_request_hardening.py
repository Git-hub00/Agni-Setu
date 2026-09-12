"""SEC-1086..1089, SEC-1084 - request-level hardening: oversized and deeply nested JSON, invalid
JSON, unsupported media types, disallowed methods and unknown API routes all answer as bounded
problem responses (never a 500, never a stack trace)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from agni.identity.models import Principal
from tests.integration.test_submission import cmd

JSON = "application/json"


def _problem(response: Any) -> dict[str, Any]:
    assert response["Content-Type"].startswith("application/problem+json"), response.content
    body: dict[str, Any] = response.json()
    assert body["request_id"] and "Traceback" not in response.content.decode()
    return body


@pytest.mark.django_db
def test_deeply_nested_and_invalid_json_are_bounded_malformed_requests(
    applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    browser = Client(enforce_csrf_checks=True, raise_request_exception=False)
    browser.cookies["sessionid"] = client.cookies["sessionid"].value
    browser.cookies["csrftoken"] = client.cookies["csrftoken"].value
    browser.defaults["HTTP_X_CSRFTOKEN"] = client.defaults["HTTP_X_CSRFTOKEN"]
    deep = "[" * 200_000 + "]" * 200_000
    response = browser.post("/api/v1/premises", data=deep, content_type=JSON, headers=cmd())
    assert response.status_code in (400, 413, 422), response.status_code
    assert _problem(response)["code"] in ("MALFORMED_REQUEST", "VALIDATION_FAILED")
    invalid = browser.post("/api/v1/premises", data="{not json", content_type=JSON, headers=cmd())
    assert invalid.status_code == 400 and _problem(invalid)["code"] == "MALFORMED_REQUEST"
    top_level_list = browser.post(
        "/api/v1/premises", data="[1,2]", content_type=JSON, headers=cmd()
    )
    assert top_level_list.status_code in (400, 422), top_level_list.content
    _problem(top_level_list)
    scalar = browser.post("/api/v1/premises", data='"x"', content_type=JSON, headers=cmd())
    assert scalar.status_code in (400, 422), scalar.content
    _problem(scalar)


@pytest.mark.django_db
def test_unsupported_media_methods_and_routes_are_problem_responses(
    applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    xml = client.post(
        "/api/v1/premises", data="<a/>", content_type="application/xml", headers=cmd()
    )
    assert xml.status_code in (400, 415), xml.content
    _problem(xml)
    form = client.post(
        "/api/v1/premises",
        data="display_name=x",
        content_type="application/x-www-form-urlencoded",
        headers=cmd(),
    )
    assert form.status_code in (400, 415, 422), form.content
    _problem(form)
    trace = client.generic("TRACE", "/api/v1/premises")
    assert trace.status_code in (405, 404, 400), trace.status_code
    unknown = client.get("/api/v1/definitely-not-a-route")
    assert unknown.status_code == 404
    assert _problem(unknown)["code"] == "RESOURCE_NOT_FOUND"
    for method in ("delete", "put"):
        response = getattr(client, method)("/api/v1/premises")
        assert response.status_code == 405, method
        assert _problem(response)["code"] == "MALFORMED_REQUEST"
    # Query-string abuse on a read route is data, never SQL or a crash.
    weird = client.get("/api/v1/applications", {"status": "'; DROP TABLE x; --", "cursor": "zz"})
    assert weird.status_code in (200, 400, 422), weird.content
