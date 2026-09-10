"""Policy governance commands (FR-27; API-096..102, API-123) on the kernel.

Lifecycle: DRAFT -> IN_REVIEW -> APPROVED -> SCHEDULED/ACTIVE -> RETIRED, IN_REVIEW -> RETURNED ->
DRAFT edits. Preparation is an ADMIN role action; every editor is a recorded material
contributor and none of them may approve (separation of duties). Approval needs the
`policy.approve` capability, the exact frozen candidate hash, a passed simulation for that hash,
a valid effective interval and no overlap with another effective version. Activation needs
`policy.activate`, locks the service activation fence (the same fence submission uses) and
bumps the service activation epoch.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Max
from django.utils.dateparse import parse_datetime

from agni.identity.authz import load_snapshot, require_capability, require_role
from agni.identity.domain.roles import Capability, RoleKey
from agni.platform.canonical import canonical_sha256
from agni.platform.commands import AuditEntry, CommandHandler, CommandOutcome, UnitOfWork
from agni.platform.errors import (
    InvalidTransition,
    PolicyReviewConflict,
    ResourceNotFound,
    SeparationOfDuties,
    ValidationFailed,
    Violation,
)

from ..domain.schema import SUPPORTED_SCHEMA_VERSIONS, require_valid_policy_payload
from ..domain.simulation import ENGINE_VERSION, SUITES, SuiteContext, run_suite
from ..models import (
    ContributorAction,
    Jurisdiction,
    PolicyArtifact,
    PolicyContributor,
    PolicySimulation,
    PolicyState,
    PolicyVersion,
    Service,
)
from ..selection import check_no_overlap, lock_service_fence


def _reason(payload: Mapping[str, Any], *, minimum: int = 10, maximum: int = 4000) -> str:
    reason = str(payload.get("reason", "")).strip()
    if not minimum <= len(reason) <= maximum:
        raise ValidationFailed(
            violations=[
                Violation(
                    "/reason", "length", f"explain the change in {minimum}-{maximum} characters"
                )
            ]
        )
    return reason


def _uuid(value: Any, pointer: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationFailed(
            violations=[Violation(pointer, "invalid", "must be a UUID")]
        ) from None


def _instant(value: Any, pointer: str, *, required: bool) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ValidationFailed(violations=[Violation(pointer, "required", "is required")])
        return None
    parsed = parse_datetime(str(value)) if isinstance(value, str) else None
    if parsed is None or parsed.tzinfo is None:
        raise ValidationFailed(
            violations=[Violation(pointer, "format", "must be an ISO 8601 UTC timestamp")]
        )
    return parsed


def _lock_policy(uow: UnitOfWork) -> PolicyVersion:
    # Lock only the version row: PostgreSQL refuses FOR UPDATE on the nullable side of an outer
    # join, so the optional jurisdiction is resolved lazily instead of via select_related.
    version = (
        PolicyVersion.objects.select_for_update(of=("self",))
        .select_related("service")
        .filter(pk=uow.envelope.target_id)
        .first()
    )
    if version is None:
        raise ResourceNotFound("Policy version not found")
    return version


def _record_contribution(version: PolicyVersion, uow: UnitOfWork, action: str) -> None:
    PolicyContributor.objects.get_or_create(
        policy_version=version,
        principal=uow.actor,
        command_id=uow.command_id,
        defaults={"action": action},
    )


def _policy_body(version: PolicyVersion) -> dict[str, Any]:
    return {
        "policy_version_id": str(version.pk),
        "service_key": version.service.key,
        "number": version.number,
        "state": version.state,
        "payload_sha256": version.payload_sha256,
        "review_candidate_sha256": version.review_candidate_sha256 or None,
        "effective_from": version.effective_from.isoformat() if version.effective_from else None,
        "effective_until": version.effective_until.isoformat() if version.effective_until else None,
        "version": version.version,
    }


class PreparePolicyDraft(CommandHandler[PolicyVersion]):
    """API-096: new lineage version in DRAFT with an editable payload. Target: the service."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN, RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return None

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        data = dict(uow.envelope.payload)
        unknown = set(data) - {
            "service_id",
            "base_policy_version_id",
            "schema_version",
            "payload",
            "source_references",
            "reason",
        }
        if unknown:
            raise ValidationFailed(
                violations=[
                    Violation(f"/{k}", "unknown_field", "unknown field") for k in sorted(unknown)
                ]
            )
        reason = _reason(data)
        service = (
            Service.objects.select_for_update()
            .filter(pk=_uuid(data.get("service_id"), "/service_id"))
            .first()
        )
        if service is None:
            raise ResourceNotFound("Service not found")
        schema_version = str(data.get("schema_version", ""))
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValidationFailed(
                violations=[
                    Violation("/schema_version", "unsupported", "unsupported schema version")
                ]
            )
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValidationFailed(
                violations=[Violation("/payload", "invalid", "must be an object")]
            )
        require_valid_policy_payload(payload)
        sources = data.get("source_references", [])
        if not isinstance(sources, list) or (payload.get("mode") != "DEMO" and not sources):
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/source_references", "required", "live policies need source references"
                    )
                ]
            )
        jurisdiction = Jurisdiction.objects.filter(code=payload["jurisdiction_key"]).first()
        if jurisdiction is None:
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/payload/jurisdiction_key",
                        "unknown",
                        "jurisdiction code is not registered",
                    )
                ]
            )
        base_id = data.get("base_policy_version_id")
        if (
            base_id
            and not PolicyVersion.objects.filter(
                pk=_uuid(base_id, "/base_policy_version_id"), service=service
            ).exists()
        ):
            raise ResourceNotFound("Base policy version not found")
        number = (
            PolicyVersion.objects.filter(service=service).aggregate(m=Max("number"))["m"] or 0
        ) + 1
        version = PolicyVersion.objects.create(
            service=service,
            jurisdiction=jurisdiction,
            number=number,
            state=PolicyState.DRAFT,
            payload=payload,
            payload_sha256=canonical_sha256(payload),
            schema_version=schema_version,
            source_references=sources,
            prepared_by=uow.actor,
        )
        _record_contribution(version, uow, ContributorAction.CREATE)
        return CommandOutcome(
            status=201,
            body=_policy_body(version),
            aggregate=version,
            created=True,
            audits=[
                AuditEntry(
                    "policy_version",
                    version.pk,
                    "policy.drafted",
                    {
                        "service_key": service.key,
                        "number": number,
                        "payload_sha256": version.payload_sha256,
                        "reason": reason[:200],
                    },
                )
            ],
        )


