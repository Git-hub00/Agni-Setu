"""The single HTTP boundary renders typed errors as RFC 9457 problem details."""

from __future__ import annotations

from uuid import uuid4

import pytest
from rest_framework import exceptions as drf

from agni.platform.api.exceptions import PROBLEM_CONTENT_TYPE, problem_exception_handler
from agni.platform.correlation import bind_request_id, reset_request_id
from agni.platform.errors import (
    CATALOGUE,
    DomainError,
    MalformedRequest,
    VersionConflict,
    Violation,
)


def test_catalogue_matches_error_document_statuses() -> None:
    assert CATALOGUE["VERSION_CONFLICT"].status == 412
    assert CATALOGUE["PRECONDITION_REQUIRED"].status == 428
    assert CATALOGUE["IDEMPOTENCY_CONFLICT"].status == 409
    assert CATALOGUE["RESOURCE_NOT_FOUND"].status == 404
    assert CATALOGUE["VERIFICATION_UNAVAILABLE"].status == 503
    assert len(CATALOGUE) == 51


def test_domain_error_renders_problem_details_with_request_id() -> None:
    request_id = uuid4()
    token = bind_request_id(request_id)
    try:
        error = VersionConflict("The resource has changed", extensions={"current_version": 7})
        response = problem_exception_handler(error, {})
    finally:
        reset_request_id(token)

    assert response.status_code == 412
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.data["type"] == "urn:agni-setu:problem:version-conflict"
    assert response.data["code"] == "VERSION_CONFLICT"
    assert response.data["request_id"] == str(request_id)
    assert response.data["current_version"] == 7
    assert response.data["detail"] == "The resource has changed"


def test_drf_validation_error_becomes_violations_with_pointers() -> None:
    error = drf.ValidationError(
        {"premises_id": ["This field is required."], "items": [{"code": ["invalid"]}]}
    )
    response = problem_exception_handler(error, {})
    assert response.status_code == 422
    pointers = {v["pointer"] for v in response.data["violations"]}
    assert pointers == {"/premises_id", "/items/0/code"}


def test_unknown_exception_is_internal_error_without_details() -> None:
    response = problem_exception_handler(RuntimeError("secret stack detail"), {})
    assert response.status_code == 500
    assert response.data["code"] == "INTERNAL_ERROR"
    assert "secret" not in str(response.data)


def test_throttled_sets_retry_after_header() -> None:
    response = problem_exception_handler(drf.Throttled(wait=30), {})
    assert response.status_code == 429 and response["Retry-After"] == "30"


def test_drf_not_found_and_permission_map_to_catalogue() -> None:
    assert problem_exception_handler(drf.NotFound(), {}).data["code"] == "RESOURCE_NOT_FOUND"
    assert problem_exception_handler(drf.PermissionDenied(), {}).data["code"] == "FORBIDDEN"
    assert (
        problem_exception_handler(drf.NotAuthenticated(), {}).data["code"]
        == "AUTHENTICATION_REQUIRED"
    )
    assert (
        problem_exception_handler(drf.PermissionDenied("CSRF Failed: missing"), {}).data["code"]
        == "CSRF_FAILED"
    )


def test_violations_serialise_without_secrets() -> None:
    error = MalformedRequest(violations=[Violation("/x", "invalid", "bad")])
    body = error.to_problem(None)
    assert body["violations"] == [{"pointer": "/x", "code": "invalid", "message": "bad"}]
    assert body["request_id"] is None


def test_unknown_code_is_a_programming_error() -> None:
    class Bogus(DomainError):
        code = "NOT_IN_CATALOGUE"

    with pytest.raises(ValueError):
        Bogus()
