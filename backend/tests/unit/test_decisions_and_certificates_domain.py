"""Pure rules of B12: decision readiness guard list, effective certificate status precedence
and the simulated PDF structure."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from agni.certificates.adapters import WATERMARK, minimal_pdf
from agni.certificates.application.registry import effective_status
from agni.decisions.domain.readiness import (
    ActorFacts,
    Blocker,
    CaseFacts,
    approve_blockers,
    readiness,
    reject_blockers,
)

CLEAN = CaseFacts(
    status="REVIEW_PENDING",
    inspection_required=True,
    has_accepted_report=True,
    report_eligible=True,
    report_blockers=(),
    open_mandatory_findings=(),
    reinspection_outstanding=(),
    open_attempt=False,
    routing_exception_open=False,
    open_notices=(),
    decision_exists=False,
    reject_from=("REVIEW_PENDING",),
)
AUTHORISED = ActorFacts(
    has_grant=True,
    grant_out_of_scope=False,
    inspected_this_case=False,
    inspector_cannot_decide=True,
)


def codes(blockers: tuple[Blocker, ...]) -> list[str]:
    return [b.code for b in blockers]


def test_clean_case_with_authority_is_ready_for_either_outcome() -> None:
    result = readiness(CLEAN, AUTHORISED)
    assert result.can_approve and result.can_reject


# PROP-02 (a favourable decision implies every mandatory guard passed; nothing compensates)
def test_every_guard_produces_its_own_blocker_and_none_is_compensated() -> None:
    blocked = replace(
        CLEAN,
        report_eligible=False,
        report_blockers=("MANDATORY_FAIL:C01",),
        open_mandatory_findings=("C01",),
        open_attempt=True,
        routing_exception_open=True,
        open_notices=("DEFICIENCY:1",),
    )
    result = codes(approve_blockers(blocked, AUTHORISED))
    assert result == [
        "ROUTING_UNRESOLVED",
        "INSPECTION_OPEN",
        "REPORT_NOT_ELIGIBLE",
        "MANDATORY_FINDINGS_OPEN",
        "NOTICE_OPEN",
    ]
    # Rejection does not depend on the report but still needs authority and the profile stage.
    assert reject_blockers(blocked, AUTHORISED) == ()
    assert codes(reject_blockers(replace(blocked, status="SCRUTINY"), AUTHORISED)) == [
        "STATUS_NOT_PERMITTED"
    ]


def test_authority_and_separation_of_duties_block_both_outcomes() -> None:
    missing = ActorFacts(False, False, False, True)
    out_of_scope = ActorFacts(False, True, False, True)
    inspector = ActorFacts(True, False, True, True)
    permissive_profile = ActorFacts(True, False, True, False)
    assert codes(approve_blockers(CLEAN, missing)) == ["AUTHORITY_MISSING"]
    assert codes(reject_blockers(CLEAN, out_of_scope)) == ["AUTHORITY_SCOPE_MISMATCH"]
    assert codes(approve_blockers(CLEAN, inspector)) == ["SEPARATION_OF_DUTIES"]
    assert approve_blockers(CLEAN, permissive_profile) == ()


def test_existing_decision_and_wrong_status_block_approval() -> None:
    assert codes(approve_blockers(replace(CLEAN, decision_exists=True), AUTHORISED)) == [
        "DECISION_EXISTS"
    ]
    assert codes(approve_blockers(replace(CLEAN, status="SCRUTINY"), AUTHORISED)) == [
        "STATUS_NOT_REVIEW_PENDING"
    ]
    assert codes(
        approve_blockers(
            replace(CLEAN, has_accepted_report=False, report_eligible=False), AUTHORISED
        )
    ) == ["NO_ACCEPTED_REPORT"]
    # A policy without a required visit may approve on the submission alone.
    assert (
        approve_blockers(
            replace(
                CLEAN, inspection_required=False, has_accepted_report=False, report_eligible=False
            ),
            AUTHORISED,
        )
        == ()
    )


# Cases: AT-22-02 (expired / revoked / suspended never verify ACTIVE) PROP-12 (expiry wins without
# any projection refresh)
def test_effective_status_precedence_and_expiry_at_the_boundary() -> None:
    now = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)

    def cert(recorded: str, valid_until: datetime | None) -> object:
        return SimpleNamespace(recorded_status=recorded, valid_until=valid_until)

    later = now + timedelta(days=1)
    assert effective_status(cert("ACTIVE", later), now) == "ACTIVE"  # type: ignore[arg-type]
    assert effective_status(cert("ACTIVE", now), now) == "EXPIRED"  # type: ignore[arg-type]
    assert effective_status(cert("SUSPENDED", later), now) == "SUSPENDED"  # type: ignore[arg-type]
    assert effective_status(cert("SUSPENDED", now - timedelta(1)), now) == "EXPIRED"  # type: ignore[arg-type]
    assert effective_status(cert("REVOKED", later), now) == "REVOKED"  # type: ignore[arg-type]
    assert effective_status(cert("REVOKED", now - timedelta(1)), now) == "REVOKED"  # type: ignore[arg-type]
    assert effective_status(cert("SUPERSEDED", now - timedelta(1)), now) == "SUPERSEDED"  # type: ignore[arg-type]
    assert effective_status(cert("ACTIVE", None), now) == "ACTIVE"  # type: ignore[arg-type]


def test_minimal_pdf_is_a_valid_single_page_document_with_the_watermark() -> None:
    data = minimal_pdf([WATERMARK, "Certificate (AGNI-DEMO-2026-101)"])
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert data.count(b"endobj") == 5 and b"/Type /Page" in data and b"xref" in data
    assert WATERMARK.encode() in data and b"\\(AGNI-DEMO-2026-101\\)" in data
    assert minimal_pdf(["a"]) == minimal_pdf(["a"])  # deterministic
