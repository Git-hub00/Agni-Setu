"""Operator recovery for an issuance request in RECONCILIATION_REQUIRED (docs/16 s.6).

Resumes the SAME issuance identity: the job looks the signer up by the stable request id before
any resubmission; no new decision, certificate number or verification token is created.
The HTTP recovery commands (API-105/106) arrive with B14; this command is the B12 path.

Usage: manage.py reconcile_issuance <issuance_request_id> [--note "..."]
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from agni.certificates.application.issuance import reconcile_issuance
from agni.platform.clock import get_clock
from agni.platform.errors import DomainError


class Command(BaseCommand):
    help = "Resume the same issuance request after an unknown/invalid signing outcome."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("issuance_request_id")
        parser.add_argument("--note", default="operator-triggered reconciliation")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            request_id = UUID(str(options["issuance_request_id"]))
        except ValueError as exc:
            raise CommandError("issuance_request_id must be a UUID") from exc
        try:
            job = reconcile_issuance(request_id, now=get_clock().now(), note=options["note"])
        except DomainError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"issuance {request_id}: job {job.logical_action_id} set PENDING "
            f"(attempts so far {job.attempt_count}); run process_jobs to continue"
        )
