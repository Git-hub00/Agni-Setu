from django.urls import path

from . import case_views, views

urlpatterns = [
    path("premises", views.PremisesListView.as_view(), name="premises"),
    path("premises/<uuid:premises_id>", views.PremisesDetailView.as_view(), name="premises-detail"),
    path("applications", case_views.ApplicationListView.as_view(), name="applications"),
    path(
        "applications/<uuid:application_id>",
        case_views.ApplicationDetailView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<uuid:application_id>/draft",
        case_views.DraftPatchView.as_view(),
        name="application-draft",
    ),
    path(
        "applications/<uuid:application_id>/submit",
        case_views.SubmitView.as_view(),
        name="application-submit",
    ),
    path(
        "applications/<uuid:application_id>/timeline",
        case_views.TimelineView.as_view(),
        name="application-timeline",
    ),
    path(
        "applications/<uuid:application_id>/revisions",
        case_views.RevisionsView.as_view(),
        name="application-revisions",
    ),
    path(
        "applications/<uuid:application_id>/start-scrutiny",
        case_views.StartScrutinyView.as_view(),
        name="application-start-scrutiny",
    ),
    path(
        "applications/<uuid:application_id>/resolve-routing",
        case_views.ResolveRoutingView.as_view(),
        name="application-resolve-routing",
    ),
    path(
        "applications/<uuid:application_id>/withdraw",
        case_views.WithdrawView.as_view(),
        name="application-withdraw",
    ),
    path(
        "applications/<uuid:application_id>/holds",
        case_views.HoldCreateView.as_view(),
        name="application-holds",
    ),
    path("holds/<uuid:hold_id>/release", case_views.HoldReleaseView.as_view(), name="hold-release"),
    path("overview", case_views.OverviewView.as_view(), name="overview"),
]
