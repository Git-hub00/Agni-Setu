"""Workload model for the performance protocol (docs/11 s.7): 70 % scoped reads, 20 % draft /
response style mutations (represented by support tickets - a real kernel command with receipt,
audit and outbox), 10 % inspection / review reads by staff. Sessions are established ONCE by
`scripts/ops/measure_load.py` (real OTP + Keycloak sign-ins) and handed over through the
environment, so the run measures the API, not the identity providers or their abuse limits.

Run headless (reduced workload; the declared 100-user / 10,000-case protocol needs a larger
host - see status21 s.3s):
  locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 2m --host http://127.0.0.1:5173
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

APPLICANT_SESSION = os.environ.get("LOAD_APPLICANT_SESSION", "")
APPLICANT_CSRF = os.environ.get("LOAD_APPLICANT_CSRF", "")
STAFF_SESSION = os.environ.get("LOAD_STAFF_SESSION", "")
STAFF_CSRF = os.environ.get("LOAD_STAFF_CSRF", "")
CASE_IDS = [c for c in os.environ.get("LOAD_CASE_IDS", "").split(",") if c]
STAFF_CASE_IDS = [c for c in os.environ.get("LOAD_STAFF_CASE_IDS", "").split(",") if c]


class ApplicantUser(HttpUser):
    """Scoped reads (weight 7) and ticket mutations (weight 2)."""

    weight = 9
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.client.cookies.set("sessionid", APPLICANT_SESSION)
        self.client.cookies.set("csrftoken", APPLICANT_CSRF)
        self.client.headers.update({"X-CSRFToken": APPLICANT_CSRF})

    @task(3)
    def list_cases(self) -> None:
        self.client.get("/api/v1/applications", name="GET /applications")

    @task(2)
    def case_detail(self) -> None:
        if CASE_IDS:
            case_id = random.choice(CASE_IDS)  # noqa: S311 - workload sampling, not security
            self.client.get(f"/api/v1/applications/{case_id}", name="GET /applications/{id}")

    @task(1)
    def overview(self) -> None:
        self.client.get("/api/v1/overview", name="GET /overview")

    @task(1)
    def notifications(self) -> None:
        self.client.get("/api/v1/notifications", name="GET /notifications")

    @task(2)
    def open_ticket(self) -> None:
        self.client.post(
            "/api/v1/tickets",
            json={
                "category": "HOW_TO",
                "subject": "Load drill question",
                "description": "Synthetic load-drill ticket; no real request behind it.",
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="POST /tickets",
        )


class SupervisorUser(HttpUser):
    """Inspection / review reads (weight 1)."""

    weight = 1
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.client.cookies.set("sessionid", STAFF_SESSION)
        self.client.cookies.set("csrftoken", STAFF_CSRF)
        self.client.headers.update({"X-CSRFToken": STAFF_CSRF})

    @task(2)
    def queue(self) -> None:
        self.client.get("/api/v1/inspections", name="GET /inspections (staff)")

    @task(1)
    def reviews(self) -> None:
        self.client.get(
            "/api/v1/applications?status=REVIEW_PENDING",
            name="GET /applications?status=REVIEW_PENDING (staff)",
        )

    @task(1)
    def case(self) -> None:
        if STAFF_CASE_IDS:
            case_id = random.choice(STAFF_CASE_IDS)  # noqa: S311 - workload sampling
            self.client.get(
                f"/api/v1/applications/{case_id}", name="GET /applications/{id} (staff)"
            )
