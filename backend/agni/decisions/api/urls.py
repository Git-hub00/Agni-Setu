from django.urls import path

from .views import DecisionReadinessView, DecisionsView

urlpatterns = [
    path(
        "applications/<uuid:application_id>/decision-readiness",
        DecisionReadinessView.as_view(),
        name="decision-readiness",
    ),
    path(
        "applications/<uuid:application_id>/decisions",
        DecisionsView.as_view(),
        name="decisions",
    ),
]
