from django.urls import path

from . import views

urlpatterns = [
    path(
        "inspections/<uuid:inspection_id>/offline-package",
        views.OfflinePackageView.as_view(),
        name="inspection-offline-package",
    ),
    path("sync/operations", views.SyncOperationsView.as_view(), name="sync-operations"),
    path(
        "sync/operations/<uuid:operation_id>",
        views.SyncOperationDetailView.as_view(),
        name="sync-operation-detail",
    ),
    path(
        "inspections/<uuid:inspection_id>/conflicts",
        views.ConflictProposalView.as_view(),
        name="inspection-conflicts",
    ),
    path("conflicts", views.ConflictListView.as_view(), name="conflicts"),
    path(
        "conflicts/<uuid:conflict_id>/resolve",
        views.ConflictResolveView.as_view(),
        name="conflict-resolve",
    ),
]
