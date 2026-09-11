"""Certificate register, artifact access and public verification (API-067/068/069/073;
UI-16/17/18)."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.http import HttpResponse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agni.cases.selectors import visible_applications
from agni.documents.adapters import get_object_store
from agni.documents.ports import ObjectNotFound, ObjectStoreUnavailable
from agni.identity.authz import load_snapshot
from agni.identity.contacts import decrypt_contact
from agni.identity.models import Principal, PrincipalKind
from agni.platform import audit
from agni.platform.api.views import ApiView, client_ip, ok
from agni.platform.clock import get_clock
from agni.platform.correlation import current_request_id
from agni.platform.errors import (
    AuthenticationRequired,
    DependencyUnavailable,
    InvalidTransition,
    RateLimited,
    ResourceNotFound,
    VerificationUnavailable,
)

from ..adapters import WATERMARK
from ..application.issuance import verification_url
from ..application.registry import (
    EFFECTIVE_STATUSES,
    certificate_detail,
    certificate_summary,
    pending_issuance_card,
    public_projection,
)
from ..models import Certificate, IssuanceRequest, IssuanceState

ACCESS_SALT = "agni.certificate-access"
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


def _principal(request: Request) -> Principal:
    user = request.user
    if not isinstance(user, Principal):
        raise AuthenticationRequired()
    return user


def _visible_certificate(principal: Principal, certificate_id: UUID, now: Any) -> Certificate:
    snapshot = load_snapshot(principal, now)
    certificate = (
        Certificate.objects.select_related(
            "application__premises", "application__owner_queue", "artifact", "issuance_request"
        )
        .filter(pk=certificate_id, application__in=visible_applications(snapshot, now))
        .first()
    )
    if certificate is None:
        raise ResourceNotFound("Certificate not found")
    return certificate


class CertificateListView(ApiView):
    """API-067: scoped authoritative register plus pending-issuance cards. A reserved number is
    never listed as an issued active instrument."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        snapshot = load_snapshot(principal, now)
        visible = visible_applications(snapshot, now)
        queryset = (
            Certificate.objects.filter(application__in=visible)
            .select_related("application__premises", "artifact")
            .order_by("-issued_at")
        )
        outcome = request.query_params.get("outcome_kind")
        if outcome:
            queryset = queryset.filter(outcome_kind=outcome)
        term = (request.query_params.get("q") or "").strip()
        if term:
            queryset = queryset.filter(certificate_number__iexact=term) | queryset.filter(
                application__premises__display_name__icontains=term
            )
        wanted = request.query_params.get("effective_status")
        items = [certificate_summary(c, now) for c in queryset.distinct()[:200]]
        if wanted in EFFECTIVE_STATUSES:
            items = [i for i in items if i["effective_status"] == wanted]
        pending = (
            IssuanceRequest.objects.filter(application__in=visible)
            .exclude(state=IssuanceState.PUBLISHED)
            .select_related("application__premises")
            .order_by("-created_at")[:100]
        )
        return ok(
            {
                "items": items,
                "pending_issuance": [pending_issuance_card(r) for r in pending],
                "as_of": now.isoformat(),
                "demo_notice": WATERMARK if settings.SERVICE_MODE == "DEMO" else None,
            },
            request,
        )


class CertificateDetailView(ApiView):
    """API-068: provenance, derived effective status and allowed lifecycle actions."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, certificate_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        certificate = _visible_certificate(principal, certificate_id, now)
        staff = principal.kind != PrincipalKind.APPLICANT
        body = certificate_detail(certificate, now, staff=staff)
        # Holders and scoped readers may copy the public verification link (UI-17); the token
        # is recovered from its ciphertext here and never listed anywhere else.
        body["verification_url"] = verification_url(
            decrypt_contact(certificate.verification_token_ciphertext)
        )
        response = ok(body, request)
        response["ETag"] = certificate.etag
        return response


class CertificateAccessView(ApiView):
    """API-069: reauthorise the reader, audit, and issue a short-lived principal-bound ticket
    for the labelled artifact. The public token is never used for this."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, certificate_id: UUID) -> Response:
        principal = _principal(request)
        now = get_clock().now()
        certificate = _visible_certificate(principal, certificate_id, now)
        artifact = certificate.artifact
        if artifact is None:
            raise InvalidTransition("The instrument artifact is not available yet")
        ttl = int(settings.AGNI_UPLOADS["ACCESS_TTL_SECONDS"])
        ticket = signing.TimestampSigner(salt=ACCESS_SALT).sign(f"{certificate.pk}:{principal.pk}")
        with transaction.atomic():
            audit.record_audit(
                entity_type="certificate",
                entity_id=certificate.pk,
                action="certificate.access_granted",
                actor_id=UUID(str(principal.pk)),
                request_id=current_request_id() or UUID(int=0),
                at=now,
                summary={"mode": artifact.mode, "purpose": "DOWNLOAD", "ttl_seconds": ttl},
            )
        return ok(
            {
                "url": f"/api/v1/certificates/{certificate.pk}/artifact?ticket={quote(ticket)}",
                "expires_in_seconds": ttl,
                "mode": artifact.mode,
                "media_type": artifact.media_type,
                "sha256": artifact.sha256,
                "label": WATERMARK if certificate.is_demo else "Issued instrument",
            },
            request,
        )


