from django.urls import path

from .views import (
    ConflictDetailView,
    ConflictListView,
    ConflictResolveView,
    IntegrationDetailView,
    IntegrationListView,
    IntegrationTestView,
    PartnerEventView,
)

urlpatterns = [
    path("integrations", IntegrationListView.as_view(), name="integrations"),
    path(
        "integrations/<str:integration_ref>",
        IntegrationDetailView.as_view(),
        name="integration-detail",
    ),
    path(
        "integrations/<str:integration_ref>/test",
        IntegrationTestView.as_view(),
        name="integration-test",
    ),
    path(
        "integrations/<str:integration_ref>/events",
        PartnerEventView.as_view(),
        name="integration-events",
    ),
    path("integration-conflicts", ConflictListView.as_view(), name="integration-conflicts"),
    path(
        "integration-conflicts/<uuid:conflict_id>",
        ConflictDetailView.as_view(),
        name="integration-conflict-detail",
    ),
    path(
        "integration-conflicts/<uuid:conflict_id>/resolve",
        ConflictResolveView.as_view(),
        name="integration-conflict-resolve",
    ),
]