class PatchPolicyDraft(CommandHandler[PolicyVersion]):
    """API-098: replace the candidate payload while editable; the editor becomes a contributor."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN, RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return _lock_policy(uow)

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        if not target.is_editable:
            raise InvalidTransition(
                f"Policy version is {target.state}; only DRAFT/RETURNED are editable"
            )
        data = dict(uow.envelope.payload)
        reason = _reason(data)
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValidationFailed(
                violations=[Violation("/payload", "invalid", "must be a complete candidate object")]
            )
        require_valid_policy_payload(payload)
        if payload["jurisdiction_key"] != (
            target.jurisdiction.code if target.jurisdiction else None
        ):
            raise ValidationFailed(
                violations=[
                    Violation(
                        "/payload/jurisdiction_key",
                        "immutable",
                        "create a new lineage to change jurisdiction",
                    )
                ]
            )
        target.payload = payload
        target.payload_sha256 = canonical_sha256(payload)
        if "source_references" in data and isinstance(data["source_references"], list):
            target.source_references = data["source_references"]
        if target.state == PolicyState.RETURNED:
            target.state = PolicyState.DRAFT
        target.review_candidate_sha256 = ""
        target.save(
            update_fields=[
                "payload",
                "payload_sha256",
                "source_references",
                "state",
                "review_candidate_sha256",
                "updated_at",
            ]
        )
        _record_contribution(target, uow, ContributorAction.EDIT)
        return CommandOutcome(
            status=200,
            body=_policy_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "policy_version",
                    target.pk,
                    "policy.edited",
                    {"payload_sha256": target.payload_sha256, "reason": reason[:200]},
                )
            ],
        )


class SubmitPolicyForReview(CommandHandler[PolicyVersion]):
    """API-099: validate and freeze the candidate hash for independent review."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_role(load_snapshot(uow.actor, uow.now), RoleKey.ADMIN, RoleKey.SUPERVISOR)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return _lock_policy(uow)

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        if not target.is_editable:
            raise InvalidTransition(f"Policy version is {target.state}")
        reason = _reason(dict(uow.envelope.payload))
        require_valid_policy_payload(target.payload)
        _require_artifacts(target.payload)
        target.state = PolicyState.IN_REVIEW
        target.review_candidate_sha256 = target.payload_sha256
        target.save(update_fields=["state", "review_candidate_sha256", "updated_at"])
        return CommandOutcome(
            status=200,
            body=_policy_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "policy_version",
                    target.pk,
                    "policy.submitted_for_review",
                    {"candidate_sha256": target.review_candidate_sha256, "reason": reason[:200]},
                )
            ],
        )