class CertificateArtifactView(ApiView):
    """Ticketed byte retrieval of the immutable artifact (the ticket is bound to the reader)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, certificate_id: UUID) -> HttpResponse:
        principal = _principal(request)
        now = get_clock().now()
        ttl = int(settings.AGNI_UPLOADS["ACCESS_TTL_SECONDS"])
        ticket = request.query_params.get("ticket", "")
        try:
            value = signing.TimestampSigner(salt=ACCESS_SALT).unsign(ticket, max_age=ttl)
        except signing.BadSignature as exc:
            raise ResourceNotFound("Artifact access ticket is not valid") from exc
        if value != f"{certificate_id}:{principal.pk}":
            raise ResourceNotFound("Artifact access ticket is not valid")
        certificate = _visible_certificate(principal, certificate_id, now)
        artifact = certificate.artifact
        if artifact is None:
            raise InvalidTransition("The instrument artifact is not available yet")
        store = get_object_store()
        try:
            data = b"".join(store.read(artifact.object_key, max_bytes=MAX_ARTIFACT_BYTES))
        except ObjectStoreUnavailable as exc:
            raise DependencyUnavailable("Artifact storage is temporarily unavailable") from exc
        except ObjectNotFound as exc:
            raise ResourceNotFound("Artifact object is missing") from exc
        if hashlib.sha256(data).hexdigest() != artifact.sha256:
            # The bytes behind the immutable identity changed: never serve them as the instrument.
            raise DependencyUnavailable("Artifact integrity check failed")
        suffix = "-DEMO" if certificate.is_demo else ""
        response = HttpResponse(data, content_type=artifact.media_type)
        response["Content-Disposition"] = (
            f'attachment; filename="{certificate.certificate_number}{suffix}.pdf"'
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Agni-Artifact-Mode"] = artifact.mode
        response["X-Content-Type-Options"] = "nosniff"
        return response


def _rate_limit(ip: str) -> None:
    """Per-IP window in the disposable store. Store outage -> fail closed (no assertion)."""
    key = f"verify:{ip}"
    try:
        added = cache.add(key, 1, timeout=60)
        count = 1 if added else cache.incr(key)
    except Exception as exc:  # noqa: BLE001 - any store failure must fail closed
        raise VerificationUnavailable(
            "Verification is temporarily unavailable; try again shortly"
        ) from exc
    if count > int(settings.PUBLIC_VERIFY_RATE_LIMIT):
        raise RateLimited("Too many verification requests", retry_after_seconds=60)


class PublicVerificationView(ApiView):
    """API-073: minimal, non-cacheable authoritative assertion. Unknown != revoked; an outage
    never yields an active assertion."""

    permission_classes = [AllowAny]

    def get(self, request: Request, token: str) -> Response:
        now = get_clock().now()
        _rate_limit(client_ip(request))
        value = token.strip()
        if not (8 <= len(value) <= 200):
            raise ResourceNotFound("Record not found")
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        try:
            certificate = (
                Certificate.objects.select_related("application__premises")
                .filter(verification_token_hash=digest)
                .first()
            )
            if (
                certificate is None
                and settings.PUBLIC_LOOKUP_PROFILE == "TOKEN_OR_NUMBER"
                and settings.SERVICE_MODE == "DEMO"
            ):
                certificate = (
                    Certificate.objects.select_related("application__premises")
                    .filter(certificate_number=value.upper())
                    .first()
                )
        except DatabaseError as exc:
            raise VerificationUnavailable(
                "The registry cannot be reached; no assertion is made"
            ) from exc
        if certificate is None:
            raise ResourceNotFound("Record not found")
        response = ok(public_projection(certificate, now), request)
        response["Cache-Control"] = "no-store"
        return response
