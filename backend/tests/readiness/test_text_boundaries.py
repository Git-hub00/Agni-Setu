"""Text boundaries of the premises command (DOM/WF input rules): a name that is blank once
surrounding whitespace is removed is not a name, and the record must not be created."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.test import Client

from agni.cases.models import Premises
from agni.identity.models import Principal
from tests.integration.test_premises_api import VALID as VALID_PREMISES
from tests.integration.test_submission import cmd

JSON = "application/json"


@pytest.mark.django_db
@pytest.mark.parametrize("blank", ["   ", "\t\n", " \r\n "])
def test_blank_after_strip_required_text_is_refused(
    blank: str, applicant: Principal, signed_client: Callable[[Principal], Client]
) -> None:
    client = signed_client(applicant)
    response = client.post(
        "/api/v1/premises",
        data={**VALID_PREMISES, "display_name": blank},
        content_type=JSON,
        headers=cmd(),
    )
    assert response.status_code == 422, response.content
    assert any(
        v["pointer"] == "/display_name" and v["code"] == "required"
        for v in response.json()["violations"]
    ), response.json()
    assert not Premises.objects.filter(owner=applicant).exists()
