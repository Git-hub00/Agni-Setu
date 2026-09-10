"""Applicant OTP service (FR-01; security s.2).

Start: normalise contact, enforce anti-abuse limits (fail closed if the limit store is down),
supersede older open challenges for the same contact/purpose, store a keyed MAC over
(challenge id, purpose, code), hand the code to the provider port. Responses are
enumeration-safe: the same shape whether or not an account exists.

Verify: one atomic row lock decides expiry, consumption, supersession and attempt budget;
attempt increments persist even when verification fails; a correct code consumes the
challenge exactly once and binds/creates the applicant principal.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from agni.notifications.adapters import get_otp_sender
from agni.notifications.ports import OtpMessage
from agni.platform.clock import Clock
from agni.platform.errors import (
    DependencyUnavailable,
    DomainError,
    OtpExpired,
    OtpInvalid,
    OtpThrottled,
)

from .contacts import NormalizedContact, encrypt_contact, normalize_contact
from .models import ContactIdentity, OtpChallenge, OtpPurpose, Principal, PrincipalKind

PEPPER_VERSION = "v1"


@dataclass(frozen=True)
class OtpPolicy:
    lifetime: timedelta = timedelta(minutes=5)
    max_attempts: int = 5
    resend_cooldown: timedelta = timedelta(seconds=60)
    sends_per_contact_per_hour: int = 5
    sends_per_ip_per_hour: int = 20


def policy_from_settings() -> OtpPolicy:
    cfg = getattr(settings, "AGNI_OTP", {})
    return OtpPolicy(
        lifetime=timedelta(seconds=int(cfg.get("LIFETIME_SECONDS", 300))),
        max_attempts=int(cfg.get("MAX_ATTEMPTS", 5)),
        resend_cooldown=timedelta(seconds=int(cfg.get("RESEND_COOLDOWN_SECONDS", 60))),
        sends_per_contact_per_hour=int(cfg.get("SENDS_PER_CONTACT_PER_HOUR", 5)),
        sends_per_ip_per_hour=int(cfg.get("SENDS_PER_IP_PER_HOUR", 20)),
    )


@dataclass(frozen=True)
class ChallengeStarted:
    challenge_id: UUID
    masked_destination: str
    expires_at: datetime
    resend_available_at: datetime


def _code_mac(challenge_id: UUID, purpose: str, code: str) -> str:
    pepper = settings.OTP_PEPPER.encode("utf-8")
    return hmac.new(pepper, f"{challenge_id}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()


def _limit(key: str, limit: int, window_seconds: int, retry_after: int) -> None:
    """Sliding-window-ish counter in the disposable store. Outage -> fail closed."""
    try:
        added = cache.add(key, 1, timeout=window_seconds)
        count = 1 if added else cache.incr(key)
    except Exception as exc:  # noqa: BLE001 - any store failure must fail closed
        raise DependencyUnavailable("Abuse-control store unavailable; try again shortly") from exc
    if count > limit:
        raise OtpThrottled("Too many verification codes requested", retry_after_seconds=retry_after)


def _cooldown(key: str, seconds: int) -> None:
    try:
        if not cache.add(key, 1, timeout=seconds):
            raise OtpThrottled(
                "Please wait before requesting another code", retry_after_seconds=seconds
            )
    except OtpThrottled:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DependencyUnavailable("Abuse-control store unavailable; try again shortly") from exc


def start_challenge(
    *,
    channel: str,
    contact: str,
    purpose: str,
    source_ip: str,
    clock: Clock,
    principal: Principal | None = None,
    policy: OtpPolicy | None = None,
) -> ChallengeStarted:
    policy = policy or policy_from_settings()
    if purpose not in OtpPurpose.values:
        raise OtpInvalid()
    normalized = normalize_contact(channel, contact)
    lookup = normalized.lookup_hmac
    now = clock.now()

    _limit(f"otp:ip:{source_ip}", policy.sends_per_ip_per_hour, 3600, 3600)
    _limit(f"otp:contact:{lookup}", policy.sends_per_contact_per_hour, 3600, 3600)
    _cooldown(f"otp:resend:{lookup}:{purpose}", int(policy.resend_cooldown.total_seconds()))

    code = f"{secrets.randbelow(10**6):06d}"
    with transaction.atomic():
        OtpChallenge.objects.filter(
            contact_lookup_hmac=lookup,
            purpose=purpose,
            consumed_at__isnull=True,
            superseded_at__isnull=True,
        ).update(superseded_at=now)
        challenge = OtpChallenge(
            contact_lookup_hmac=lookup,
            channel=normalized.channel,
            purpose=purpose,
            pepper_version=PEPPER_VERSION,
            principal=principal,
            expires_at=now + policy.lifetime,
            max_attempts=policy.max_attempts,
        )
        challenge.code_mac = _code_mac(challenge.id, purpose, code)
        challenge.save()
        get_otp_sender().send(
            OtpMessage(
                channel=normalized.channel,
                destination=normalized.value,
                destination_masked=normalized.masked,
                destination_lookup_hmac=lookup,
                purpose=purpose,
                code=code,
                challenge_id=challenge.id,
                expires_in_minutes=max(1, int(policy.lifetime.total_seconds() // 60)),
            )
        )
    return ChallengeStarted(
        challenge_id=challenge.id,
        masked_destination=normalized.masked,
        expires_at=challenge.expires_at,
        resend_available_at=now + policy.resend_cooldown,
    )


@dataclass(frozen=True)
class Verified:
    principal: Principal
    contact: NormalizedContact | None
    challenge: OtpChallenge


def verify_challenge(*, challenge_id: UUID | str, code: str, clock: Clock) -> Verified:
    """Consume a challenge exactly once. Every failure is generic (OTP_INVALID) except a
    clearly expired challenge; unknown ids look like wrong codes."""
    try:
        cid = UUID(str(challenge_id))
    except ValueError:
        raise OtpInvalid() from None
    now = clock.now()
    failure: type[DomainError] | None = None
    verified: Verified | None = None
    # The atomic block decides and PERSISTS the outcome (including a failed-attempt increment);
    # the error is raised only after the block commits so a wrong code can never be retried
    # without consuming attempt budget.
    with transaction.atomic():
        challenge = OtpChallenge.objects.select_for_update().filter(pk=cid).first()
        if challenge is None or challenge.consumed_at or challenge.superseded_at:
            failure = OtpInvalid
        elif challenge.expires_at <= now:
            failure = OtpExpired
        elif challenge.attempt_count >= challenge.max_attempts:
            failure = OtpInvalid
        else:
            presented = _code_mac(challenge.id, challenge.purpose, (code or "").strip())
            challenge.attempt_count += 1
            if not hmac.compare_digest(challenge.code_mac, presented):
                challenge.save(update_fields=["attempt_count"])
                failure = OtpInvalid
            else:
                challenge.consumed_at = now
                challenge.save(update_fields=["attempt_count", "consumed_at"])
                principal, contact = _bind_principal(challenge, now)
                verified = Verified(principal=principal, contact=contact, challenge=challenge)
    if failure is not None or verified is None:
        raise (failure or OtpInvalid)()
    return verified


def _bind_principal(
    challenge: OtpChallenge, now: datetime
) -> tuple[Principal, NormalizedContact | None]:
    """SIGN_IN: find the principal owning this verified contact or create an applicant.
    CONTACT_CHANGE binds the new contact to the requesting principal (step-up handled by caller)."""
    if challenge.purpose == OtpPurpose.CONTACT_CHANGE:
        if challenge.principal is None:
            raise OtpInvalid()
        return challenge.principal, None

    existing = (
        ContactIdentity.objects.select_related("principal")
        .filter(
            channel=challenge.channel,
            lookup_hmac=challenge.contact_lookup_hmac,
            replaced_at__isnull=True,
        )
        .first()
    )
    if existing is not None:
        return existing.principal, None

    principal = Principal.objects.create_principal(
        kind=PrincipalKind.APPLICANT,
        display_name="Applicant",
        login_key=f"contact:{challenge.contact_lookup_hmac}",
    )
    # The plaintext is not available here (only the MAC); the API layer that received the
    # contact stores the encrypted value via `record_verified_contact` right after verify.
    principal.verified_contact_ref = None
    principal.save(update_fields=["verified_contact_ref", "updated_at"])
    return principal, None


def record_verified_contact(
    principal: Principal, contact: NormalizedContact, now: datetime
) -> ContactIdentity:
    """Persist the encrypted verified contact for a principal (idempotent per active lookup)."""
    existing = ContactIdentity.objects.filter(
        principal=principal,
        channel=contact.channel,
        lookup_hmac=contact.lookup_hmac,
        replaced_at__isnull=True,
    ).first()
    if existing is not None:
        if existing.verified_at is None:
            existing.verified_at = now
            existing.save(update_fields=["verified_at"])
        return existing
    ciphertext, key_version = encrypt_contact(contact.value)
    identity = ContactIdentity.objects.create(
        principal=principal,
        channel=contact.channel,
        ciphertext=ciphertext,
        lookup_hmac=contact.lookup_hmac,
        key_version=key_version,
        verified_at=now,
    )
    principal.verified_contact_ref = identity.id
    principal.save(update_fields=["verified_contact_ref", "updated_at"])
    return identity
