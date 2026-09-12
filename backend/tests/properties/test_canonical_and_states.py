"""Property tests (Hypothesis) for pure kernel functions: canonical hashing, lock ordering,
state vocabulary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from agni.cases.domain.states import (
    TERMINAL_STATES,
    TRANSITIONS,
    ApplicationStatus,
    allowed_transitions,
)
from agni.platform.canonical import canonical_json, canonical_sha256
from agni.platform.locks import sorted_unique

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.text(max_size=40),
    st.uuids(),
    st.datetimes(
        min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
    ),
    st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=6), st.dictionaries(st.text(max_size=12), children, max_size=6)
    ),
    max_leaves=30,
)


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(st.text(max_size=12), json_values, max_size=8))
def test_canonical_hash_is_independent_of_key_order(payload: dict[str, object]) -> None:
    items = list(payload.items())
    reversed_payload = dict(reversed(items))
    assert canonical_sha256(payload) == canonical_sha256(reversed_payload)
    assert len(canonical_sha256(payload)) == 64


@settings(max_examples=100, deadline=None)
@given(json_values)
def test_canonical_json_is_deterministic_and_utf8(value: object) -> None:
    first = canonical_json(value)
    second = canonical_json(value)
    assert first == second
    first.decode("utf-8")


@settings(max_examples=100, deadline=None)
@given(st.lists(st.uuids(), max_size=20))
def test_sorted_unique_is_sorted_and_deduplicated(ids: list[UUID]) -> None:
    result = sorted_unique(ids)
    assert result == sorted(set(ids))
    assert all(a < b for a, b in zip(result, result[1:], strict=False))


def test_state_vocabulary_is_exactly_the_eleven_states() -> None:
    assert [s.value for s in ApplicationStatus] == [
        "DRAFT",
        "SUBMITTED",
        "SCRUTINY",
        "INFO_REQUIRED",
        "INSPECTION_PENDING",
        "REVIEW_PENDING",
        "COMPLIANCE_PENDING",
        "APPROVED_PENDING_ISSUE",
        "COMPLETED",
        "REJECTED",
        "WITHDRAWN",
    ]


@given(st.sampled_from(list(ApplicationStatus)))
# PROP-01 (structural part: the transition table admits exactly the permitted moves; the
# per-command guard is exercised by every integration test that asserts an unchanged state)
def test_terminal_states_have_no_outgoing_transitions(state: ApplicationStatus) -> None:
    outgoing = allowed_transitions(state)
    if state in TERMINAL_STATES:
        assert outgoing == []
    else:
        assert outgoing, f"{state} must have at least one authorized transition"


def test_no_transition_targets_draft_and_ids_are_unique() -> None:
    assert all(target is not ApplicationStatus.DRAFT for _, _, _, target, _ in TRANSITIONS)
    ids = [tid for tid, *_ in TRANSITIONS]
    assert len(ids) == len(set(ids))
