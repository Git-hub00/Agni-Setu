"""Durable job worker (docs/08 s.3-5). Polls the `logical_job` table; the database is the source
of truth, so this loop is also the recovery path when broker wake-ups are lost. Runs in the
`worker` container (Compose `app` profile) or once from the shell.

Usage: manage.py process_jobs --once | --loop [--interval 5] [--limit 10] [--kind document.scan]
"""

from __future__ import annotations

import signal
import time
from typing import Any

from django.core.management.base import BaseCommand

import agni.certificates.application.issuance  # noqa: F401  (certificate.issue kind)
import agni.documents.scanning  # noqa: F401  (importing registers the job kind)
import agni.integrations.application.commands  # noqa: F401  (integration.test kind)
import agni.integrations.application.inbox  # noqa: F401  (integration.apply kind)
import agni.notifications.application.fanout  # noqa: F401  (fan-out + delivery kinds)
import agni.obligations.application.scheduler  # noqa: F401  (threshold kind)
import agni.reporting.application.exports  # noqa: F401  (export.generate kind)
from agni.platform import jobs
from agni.platform.clock import get_clock


class Command(BaseCommand):
    help = "Process due durable jobs (scan, later dispatch/notifications)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--once", action="store_true", help="Run one pass and exit")
        parser.add_argument("--loop", action="store_true", help="Poll until SIGTERM/SIGINT")
        parser.add_argument("--interval", type=float, default=5.0)
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--kind", action="append", default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        owner = jobs.default_owner()
        stop = {"flag": False}

        def _stop(_signum: int, _frame: Any) -> None:
            stop["flag"] = True

        if options["loop"]:
            signal.signal(signal.SIGTERM, _stop)
            signal.signal(signal.SIGINT, _stop)
        registered = ", ".join(sorted(jobs.handlers())) or "-"
        self.stdout.write(f"[jobs] worker {owner} handlers: {registered}")
        while True:
            report = jobs.run_due_jobs(
                owner=owner, limit=options["limit"], kinds=options["kind"], clock=get_clock()
            )
            if report.claimed:
                self.stdout.write(
                    f"[jobs] claimed={report.claimed} complete={report.completed} "
                    f"retry={report.retried} dead={report.dead} reconcile={report.reconcile} "
                    f"lost={report.lost} kinds={report.kinds}"
                )
            if not options["loop"] or stop["flag"]:
                break
            time.sleep(max(0.5, float(options["interval"])))
