"""Typed domain errors mapped to the stable error catalogue (docs/08 s.7) and rendered as
RFC 9457 problem details at the HTTP boundary (docs/06 s.5).

Domain and application code raise these; nothing below the API layer imports DRF or HTTP
response types. Provider errors are mapped to a catalogue code, never surfaced raw.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import UUID


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    status: int
    title: str


# The complete public catalogue. Codes are stable identifiers; titles are safe defaults.
CATALOGUE: dict[str, ErrorSpec] = {
    spec.code: spec
    for spec in (
        ErrorSpec("MALFORMED_REQUEST", 400, "Request is malformed"),
        ErrorSpec("AUTHENTICATION_REQUIRED", 401, "Authentication is required"),
        ErrorSpec("SESSION_EXPIRED", 401, "Session has expired"),
        ErrorSpec("OTP_INVALID", 422, "Verification code is not valid"),
        ErrorSpec("OTP_EXPIRED", 422, "Verification code has expired"),
        ErrorSpec("OTP_THROTTLED", 429, "Too many verification attempts"),
        ErrorSpec("CSRF_FAILED", 403, "Request origin could not be verified"),
        ErrorSpec("FORBIDDEN", 403, "Action is not permitted"),
        ErrorSpec("RESOURCE_NOT_FOUND", 404, "Resource not found"),
        ErrorSpec("PRECONDITION_REQUIRED", 428, "Version precondition is required"),
        ErrorSpec("VERSION_CONFLICT", 412, "Resource has changed"),
        ErrorSpec("IDEMPOTENCY_CONFLICT", 409, "Command key was used with a different request"),
        ErrorSpec("COMMAND_IN_PROGRESS", 409, "The same command is still being processed"),
        ErrorSpec("INVALID_TRANSITION", 409, "Command is not permitted from the current state"),
        ErrorSpec("VALIDATION_FAILED", 422, "Validation failed"),
        ErrorSpec("POLICY_UNAVAILABLE", 409, "No approved applicable policy"),
        ErrorSpec("POLICY_AMBIGUOUS", 409, "More than one policy applies"),
        ErrorSpec("POLICY_REVIEW_CONFLICT", 409, "Policy review conflict"),
        ErrorSpec("POLICY_INTERVAL_OVERLAP", 409, "Policy activation interval overlaps"),
        ErrorSpec("SERVICE_DISABLED", 409, "Service feature is not enabled"),
        ErrorSpec("AUTHORITY_REVOKED", 403, "Authority is no longer valid"),
        ErrorSpec("AUTHORITY_SCOPE_MISMATCH", 403, "Authority does not cover this scope"),
        ErrorSpec("SEPARATION_OF_DUTIES", 403, "A different actor must perform this step"),
        ErrorSpec("ROUTING_UNRESOLVED", 409, "Case routing is unresolved"),
        ErrorSpec("ASSIGNMENT_CHANGED", 409, "Assignment has changed"),
        ErrorSpec("OFFICER_UNAVAILABLE", 409, "Officer is unavailable"),
        ErrorSpec("APPOINTMENT_CONFLICT", 409, "Appointment conflicts with another booking"),
        ErrorSpec("FILE_TOO_LARGE", 413, "File is too large"),
        ErrorSpec("FILE_TYPE_UNSUPPORTED", 415, "File type is not supported"),
        ErrorSpec("UPLOAD_INCOMPLETE", 409, "Upload is incomplete"),
        ErrorSpec("UPLOAD_EXPIRED", 410, "Upload reservation has expired"),
        ErrorSpec("FILE_QUARANTINED", 409, "File is awaiting security scan"),
        ErrorSpec("FILE_REJECTED", 422, "File was rejected"),
        ErrorSpec("EVIDENCE_INCOMPLETE", 422, "Mandatory evidence is missing"),
        ErrorSpec("CHECKLIST_INCOMPLETE", 422, "Checklist is incomplete"),
        ErrorSpec("MANDATORY_FINDINGS_OPEN", 409, "Mandatory findings are still open"),
        ErrorSpec("NOTICE_NOT_OPEN", 409, "Notice is not open"),
        ErrorSpec("RESPONSE_NOT_VERIFIED", 409, "Responses are not yet verified"),
        ErrorSpec("OFFLINE_PACKAGE_EXPIRED", 409, "Offline package has expired"),
        ErrorSpec("SYNC_SCHEMA_UNSUPPORTED", 422, "Offline schema is not supported"),
        ErrorSpec(
            "SYNC_PAYLOAD_CONFLICT", 409, "Operation was already accepted with other content"
        ),
        ErrorSpec("ISSUANCE_IN_PROGRESS", 409, "Issuance is already in progress"),
        ErrorSpec("EXTERNAL_OUTCOME_UNKNOWN", 409, "External outcome is unknown"),
        ErrorSpec("CERTIFICATE_STATUS_CONFLICT", 409, "Certificate status conflict"),
        ErrorSpec("VERIFICATION_UNAVAILABLE", 503, "Verification is currently unavailable"),
        ErrorSpec("EXPORT_EXPIRED", 410, "Export is no longer available"),
        ErrorSpec("INTEGRATION_SEQUENCE_GAP", 409, "Source event sequence gap"),
        ErrorSpec("INTEGRATION_SIGNATURE_INVALID", 401, "Partner signature is invalid"),
        ErrorSpec("RATE_LIMITED", 429, "Too many requests"),
        ErrorSpec("DEPENDENCY_UNAVAILABLE", 503, "A required dependency is unavailable"),
        ErrorSpec("INTERNAL_ERROR", 500, "Unexpected error"),
    )
}


@dataclass(frozen=True)
class Violation:
    """One field-level problem, addressed by JSON Pointer; never carries secret values."""

    pointer: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"pointer": self.pointer, "code": self.code, "message": self.message}


@dataclass
class DomainError(Exception):
    """Base error. Subclasses fix `code`; generic use passes `code` explicitly."""

    code: ClassVar[str] = "INTERNAL_ERROR"

    detail: str | None = None
    violations: Sequence[Violation] = field(default_factory=tuple)
    extensions: Mapping[str, Any] = field(default_factory=dict)
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if type(self).code not in CATALOGUE:
            raise ValueError(f"unknown error code {type(self).code!r}")
        super().__init__(self.detail or self.spec.title)

    @property
    def spec(self) -> ErrorSpec:
        return CATALOGUE[type(self).code]

    @property
    def status(self) -> int:
        return self.spec.status

    @property
    def title(self) -> str:
        return self.spec.title

    def to_problem(self, request_id: UUID | str | None) -> dict[str, Any]:
        """RFC 9457 body with project extensions (docs/06 s.5)."""
        body: dict[str, Any] = {
            "type": f"urn:agni-setu:problem:{type(self).code.lower().replace('_', '-')}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail or self.title,
            "code": type(self).code,
            "request_id": str(request_id) if request_id else None,
        }
        if self.violations:
            body["violations"] = [v.as_dict() for v in self.violations]
        if self.retry_after_seconds is not None:
            body["retry_after_seconds"] = self.retry_after_seconds
        for key, value in self.extensions.items():
            body.setdefault(key, value)
        return body


# Explicit subclasses (real types, so they can be used in annotations and `type[...]`).


class MalformedRequest(DomainError):
    code = "MALFORMED_REQUEST"


class AuthenticationRequired(DomainError):
    code = "AUTHENTICATION_REQUIRED"


class SessionExpired(DomainError):
    code = "SESSION_EXPIRED"


class OtpInvalid(DomainError):
    code = "OTP_INVALID"


class OtpExpired(DomainError):
    code = "OTP_EXPIRED"


class OtpThrottled(DomainError):
    code = "OTP_THROTTLED"


class CsrfFailed(DomainError):
    code = "CSRF_FAILED"


class Forbidden(DomainError):
    code = "FORBIDDEN"


class ResourceNotFound(DomainError):
    code = "RESOURCE_NOT_FOUND"


class PreconditionRequired(DomainError):
    code = "PRECONDITION_REQUIRED"


class VersionConflict(DomainError):
    code = "VERSION_CONFLICT"


class IdempotencyConflict(DomainError):
    code = "IDEMPOTENCY_CONFLICT"


class CommandInProgress(DomainError):
    code = "COMMAND_IN_PROGRESS"


class InvalidTransition(DomainError):
    code = "INVALID_TRANSITION"


class ValidationFailed(DomainError):
    code = "VALIDATION_FAILED"


class PolicyUnavailable(DomainError):
    code = "POLICY_UNAVAILABLE"


class PolicyAmbiguous(DomainError):
    code = "POLICY_AMBIGUOUS"


class PolicyReviewConflict(DomainError):
    code = "POLICY_REVIEW_CONFLICT"


class PolicyIntervalOverlap(DomainError):
    code = "POLICY_INTERVAL_OVERLAP"


class ServiceDisabled(DomainError):
    code = "SERVICE_DISABLED"


class AuthorityRevoked(DomainError):
    code = "AUTHORITY_REVOKED"


class AuthorityScopeMismatch(DomainError):
    code = "AUTHORITY_SCOPE_MISMATCH"


class SeparationOfDuties(DomainError):
    code = "SEPARATION_OF_DUTIES"


class RoutingUnresolved(DomainError):
    code = "ROUTING_UNRESOLVED"


class AssignmentChanged(DomainError):
    code = "ASSIGNMENT_CHANGED"


class OfficerUnavailable(DomainError):
    code = "OFFICER_UNAVAILABLE"


class AppointmentConflict(DomainError):
    code = "APPOINTMENT_CONFLICT"


class FileTooLarge(DomainError):
    code = "FILE_TOO_LARGE"


class FileTypeUnsupported(DomainError):
    code = "FILE_TYPE_UNSUPPORTED"


class UploadIncomplete(DomainError):
    code = "UPLOAD_INCOMPLETE"


class UploadExpired(DomainError):
    code = "UPLOAD_EXPIRED"


class FileQuarantined(DomainError):
    code = "FILE_QUARANTINED"


class FileRejected(DomainError):
    code = "FILE_REJECTED"


class EvidenceIncomplete(DomainError):
    code = "EVIDENCE_INCOMPLETE"


class OfflinePackageExpired(DomainError):
    code = "OFFLINE_PACKAGE_EXPIRED"


class SyncSchemaUnsupported(DomainError):
    code = "SYNC_SCHEMA_UNSUPPORTED"


class SyncPayloadConflict(DomainError):
    code = "SYNC_PAYLOAD_CONFLICT"


class MandatoryFindingsOpen(DomainError):
    code = "MANDATORY_FINDINGS_OPEN"


class NoticeNotOpen(DomainError):
    code = "NOTICE_NOT_OPEN"


class ResponseNotVerified(DomainError):
    code = "RESPONSE_NOT_VERIFIED"


class VerificationUnavailable(DomainError):
    code = "VERIFICATION_UNAVAILABLE"


class RateLimited(DomainError):
    code = "RATE_LIMITED"


class DependencyUnavailable(DomainError):
    code = "DEPENDENCY_UNAVAILABLE"


class InternalError(DomainError):
    code = "INTERNAL_ERROR"


class AppendOnlyViolation(RuntimeError):
    """Programming error: ordinary code tried to update or delete an append-only record."""
