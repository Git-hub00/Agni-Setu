from django.urls import path

from . import views

urlpatterns = [
    path("uploads", views.UploadListView.as_view(), name="uploads"),
    path(
        "uploads/<uuid:upload_id>/content", views.UploadContentView.as_view(), name="upload-content"
    ),
    path(
        "uploads/<uuid:upload_id>/complete",
        views.UploadCompleteView.as_view(),
        name="upload-complete",
    ),
    path(
        "documents/<uuid:document_id>", views.DocumentDetailView.as_view(), name="document-detail"
    ),
    path(
        "documents/<uuid:document_id>/access",
        views.DocumentAccessView.as_view(),
        name="document-access",
    ),
    path(
        "documents/<uuid:document_id>/detach",
        views.DocumentDetachView.as_view(),
        name="document-detach",
    ),
    path(
        "documents/<uuid:document_id>/content",
        views.DocumentContentView.as_view(),
        name="document-content",
    ),
]
