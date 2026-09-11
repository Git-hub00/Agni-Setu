"""Root URL configuration.

Base API path is /api/v1 (docs/06_API_AND_EVENT_CONTRACTS.md s.1). Demo-only routes are
registered only when demo controls are enabled outside production (ADR-15).
"""

from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

from agni.platform import health
from agni.platform.api import operations

api_v1: list[URLPattern | URLResolver] = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    # Operations skeleton (API-103/104, UI-20) - operations administrator only.
    path("jobs", operations.JobListView.as_view(), name="jobs"),
    path("jobs/<uuid:job_id>", operations.JobDetailView.as_view(), name="job-detail"),
    path("", include("agni.identity.api.urls")),
    path("", include("agni.policies.api.urls")),
    path("", include("agni.cases.api.urls")),
    path("", include("agni.documents.api.urls")),
    path("", include("agni.inspections.api.urls")),
    path("", include("agni.notices.api.urls")),
    path("", include("agni.obligations.api.urls")),
    path("", include("agni.notifications.api.urls")),
]

if settings.ENABLE_DEMO_CONTROLS and settings.APP_ENV != "production":
    from agni.notifications.api.demo_views import DemoInboxView

    api_v1.append(path("demo/inbox", DemoInboxView.as_view(), name="demo-inbox"))

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/", include((api_v1, "api"), namespace="api")),
]
