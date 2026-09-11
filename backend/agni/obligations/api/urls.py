from django.urls import path

from . import views

urlpatterns = [
    path("obligations", views.ObligationListView.as_view(), name="obligations"),
    path(
        "obligations/<uuid:obligation_id>",
        views.ObligationDetailView.as_view(),
        name="obligation-detail",
    ),
    path(
        "obligations/<uuid:obligation_id>/escalations",
        views.EscalationCreateView.as_view(),
        name="obligation-escalations",
    ),
    path(
        "escalations/<uuid:escalation_id>/acknowledge",
        views.EscalationAcknowledgeView.as_view(),
        name="escalation-acknowledge",
    ),
]
