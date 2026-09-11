"""FR-14 evaluator: deterministic blockers, policy-permitted NA, evidence rules, no scoring."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agni.inspections.domain.checklist import (
    ChecklistItem,
    checklist_items,
    evaluate,
    validate_observations,
)

ITEMS = checklist_items(
    {
        "items": [
            {
                "code": "C01",
                "title": "Means of escape",
                "mandatory": True,
                "evidence_required": True,
                "na_permitted": False,
            },
            {
                "code": "C04",
                "title": "Fire-water",
                "mandatory": True,
                "evidence_required": True,
                "na_permitted": True,
            },
            {
                "code": "C07",
                "title": "Access",
                "mandatory": False,
                "evidence_required": False,
                "na_permitted": True,
            },
        ]
    }
)
DOC = str(uuid4())


def obs(code: str, result: str, note: str = "", docs: list[str] | None = None) -> dict[str, Any]:
    return {"item_code": code, "result": result, "note": note, "document_version_ids": docs or []}


def clean(*observations: dict[str, Any], complete: bool = True) -> list[dict[str, Any]]:
    cleaned, violations = validate_observations(ITEMS, list(observations), complete=complete)
    assert violations == [], violations
    return cleaned


def test_items_parse_flags() -> None:
    assert ITEMS[1] == ChecklistItem("C04", "Fire-water", True, True, True)


def test_all_pass_with_evidence_is_eligible_and_records_no_score() -> None:
    result = evaluate(
        ITEMS,
        clean(obs("C01", "PASS", docs=[DOC]), obs("C04", "PASS", docs=[DOC]), obs("C07", "PASS")),
    )
    assert result.eligible_for_review is True and result.blockers == ()
    payload = result.as_dict()
    assert "score" not in payload and payload["counts"]["PASS"] == 3


def test_mandatory_fail_and_not_verified_block_regardless_of_other_passes() -> None:
    failed = evaluate(
        ITEMS,
        clean(
            obs("C01", "FAIL", "Escape route obstructed by stored stock"),
            obs("C04", "PASS", docs=[DOC]),
            obs("C07", "PASS"),
        ),
    )
    assert [b.code for b in failed.blockers] == ["MANDATORY_FAIL"]
    assert failed.findings[0].severity == "MANDATORY" and failed.eligible_for_review is False
    unverified = evaluate(
        ITEMS,
        clean(
            obs("C01", "PASS", docs=[DOC]),
            obs("C04", "NOT_VERIFIED", "Pump room locked during the visit"),
            obs("C07", "PASS"),
        ),
    )
    assert [b.code for b in unverified.blockers] == ["MANDATORY_NOT_VERIFIED"]


def test_na_only_where_permitted_and_always_flagged_for_review() -> None:
    cleaned, violations = validate_observations(
        ITEMS,
        [
            obs("C01", "NOT_APPLICABLE", "No means of escape needed here"),
            obs("C04", "PASS", docs=[DOC]),
            obs("C07", "PASS"),
        ],
        complete=True,
    )
    assert [v.pointer for v in violations] == ["/observations/0/result"]
    permitted = evaluate(
        ITEMS,
        clean(
            obs("C01", "PASS", docs=[DOC]),
            obs("C04", "NOT_APPLICABLE", "Single-storey shed below the fire-water threshold"),
            obs("C07", "NOT_APPLICABLE", "No vehicle access question arises"),
        ),
    )
    assert permitted.eligible_for_review is True and permitted.na_requiring_review == ("C04", "C07")
    # A bypassed client that sends NA for a non-permitted item still hits a blocker.
    forced = evaluate(
        ITEMS,
        [
            obs("C01", "NOT_APPLICABLE", "forced by a modified client"),
            obs("C04", "PASS", docs=[DOC]),
            obs("C07", "PASS"),
        ],
    )
    assert [b.code for b in forced.blockers] == ["NA_NOT_PERMITTED"]


def test_note_required_for_non_pass_and_evidence_required_for_pass() -> None:
    _, violations = validate_observations(ITEMS, [obs("C01", "FAIL", "short")], complete=False)
    assert [v.pointer for v in violations] == ["/observations/0/note"]
    missing_evidence = evaluate(
        ITEMS, clean(obs("C01", "PASS"), obs("C04", "PASS", docs=[DOC]), obs("C07", "PASS"))
    )
    assert [b.code for b in missing_evidence.blockers] == ["EVIDENCE_MISSING"]


def test_complete_submission_rejects_duplicates_unknown_and_missing_codes() -> None:
    _, violations = validate_observations(
        ITEMS,
        [obs("C01", "PASS", docs=[DOC]), obs("C01", "PASS", docs=[DOC]), obs("C99", "PASS")],
        complete=True,
    )
    assert sorted(v.code for v in violations) == ["duplicate", "missing", "missing", "unknown"]
    _, partial = validate_observations(ITEMS, [obs("C07", "PASS")], complete=False)
    assert partial == []


def test_evaluation_is_deterministic() -> None:
    observations = clean(
        obs("C01", "FAIL", "Escape route obstructed by stored stock"),
        obs("C04", "PASS", docs=[DOC]),
        obs("C07", "NOT_VERIFIED", "Could not reach the rear lane"),
    )
    assert (
        evaluate(ITEMS, observations).as_dict()
        == evaluate(ITEMS, list(reversed(observations))).as_dict()
    )
