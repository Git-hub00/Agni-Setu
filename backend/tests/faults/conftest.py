"""Fault-injection suite (B17; docs/08 s.10, docs/11 s.6). Runs against the real PostgreSQL test
database with the in-memory object store and the provider simulators; faults are injected at
the adapter boundary or by interrupting the worker between its two transactions. Every test
queries the business rows, jobs, attempts, outbox and audit - never "no exception happened"."""

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
