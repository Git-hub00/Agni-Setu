"""Production-readiness probe suite (PRODUCTION_READY_TEST.md s.12: state x command, role x
command, kernel contract sweep, free-text payload families). Shares the real-PostgreSQL fixtures
of the integration suite; nothing is mocked away."""

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
from tests.integration.test_decisions import _reset_signer  # noqa: F401 - pytest fixture
from tests.integration.test_reports import visit  # noqa: F401 - pytest fixture
