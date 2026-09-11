from django.urls import path

from .views import (
    ExportAccessView,
    ExportArtifactView,
    ExportDetailView,
    ExportListView,
    MetricsView,
)

urlpatterns = [
    path("reports/summary", MetricsView.as_view(), name="reports-summary"),
    path("exports", ExportListView.as_view(), name="exports"),
    path("exports/<uuid:export_id>", ExportDetailView.as_view(), name="export-detail"),
    path("exports/<uuid:export_id>/access", ExportAccessView.as_view(), name="export-access"),
    path("exports/<uuid:export_id>/artifact", ExportArtifactView.as_view(), name="export-artifact"),
]
