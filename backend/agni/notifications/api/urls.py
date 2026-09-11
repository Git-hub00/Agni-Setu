from django.urls import path

from . import views

urlpatterns = [
    path("notifications", views.NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/read-through",
        views.ReadThroughView.as_view(),
        name="notifications-read-through",
    ),
    path(
        "notifications/<uuid:notification_id>/read",
        views.NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("me/preferences", views.PreferencesView.as_view(), name="me-preferences"),
]
