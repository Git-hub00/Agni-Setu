"""Finding materialisation from an accepted inspection report (FR-14 -> FR-17).

Called inside the report-acceptance transaction (B08 `SubmitReport`): every FAIL and every
mandatory NOT_VERIFIED observation becomes an OPEN finding unless an unresolved finding for the
same item already exists on the case (a reinspection re-observes the same deficiency; the
original finding and its history are retained)."""

from __future__ import annotations

from typing import Any

from agni.cases.models import Application

from ..models import Finding, FindingState


def materialise_findings(
    application: Application, report: Any, evaluation_findings: list[dict[str, Any]]
) -> list[Finding]:
    unresolved = {
        f.checklist_item_code
        for f in Finding.objects.filter(application=application).exclude(
            state=FindingState.VERIFIED_CLOSED
        )
    }
    created: list[Finding] = []
    for entry in evaluation_findings:
        code = str(entry["item_code"])
        if code in unresolved:
            continue
        created.append(
            Finding.objects.create(
                application=application,
                originating_report=report,
                checklist_item_code=code,
                severity=str(entry["severity"]),
                state=FindingState.OPEN,
                description=str(entry.get("note") or f"{code}: {entry.get('result')}"),
            )
        )
        unresolved.add(code)
    return created