def _require_artifacts(payload: Mapping[str, Any]) -> dict[str, PolicyArtifact]:
    refs = {
        "FORM": str(payload["form_schema_key"]),
        "CHECKLIST": str(payload["checklist_key"]),
        "CALENDAR": str(payload["calendar_key"]),
        "ROUTING": str(payload["routing_key"]),
    }
    resolved: dict[str, PolicyArtifact] = {}
    missing: list[Violation] = []
    for kind, key in refs.items():
        artifact = PolicyArtifact.objects.filter(kind=kind, key=key).order_by("-number").first()
        if artifact is None:
            missing.append(
                Violation(
                    f"/payload/{kind.lower()}_key",
                    "unknown_artifact",
                    f"no {kind} artifact with key {key}",
                )
            )
        else:
            resolved[kind] = artifact
    if missing:
        raise ValidationFailed(detail="Referenced artifacts are missing", violations=missing)
    return resolved


class RunPolicySimulation(CommandHandler[PolicyVersion]):
    """API-123: run an allowlisted deterministic suite against the exact frozen candidate."""

    def authorize(self, uow: UnitOfWork) -> None:
        snapshot = load_snapshot(uow.actor, uow.now)
        if not (
            snapshot.has_role(RoleKey.ADMIN)
            or snapshot.has_role(RoleKey.SUPERVISOR)
            or snapshot.grant_for(Capability.POLICY_APPROVE) is not None
        ):
            raise _forbidden()

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return _lock_policy(uow)

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        data = dict(uow.envelope.payload)
        reason = _reason(data, maximum=1000)
        suite_key = str(data.get("fixture_suite_key", ""))
        if suite_key not in SUITES:
            raise ValidationFailed(
                violations=[
                    Violation("/fixture_suite_key", "unknown_suite", "suite is not allowlisted")
                ]
            )
        candidate = str(data.get("candidate_sha256", ""))
        if candidate != target.payload_sha256:
            raise PolicyReviewConflict(
                "Candidate hash does not match the current candidate",
                extensions={"current_candidate_sha256": target.payload_sha256},
            )
        started = uow.now
        context = _suite_context(target.payload)
        passed, checks = run_suite(suite_key, target.payload, context)
        simulation = PolicySimulation.objects.create(
            policy_version=target,
            candidate_sha256=candidate,
            fixture_suite_key=suite_key,
            fixture_suite_version=SUITES[suite_key].version,
            engine_version=ENGINE_VERSION,
            initiated_by=uow.actor,
            started_at=started,
            completed_at=uow.now,
            passed=passed,
            result_json=[c.as_dict() for c in checks],
            correlation_id=uow.request_id,
        )
        return CommandOutcome(
            status=200,
            body={
                "simulation_id": str(simulation.pk),
                "candidate_sha256": candidate,
                "fixture_suite_key": suite_key,
                "fixture_suite_version": simulation.fixture_suite_version,
                "engine_version": ENGINE_VERSION,
                "started_at": started.isoformat(),
                "completed_at": simulation.completed_at.isoformat(),
                "checks": simulation.result_json,
                "passed": passed,
                "current_candidate_unchanged": True,
            },
            aggregate=target,
            audits=[
                AuditEntry(
                    "policy_version",
                    target.pk,
                    "policy.simulated",
                    {"suite": suite_key, "passed": passed, "reason": reason[:200]},
                )
            ],
        )


def _forbidden() -> Exception:
    from agni.platform.errors import Forbidden

    return Forbidden("This action requires a policy preparer role or approval grant")


