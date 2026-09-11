"""Scheduler process (docs/08 s.5): due-obligation scan every 30 s, outbox dispatch and
reconciliation every 60 s (engineering defaults; overridable). Safe to run more than once: row
locks and unique threshold/job identities make duplicate instances harmless.

Usage: manage.py run_schedulers --once | --loop [--scan-interval 30] [--dispatch-interval 60]
"""

from __future__ import annotations

import signal
import time
from typing import Any

from django.core.management.base import BaseCommand

import agni.notifications.application.fanout  # noqa: F401  (registers job kinds)
import agni.obligations.application.scheduler as scheduler
from agni.platform import dispatch
from agni.platform.clock import get_clock


class Command(BaseCommand):
    help = "Run the due-obligation scanner and the outbox dispatcher."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--scan-interval", type=float, default=30.0)
        parser.add_argument("--dispatch-interval", type=float, default=60.0)

    def handle(self, *args: Any, **options: Any) -> None:
        stop = {"flag": False}

        def _stop(_signum: int, _frame: Any) -> None:
            stop["flag"] = True

        if options["loop"]:
            signal.signal(signal.SIGTERM, _stop)
            signal.signal(signal.SIGINT, _stop)
        last_dispatch = 0.0
        while True:
            now = get_clock().now()
            scan = scheduler.scan_due_obligations(now=now)
            if scan["created"]:
                self.stdout.write(
                    f"[scheduler] thresholds created={scan['created']} scanned={scan['scanned']}"
                )
            if options["once"] or time.monotonic() - last_dispatch >= options["dispatch_interval"]:
                report = dispatch.dispatch_pending(now=now)
                last_dispatch = time.monotonic()
                if report.scanned:
                    self.stdout.write(
                        f"[dispatch] scanned={report.scanned} published={report.published} "
                        f"failed={report.failed}"
                    )
            if not options["loop"] or stop["flag"]:
                break
            time.sleep(max(1.0, float(options["scan_interval"])))
