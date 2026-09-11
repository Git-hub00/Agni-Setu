from django.urls import path

from .views import (
    AppealsView,
    SupportRoutesView,
    TicketDetailView,
    TicketListView,
    TicketMessagesView,
    TicketStatusView,
)

urlpatterns = [
    path("tickets", TicketListView.as_view(), name="tickets"),
    path("tickets/<uuid:ticket_id>", TicketDetailView.as_view(), name="ticket-detail"),
    path("tickets/<uuid:ticket_id>/messages", TicketMessagesView.as_view(), name="ticket-messages"),
    path("tickets/<uuid:ticket_id>/status", TicketStatusView.as_view(), name="ticket-status"),
    path("support/routes", SupportRoutesView.as_view(), name="support-routes"),
    path("appeals", AppealsView.as_view(), name="appeals"),
    path("appeals/<uuid:appeal_id>/decisions", AppealsView.as_view(), name="appeal-decisions"),
]
