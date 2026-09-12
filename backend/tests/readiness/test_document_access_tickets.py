"""DOM-1010 / GOV-1341 - ticketed document retrieval re-authorises the holder: a ticket issued
to a principal whose access has since been revoked must not keep serving the file (invariants 1
and 24: revocation invalidates stale access), matching the export artifact route which already
re-checks the reader's current scope."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from agni.documents.models import DocumentVersion
from agni.identity.models import Principal, RoleBinding
from agni.platform.clock import FrozenClock

JSON = "application/json"


def grant_ticket(client: Client, doc_id: str, purpose: str = "DOWNLOAD") -> Any:
    return client.post(
        f"/api/v1/documents/{doc_id}/access",
        data={"purpose": purpose},
        content_type=JSON,
        headers={"Idempotency-Key": str(uuid4())},
    )


@pytest.mark.django_db
def test_download_ticket_is_reauthorised_against_the_current_scope(
    visit: dict[str, Any], supervisor: Principal, clock: FrozenClock
) -> None:
    """After the supervisor's role binding ends, the ticket they obtained a moment earlier must
    stop serving the applicant's file even though its 300 s lifetime has not elapsed."""
    v = visit
    boss = v["boss"]
    # One of the CLEAN submission documents of the visit case (visible to the case's supervisor).
    documents = DocumentVersion.objects.filter(application_id=v["app_id"], scan_state="CLEAN")
    document = documents.first()
    assert document is not None
    doc_id = str(document.pk)
    assert boss.get(f"/api/v1/documents/{doc_id}").status_code == 200
    granted = grant_ticket(boss, doc_id)
    assert granted.status_code == 200, granted.content
    url = granted.json()["data"]["url"]
    assert boss.get(url).status_code == 200

    # The supervisor's scope ends (binding revoked) - visibility of the document is gone...
    RoleBinding.objects.filter(principal=supervisor).update(
        revoked_at=clock.now(), effective_until=clock.now() + timedelta(seconds=1)
    )
    clock.advance(timedelta(seconds=2))
    assert boss.get(f"/api/v1/documents/{doc_id}").status_code in (403, 404)
    # ...so the previously issued ticket must not keep serving the bytes.
    late = boss.get(url)
    assert late.status_code in (403, 404), ("ticket still valid after revocation", late.status_code)
    assert b"%PDF" not in late.content


@pytest.mark.django_db
def test_download_ticket_still_works_for_the_owner_and_stays_principal_bound(
    visit: dict[str, Any], other_applicant: Principal, signed_client: Any
) -> None:
    """The re-authorisation must not break legitimate access: the owner downloads with a valid
    ticket; another principal never can, even with the owner's ticket."""
    v = visit
    owner = v["applicant"]
    documents = DocumentVersion.objects.filter(application_id=v["app_id"], scan_state="CLEAN")
    document = documents.first()
    assert document is not None
    granted = grant_ticket(owner, str(document.pk))
    assert granted.status_code == 200, granted.content
    url = granted.json()["data"]["url"]
    served = owner.get(url)
    assert served.status_code == 200
    assert served["Content-Type"] == "application/pdf"
    stranger = signed_client(other_applicant)
    assert stranger.get(url).status_code == 404
