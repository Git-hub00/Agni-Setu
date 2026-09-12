"""SEC-1065 / DOM-0998 / DOM-0999 - stored file names never become header or markup injection
vectors: traversal, CR/LF, markup, quotes, Unicode and over-long names are inert in the JSON
projection and in the download `Content-Disposition` header (RFC 6266: ASCII fallback plus a
percent-encoded `filename*`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.cases.models import Premises
from agni.identity.models import Principal
from agni.platform.clock import FrozenClock
from agni.policies.models import Service
from tests.integration.test_drafts import create_draft
from tests.integration.test_uploads import PDF, reserve, run_worker, sha

JSON = "application/json"
FILENAMES = {
    "traversal": "../../etc/passwd.pdf",
    "crlf": "plan\r\nX-Injected: yes.pdf",
    "markup": "<script>alert(1)</script>.pdf",
    "quotes": 'plan "quoted" name.pdf',
    "unicode": "योजना-🔥-plan.pdf",
    "long": ("p" * 170) + ".pdf",
}


def grant_ticket(client: Client, doc_id: str, purpose: str = "DOWNLOAD") -> Any:
    return client.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": purpose},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )


@pytest.mark.django_db
@pytest.mark.parametrize("family", sorted(FILENAMES))
def test_stored_file_names_are_inert_in_headers_and_json(
    family: str,
    applicant: Principal,
    premises: Premises,
    service: Service,
    active_policy: Any,
    clock: FrozenClock,
    signed_client: Callable[[Principal], Client],
) -> None:
    client = signed_client(applicant)
    app_id = create_draft(client, premises, service).json()["data"]["application_id"]
    name = FILENAMES[family]
    data = PDF + family.encode()
    reserved = reserve(client, app_id, "plan", data, original_name=name)
    if len(name) > 180:
        assert reserved.status_code == 422, reserved.content
        return
    assert reserved.status_code == 201, (family, reserved.content)
    ticket = reserved.json()["data"]
    put = client.put(ticket["upload_url"], data=data, content_type="application/pdf")
    assert put.status_code == 200, put.content
    done = client.post(
        f"/api/v1/uploads/{ticket['upload_id']}/complete",
        data={"sha256": sha(data), "size_bytes": len(data)},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4()), "If-Match": reserved["ETag"]},
    )
    assert done.status_code == 202, done.content
    run_worker(clock)
    doc_id = done.json()["data"]["document_version_id"]
    detail = client.get(f"/api/v1/documents/{doc_id}")
    assert detail.status_code == 200
    raw = detail.content.decode()
    assert "<" not in raw and ">" not in raw, family
    granted = grant_ticket(client, doc_id)
    assert granted.status_code == 200, granted.content
    content = client.get(granted.json()["data"]["url"])
    assert content.status_code == 200, (family, content.status_code)
    disposition = content["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert "\r" not in disposition and "\n" not in disposition
    assert "<" not in disposition and ">" not in disposition
    assert ".." not in disposition.split(";")[1], disposition  # ASCII fallback carries no traversal
    assert "filename*=UTF-8''" in disposition
    assert "X-Injected" not in content.headers
    assert content["Content-Type"] == "application/pdf"
    assert b"".join(getattr(content, "streaming_content")) == data  # noqa: B009
