from django.urls import path

from . import views

urlpatterns = [
    path("premises", views.PremisesListView.as_view(), name="premises"),
    path("premises/<uuid:premises_id>", views.PremisesDetailView.as_view(), name="premises-detail"),
    path("applications", views.ApplicationListView.as_view(), name="applications"),
    path(
        "applications/<uuid:application_id>",
        views.ApplicationDetailView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<uuid:application_id>/draft",
        views.DraftPatchView.as_view(),
        name="application-draft",
    ),
]
