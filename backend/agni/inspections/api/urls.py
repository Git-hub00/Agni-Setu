from django.urls import path

from . import views

urlpatterns = [
    path("inspections", views.InspectionListView.as_view(), name="inspections"),
    path(
        "inspections/<uuid:inspection_id>",
        views.InspectionDetailView.as_view(),
        name="inspection-detail",
    ),
    path(
        "inspections/<uuid:inspection_id>/schedule",
        views.ScheduleView.as_view(),
        name="inspection-schedule",
    ),
    path(
        "inspections/<uuid:inspection_id>/reassign",
        views.ReassignView.as_view(),
        name="inspection-reassign",
    ),
    path(
        "inspections/<uuid:inspection_id>/cancel",
        views.CancelView.as_view(),
        name="inspection-cancel",
    ),
    path(
        "inspections/<uuid:inspection_id>/check-in",
        views.CheckInView.as_view(),
        name="inspection-check-in",
    ),
    path(
        "inspections/<uuid:inspection_id>/fail-visit",
        views.FailVisitView.as_view(),
        name="inspection-fail-visit",
    ),
    path(
        "applications/<uuid:application_id>/require-inspection",
        views.RequireInspectionView.as_view(),
        name="application-require-inspection",
    ),
    path("schedule", views.ScheduleWindowView.as_view(), name="schedule"),
    path("officers", views.OfficersView.as_view(), name="officers"),
    path(
        "staff/<uuid:staff_id>/availability",
        views.AvailabilityView.as_view(),
        name="staff-availability",
    ),
]
