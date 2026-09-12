"""Read-only integrity report for a restore drill (docs/12 s.6). Run against the RESTORED
database (DATABASE_URL pointing at the isolated target): schema compatibility, record counts,
canonical relationships (completed cases <-> published certificates <-> approving decisions),
audit hash chains for a sample of entities, and object-store availability + hash equality for
certificate artifacts and recent document versions. Exit code 1 when any check fails; never
writes.

Usage: manage.py restore_integrity_report [--sample 50] [--json]
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from agni.cases.models import Application
from agni.certificates.models import Certificate, IssuanceRequest
from agni.decisions.models import Decision
from agni.documents.adapters import get_object_store
from agni.documents.models import DocumentVersion
from agni.documents.ports import ObjectNotFound, ObjectStoreError
from agni.platform import audit
from agni.platform.models import AuditEvent, LogicalJob, OutboxMessage


class Command(BaseCommand):
    help = "Read-only integrity report for a restored database (docs/12 s.6 restore drill)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--sample", type=int, default=50)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        sample = int(options["sample"])
        failures: list[str] = []
        report: dict[str, Any] = {"database": connection.settings_dict.get("NAME")}

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        report["schema"] = {"unapplied_migrations": len(plan)}
        if plan:
            failures.append(f"{len(plan)} migrations unapplied on the restored database")

        report["counts"] = {
            "applications": Application.objects.count(),
            "decisions": Decision.objects.count(),
            "issuance_requests": IssuanceRequest.objects.count(),
            "certificates": Certificate.objects.count(),
            "document_versions": DocumentVersion.objects.count(),
            "audit_events": AuditEvent.objects.count(),
            "outbox_messages": OutboxMessage.objects.count(),
            "logical_jobs": LogicalJob.objects.count(),
        }

        completed = list(
            Application.objects.filter(status="COMPLETED").values_list("pk", flat=True)
        )
        certified = set(
            Certificate.objects.filter(application_id__in=completed).values_list(
                "application_id", flat=True
            )
        )
        without = [str(pk) for pk in completed if pk not in certified]
        duplicates = [
            str(pk) for pk in completed if Certificate.objects.filter(application_id=pk).count() > 1
        ]
        report["relationships"] = {
            "completed_applications": len(completed),
            "completed_without_certificate": without,
            "completed_with_more_than_one_certificate": duplicates,
            "certificates_without_approving_decision": [
                str(c.pk)
                for c in Certificate.objects.select_related("issuance_request__decision")
                if c.issuance_request is None or c.issuance_request.decision.kind != "APPROVE"
            ],
        }
        if (
            without
            or duplicates
            or report["relationships"]["certificates_without_approving_decision"]
        ):
            failures.append("canonical relationship mismatch (see relationships)")

        entities = list(
            AuditEvent.objects.order_by("-timestamp")
            .values_list("entity_type", "entity_id")
            .distinct()[: sample * 3]
        )
        seen: set[tuple[str, Any]] = set()
        checked = 0
        broken: list[str] = []
        for entity_type, entity_id in entities:
            if (entity_type, entity_id) in seen or checked >= sample:
                continue
            seen.add((entity_type, entity_id))
            checked += 1
            if not audit.verify_chain(entity_type, entity_id):
                broken.append(f"{entity_type}:{entity_id}")
        report["audit_chains"] = {"checked": checked, "broken": broken}
        if broken:
            failures.append(f"{len(broken)} audit chains do not verify")

        store = get_object_store()
        artifact_checks: list[dict[str, Any]] = []
        for certificate in Certificate.objects.select_related("artifact").order_by("-issued_at")[
            :sample
        ]:
            artifact = certificate.artifact
            entry: dict[str, Any] = {"certificate": certificate.certificate_number}
            number = certificate.certificate_number
            if artifact is None:
                entry["status"] = "NO_ARTIFACT_ROW"
                failures.append(f"certificate {number} has no artifact row")
            else:
                try:
                    data = b"".join(store.read(artifact.object_key, max_bytes=20 * 1024 * 1024))
                    digest = hashlib.sha256(data).hexdigest()
                    entry["status"] = "OK" if digest == artifact.sha256 else "HASH_MISMATCH"
                    if digest != artifact.sha256:
                        failures.append(f"artifact hash mismatch for {number}")
                except ObjectNotFound:
                    entry["status"] = "OBJECT_MISSING"
                    failures.append(f"artifact object missing for {number}")
                except ObjectStoreError as exc:
                    entry["status"] = f"STORE_ERROR:{type(exc).__name__}"
                    failures.append(f"object store error for {number}")
            artifact_checks.append(entry)
        report["certificate_artifacts"] = artifact_checks

        document_checks: dict[str, Any] = {"checked": 0, "missing": [], "hash_mismatch": []}
        for version in DocumentVersion.objects.order_by("-created_at")[:sample]:
            document_checks["checked"] += 1
            try:
                data = b"".join(store.read(version.object_key, max_bytes=20 * 1024 * 1024))
            except ObjectNotFound:
                document_checks["missing"].append(str(version.pk))
                continue
            except ObjectStoreError:
                document_checks["missing"].append(str(version.pk))
                continue
            if hashlib.sha256(data).hexdigest() != version.sha256:
                document_checks["hash_mismatch"].append(str(version.pk))
        report["document_versions"] = document_checks
        if document_checks["missing"] or document_checks["hash_mismatch"]:
            failures.append("document object availability / hash mismatch")

        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["status"] = "PASS" if not failures else "FAIL"
        report["failures"] = failures
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
        else:
            for key, value in report.items():
                self.stdout.write(f"{key}: {json.dumps(value, default=str)}")
        if failures:
            raise SystemExit(1)
