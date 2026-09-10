"""Command kernel - the atomic transition algorithm (workflow s.9, architecture s.7, API s.4).

Every guarded command flows through `execute`:

    begin transaction
      lock principal authorization fence; recheck active state
      handler.authorize            (deny by default; scope hides existence)
      look up command receipt      (identical -> replay; different -> IDEMPOTENCY_CONFLICT)
      handler.lock_target          (FOR UPDATE; None for creations)
      compare expected version     (missing -> 428; stale -> 412)
      handler.apply                (pure guards + writes; returns outcome, audits, intents)
      bump aggregate version
      write audit rows             (failure aborts the whole command)
      write outbox intents
      write immutable receipt
    commit -> on_commit dispatcher wake-up

Handlers never manage transactions, never call providers, and never trust request-supplied
actors, roles, states or dates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction

from agni.identity.models import Principal

from . import audit, outbox
from .canonical import canonical_sha256, sha256_hex
from .clock import Clock, get_clock
from .errors import (
    AuthorityRevoked,
    CommandInProgress,
    IdempotencyConflict,
    MalformedRequest,
    PreconditionRequired,
    VersionConflict,
)
from .locks import load_locked_principal
from .models import CommandReceipt, VersionedModel

# Command aggregates: every VersionedModel plus the custom Principal (which carries its own
# `version` column but derives from AbstractBaseUser).
Versioned = VersionedModel | Principal

RECEIPT_RETENTION = timedelta(days=7)  # demo minimum for online commands (data model s.9)


@dataclass(frozen=True)
class ActorContext:
    """Who is acting, as established by the server (session/OIDC), never by the request body."""

    principal_id: UUID
    request_id: UUID


@dataclass(frozen=True)
class CommandEnvelope:
    actor: ActorContext
    command_name: str
    target_type: str
    target_id: UUID
    payload: Mapping[str, Any]
    idempotency_key: str | None
    expected_version: int | None = None

    @property
    def key_hash(self) -> str:
        if not self.idempotency_key:
            raise MalformedRequest("Idempotency-Key is required for commands")
        return sha256_hex(self.idempotency_key.encode("utf-8"))

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(
            {
                "command": self.command_name,
                "target_type": self.target_type,
                "target_id": self.target_id,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True)
class AuditEntry:
    entity_type: str
    entity_id: UUID
    action: str
    summary: Mapping[str, Any]
    authority_grant_id: UUID | None = None


@dataclass(frozen=True)
class OutboxIntent:
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: Mapping[str, Any]
    logical_action_id: UUID | None = None
    delay: timedelta = timedelta(0)


@dataclass
class CommandOutcome[T: Versioned]:
    """What a handler produced. `aggregate` is version-bumped by the kernel unless `created`."""

    status: int
    body: dict[str, Any]
    aggregate: T | None = None
    created: bool = False
    audits: Sequence[AuditEntry] = field(default_factory=tuple)
    intents: Sequence[OutboxIntent] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommandResult:
    status: int
    body: dict[str, Any]
    command_id: UUID
    accepted_at: datetime
    replayed: bool
    resulting_version: int | None


@dataclass
class UnitOfWork:
    """Facts and services available to a handler inside the transaction."""

    actor: Principal
    envelope: CommandEnvelope
    clock: Clock
    command_id: UUID

    @property
    def now(self) -> datetime:
        return self.clock.now()

    @property
    def request_id(self) -> UUID:
        return self.envelope.actor.request_id


class CommandHandler[T: Versioned](Protocol):
    def authorize(self, uow: UnitOfWork) -> None:
        """Raise Forbidden/ResourceNotFound/AuthorityRevoked; deny by default."""

    def lock_target(self, uow: UnitOfWork) -> T | None:
        """SELECT ... FOR UPDATE the aggregate (or None for creations)."""

    def apply(self, uow: UnitOfWork, target: T | None) -> CommandOutcome[T]:
        """Evaluate guards and write canonical state. No version bump, no receipts."""


def _replay(receipt: CommandReceipt) -> CommandResult:
    return CommandResult(
        status=receipt.result_status,
        body=dict(receipt.result_body),
        command_id=receipt.id,
        accepted_at=receipt.accepted_at,
        replayed=True,
        resulting_version=receipt.resulting_version,
    )


def execute[T: Versioned](
    envelope: CommandEnvelope, handler: CommandHandler[T], *, clock: Clock | None = None
) -> CommandResult:
    if not envelope.idempotency_key:
        raise MalformedRequest(
            "Idempotency-Key is required for commands", extensions={"header": "Idempotency-Key"}
        )
    clock = clock or get_clock()
    key_hash = envelope.key_hash
    request_hash = envelope.request_sha256
    command_id = uuid4()

    with transaction.atomic():
        actor = load_locked_principal(envelope.actor.principal_id)
        if not actor.is_active:
            raise AuthorityRevoked("Account is disabled")

        uow = UnitOfWork(actor=actor, envelope=envelope, clock=clock, command_id=command_id)
        handler.authorize(uow)

        existing = CommandReceipt.objects.filter(
            principal=actor,
            target_type=envelope.target_type,
            target_id=envelope.target_id,
            command_name=envelope.command_name,
            key_hash=key_hash,
        ).first()
        if existing is not None:
            if existing.request_sha256 != request_hash:
                raise IdempotencyConflict(
                    "This Idempotency-Key was already used with a different request"
                )
            return _replay(existing)

        target = handler.lock_target(uow)
        if target is not None:
            if envelope.expected_version is None:
                raise PreconditionRequired("Send If-Match with the current resource version")
            if target.version != envelope.expected_version:
                raise VersionConflict(
                    "The resource has changed since it was read",
                    extensions={"current_version": target.version},
                )

        outcome = handler.apply(uow, target)
        now = clock.now()

        resulting_version: int | None = None
        if outcome.aggregate is not None:
            if not outcome.created:
                outcome.aggregate.version += 1
                outcome.aggregate.save(update_fields=["version", "updated_at"])
            resulting_version = outcome.aggregate.version

        for entry in outcome.audits:
            audit.record_audit(
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                action=entry.action,
                actor_id=actor.pk,
                request_id=envelope.actor.request_id,
                at=now,
                summary=entry.summary,
                authority_grant_id=entry.authority_grant_id,
            )
        for intent in outcome.intents:
            outbox.enqueue_intent(
                event_type=intent.event_type,
                aggregate_type=intent.aggregate_type,
                aggregate_id=intent.aggregate_id,
                payload=intent.payload,
                available_at=now + intent.delay,
                logical_action_id=intent.logical_action_id,
            )

        body = dict(outcome.body)
        body.setdefault("command_id", str(command_id))
        body.setdefault("accepted_at", now.isoformat())
        body.setdefault("replayed", False)
        if resulting_version is not None:
            body.setdefault("version", resulting_version)

        try:
            with transaction.atomic():
                receipt = CommandReceipt.objects.create(
                    id=command_id,
                    principal=actor,
                    target_type=envelope.target_type,
                    target_id=envelope.target_id,
                    command_name=envelope.command_name,
                    key_hash=key_hash,
                    request_sha256=request_hash,
                    result_status=outcome.status,
                    result_body=body,
                    resulting_version=resulting_version,
                    accepted_at=now,
                    retain_until=now + RECEIPT_RETENTION,
                )
        except IntegrityError as exc:
            # Only reachable if a concurrent writer bypassed the principal fence; never guess.
            raise CommandInProgress(
                "The same command is being processed", retry_after_seconds=2
            ) from exc

        if outcome.intents:
            outbox.schedule_dispatcher_wakeup()

    return CommandResult(
        status=receipt.result_status,
        body=body,
        command_id=receipt.id,
        accepted_at=receipt.accepted_at,
        replayed=False,
        resulting_version=resulting_version,
    )
