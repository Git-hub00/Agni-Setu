from django.urls import path

from . import views

urlpatterns = [
    path("services", views.ServiceCatalogueView.as_view(), name="services"),
    path(
        "services/<uuid:service_id>/applicability",
        views.ApplicabilityView.as_view(),
        name="service-applicability",
    ),
    path("policies", views.PolicyListView.as_view(), name="policies"),
    path("policies/<uuid:policy_id>", views.PolicyDetailView.as_view(), name="policy-detail"),
    path(
        "policies/<uuid:policy_id>/submit-review",
        views.PolicySubmitReviewView.as_view(),
        name="policy-submit-review",
    ),
    path(
        "policies/<uuid:policy_id>/simulate",
        views.PolicySimulateView.as_view(),
        name="policy-simulate",
    ),
    path(
        "policies/<uuid:policy_id>/approve",
        views.PolicyApproveView.as_view(),
        name="policy-approve",
    ),
    path(
        "policies/<uuid:policy_id>/return", views.PolicyReturnView.as_view(), name="policy-return"
    ),
    path(
        "policies/<uuid:policy_id>/activate",
        views.PolicyActivateView.as_view(),
        name="policy-activate",
    ),
]