def _suite_context(payload: Mapping[str, Any]) -> SuiteContext:
    def latest(kind: str, key: str) -> PolicyArtifact | None:
        return PolicyArtifact.objects.filter(kind=kind, key=key).order_by("-number").first()

    checklist = latest("CHECKLIST", str(payload.get("checklist_key", "")))
    calendar = latest("CALENDAR", str(payload.get("calendar_key", "")))
    routing = latest("ROUTING", str(payload.get("routing_key", "")))
    form = latest("FORM", str(payload.get("form_schema_key", "")))
    return SuiteContext(
        checklist_items=list((checklist.payload if checklist else {}).get("items", [])),
        calendar=calendar.payload if calendar else {},
        routing_entries=list((routing.payload if routing else {}).get("entries", [])),
        form_present=form is not None,
    )


class ApprovePolicy(CommandHandler[PolicyVersion]):
    """API-100: independent approval with interval validation and overlap rejection."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_capability(load_snapshot(uow.actor, uow.now), Capability.POLICY_APPROVE)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return _lock_policy(uow)

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        if target.state != PolicyState.IN_REVIEW:
            raise InvalidTransition(f"Policy version is {target.state}, not IN_REVIEW")
        data = dict(uow.envelope.payload)
        reason = _reason(data)
        if (
            PolicyContributor.objects.filter(policy_version=target, principal=uow.actor).exists()
            or target.prepared_by_id == uow.actor.pk
        ):
            raise SeparationOfDuties("A material contributor cannot approve this policy version")
        candidate = str(data.get("candidate_sha256", ""))
        if candidate != target.review_candidate_sha256 or candidate != target.payload_sha256:
            raise PolicyReviewConflict(
                "The candidate changed since review started; re-submit for review"
            )
        if not PolicySimulation.objects.filter(
            policy_version=target, candidate_sha256=candidate, passed=True
        ).exists():
            raise PolicyReviewConflict(
                "Approval requires a passed simulation for the exact candidate hash"
            )
        effective_from = _instant(data.get("effective_from"), "/effective_from", required=True)
        effective_until = _instant(data.get("effective_until"), "/effective_until", required=False)
        if effective_from is None:
            raise ValidationFailed(
                violations=[Violation("/effective_from", "required", "is required")]
            )
        if effective_until is not None and effective_until <= effective_from:
            raise ValidationFailed(
                violations=[
                    Violation("/effective_until", "interval", "must be after effective_from")
                ]
            )
        if target.payload.get("mode") != "DEMO":
            gate_evidence = data.get("reviewed_gate_evidence_ids")
            if not isinstance(gate_evidence, list) or not gate_evidence:
                raise ValidationFailed(
                    violations=[
                        Violation(
                            "/reviewed_gate_evidence_ids",
                            "required",
                            "live policy approval needs reviewed gate evidence (document 19)",
                        )
                    ]
                )
        closed_predecessor: PolicyVersion | None = None
        if data.get("close_predecessor") is True:
            # Deliberate supersession: the single open-ended effective predecessor that started
            # before the new interval is closed exactly at the new effective_from (half-open
            # intervals never overlap). Any other configuration is still an overlap error.
            predecessors = list(
                PolicyVersion.objects.select_for_update()
                .filter(
                    service_id=target.service_id,
                    jurisdiction=target.jurisdiction,
                    state__in=[PolicyState.APPROVED, PolicyState.SCHEDULED, PolicyState.ACTIVE],
                    effective_until__isnull=True,
                    effective_from__lt=effective_from,
                )
                .exclude(pk=target.pk)
            )
            if len(predecessors) == 1:
                closed_predecessor = predecessors[0]
                closed_predecessor.effective_until = effective_from
                closed_predecessor.version += 1
                closed_predecessor.save(update_fields=["effective_until", "version", "updated_at"])
        check_no_overlap(
            target.service_id,
            target.jurisdiction_id,
            effective_from,
            effective_until,
            exclude_id=target.pk,
        )
        target.state = PolicyState.APPROVED
        target.approved_by = uow.actor
        target.approved_at = uow.now
        target.approval_basis = reason
        target.effective_from = effective_from
        target.effective_until = effective_until
        target.save(
            update_fields=[
                "state",
                "approved_by",
                "approved_at",
                "approval_basis",
                "effective_from",
                "effective_until",
                "updated_at",
            ]
        )
        return CommandOutcome(
            status=200,
            body=_policy_body(target),
            aggregate=target,
            audits=[
                AuditEntry(
                    "policy_version",
                    target.pk,
                    "policy.approved",
                    {
                        "candidate_sha256": candidate,
                        "effective_from": effective_from.isoformat(),
                        "effective_until": effective_until.isoformat() if effective_until else None,
                        "closed_predecessor_id": (
                            str(closed_predecessor.pk) if closed_predecessor else None
                        ),
                    },
                ),
                *(
                    [
                        AuditEntry(
                            "policy_version",
                            closed_predecessor.pk,
                            "policy.interval_closed",
                            {
                                "effective_until": effective_from.isoformat(),
                                "successor_id": str(target.pk),
                            },
                        )
                    ]
                    if closed_predecessor
                    else []
                ),
            ],
        )


class ReturnPolicy(CommandHandler[PolicyVersion]):
    """API-101: reasoned return to the preparers; prior review events are preserved."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_capability(load_snapshot(uow.actor, uow.now), Capability.POLICY_APPROVE)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        return _lock_policy(uow)

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        if target.state != PolicyState.IN_REVIEW:
            raise InvalidTransition(f"Policy version is {target.state}, not IN_REVIEW")
        reason = _reason(dict(uow.envelope.payload))
        target.state = PolicyState.RETURNED
        target.returned_reason = reason
        target.save(update_fields=["state", "returned_reason", "updated_at"])
        return CommandOutcome(
            status=200,
            body=_policy_body(target),
            aggregate=target,
            audits=[
                AuditEntry("policy_version", target.pk, "policy.returned", {"reason": reason[:500]})
            ],
        )


