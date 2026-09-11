from django.urls import path

from . import views

urlpatterns = [
    path(
        "applications/<uuid:application_id>/notices",
        views.NoticeListView.as_view(),
        name="application-notices",
    ),
    path("notices/<uuid:notice_id>", views.NoticeDetailView.as_view(), name="notice-detail"),
    path(
        "notices/<uuid:notice_id>/responses",
        views.NoticeResponsesView.as_view(),
        name="notice-responses",
    ),
    path(
        "notices/<uuid:notice_id>/accept-information",
        views.AcceptInformationView.as_view(),
        name="notice-accept-information",
    ),
    path(
        "notice-items/<uuid:item_id>/review",
        views.ItemReviewView.as_view(),
        name="notice-item-review",
    ),
    path(
        "applications/<uuid:application_id>/findings",
        views.FindingListView.as_view(),
        name="application-findings",
    ),
    path(
        "findings/<uuid:finding_id>/verify",
        views.FindingVerifyView.as_view(),
        name="finding-verify",
    ),
    path(
        "applications/<uuid:application_id>/complete-corrections",
        views.CompleteCorrectionsView.as_view(),
        name="application-complete-corrections",
    ),
    path(
        "applications/<uuid:application_id>/reinspect",
        views.ReinspectView.as_view(),
        name="application-reinspect",
    ),
]
