"""Root URL configuration.

Base API path is /api/v1 (docs/06_API_AND_EVENT_CONTRACTS.md s.1). Demo-only routes are
registered only when demo controls are enabled outside production (ADR-15).
"""

from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

from agni.platform import health
from agni.platform.api import audit_views, operations

api_v1: list[URLPattern | URLResolver] = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    # Operations (API-103..106, UI-20) - operations administrator only.
    path("jobs", operations.JobListView.as_view(), name="jobs"),
    path("jobs/<uuid:job_id>", operations.JobDetailView.as_view(), name="job-detail"),
    path("jobs/<uuid:job_id>/retry", operations.JobRetryView.as_view(), name="job-retry"),
    path(
        "jobs/<uuid:job_id>/reconcile", operations.JobReconcileView.as_view(), name="job-reconcile"
    ),
    # Audit reader (API-085/086, UI-23) - scoped staff only; every read is audited.
    path("audit-events", audit_views.AuditListView.as_view(), name="audit-events"),
    path(
        "audit-events/<uuid:audit_event_id>",
        audit_views.AuditDetailView.as_view(),
        name="audit-event-detail",
    ),
    path("", include("agni.identity.api.urls")),
    path("", include("agni.policies.api.urls")),
    path("", include("agni.cases.api.urls")),
    path("", include("agni.documents.api.urls")),
    path("", include("agni.inspections.api.urls")),
    path("", include("agni.notices.api.urls")),
    path("", include("agni.obligations.api.urls")),
    path("", include("agni.notifications.api.urls")),
    path("", include("agni.offline.api.urls")),
    path("", include("agni.decisions.api.urls")),
    path("", include("agni.certificates.api.urls")),
    path("", include("agni.support.api.urls")),
    path("", include("agni.reporting.api.urls")),
    path("", include("agni.integrations.api.urls")),
]

if settings.ENABLE_DEMO_CONTROLS and settings.APP_ENV != "production":
    from agni.notifications.api.demo_views import DemoInboxView

    api_v1.append(path("demo/inbox", DemoInboxView.as_view(), name="demo-inbox"))

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/", include((api_v1, "api"), namespace="api")),
]