class ActivatePolicy(CommandHandler[PolicyVersion]):
    """API-102: under the service activation fence, make an APPROVED version SCHEDULED (future)
    or ACTIVE (effective now) and bump the service activation epoch. The previous ACTIVE version
    whose interval has ended is RETIRED in the same transaction."""

    def authorize(self, uow: UnitOfWork) -> None:
        require_capability(load_snapshot(uow.actor, uow.now), Capability.POLICY_ACTIVATE)

    def lock_target(self, uow: UnitOfWork) -> PolicyVersion | None:
        version = _lock_policy(uow)
        lock_service_fence(version.service_id)
        return version

    def apply(self, uow: UnitOfWork, target: PolicyVersion | None) -> CommandOutcome[PolicyVersion]:
        if target is None:
            raise ResourceNotFound("Policy version not found")
        data = dict(uow.envelope.payload)
        reason = _reason(data)
        if target.state not in (PolicyState.APPROVED, PolicyState.SCHEDULED):
            raise InvalidTransition(
                f"Policy version is {target.state}; only APPROVED/SCHEDULED can be activated"
            )
        if str(data.get("approved_candidate_sha256", "")) != target.payload_sha256:
            raise PolicyReviewConflict("Approved candidate hash does not match")
        if target.effective_from is None:
            raise InvalidTransition("Approved version has no effective_from")
        check_no_overlap(
            target.service_id,
            target.jurisdiction_id,
            target.effective_from,
            target.effective_until,
            exclude_id=target.pk,
        )
        now = uow.now
        if target.effective_from > now:
            target.state = PolicyState.SCHEDULED
        else:
            target.state = PolicyState.ACTIVE
            target.activated_at = now
            PolicyVersion.objects.filter(
                service=target.service,
                jurisdiction=target.jurisdiction,
                state=PolicyState.ACTIVE,
                effective_until__isnull=False,
                effective_until__lte=now,
            ).exclude(pk=target.pk).update(state=PolicyState.RETIRED, retired_at=now)
        target.save(update_fields=["state", "activated_at", "updated_at"])
        service = target.service
        service.activation_epoch += 1
        service.active = True
        service.version += 1
        service.save(update_fields=["activation_epoch", "active", "version", "updated_at"])
        return CommandOutcome(
            status=200,
            body={**_policy_body(target), "service_activation_epoch": service.activation_epoch},
            aggregate=target,
            audits=[
                AuditEntry(
                    "policy_version",
                    target.pk,
                    "policy.activated",
                    {"state": target.state, "reason": reason[:200]},
                ),
                AuditEntry(
                    "service",
                    service.pk,
                    "service.activation_epoch_bumped",
                    {"activation_epoch": service.activation_epoch, "policy_number": target.number},
                ),
            ],
        )
