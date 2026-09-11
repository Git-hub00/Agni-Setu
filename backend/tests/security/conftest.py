"""Security suite shares the real-PostgreSQL fixtures of the integration suite (B16; security
s.9 threat scenarios, s.10 release gates). Nothing here is mocked away."""

from __future__ import annotations

from tests.integration.conftest import (  # noqa: F401 - pytest fixtures
    _fresh_document_adapters,
    active_policy,
    applicant,
    artifacts,
    duty_queue,
    foreign_supervisor,
    governance_actors,
    inactive_service,
    jurisdiction,
    leadership,
    officers,
    other_applicant,
    plain_supervisor,
    premises,
    service,
    signed_client,
    staff,
    supervisor,
)
