"""Root URL configuration.

Base API path is /api/v1 (docs/06_API_AND_EVENT_CONTRACTS.md s.1). Health probes are the
only routes at B00/B01; business module routers are mounted here as their phases land.
"""

from django.urls import URLPattern, URLResolver, include, path

from agni.platform import health

api_v1: list[URLPattern | URLResolver] = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
]

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/", include((api_v1, "api"), namespace="api")),
]
