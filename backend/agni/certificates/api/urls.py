from django.urls import path

from .views import (
    CertificateAccessView,
    CertificateArtifactView,
    CertificateDetailView,
    CertificateListView,
    CertificateRenewalView,
    CertificateStatusActionView,
    ConditionalRouteView,
    DeclarationsView,
    PublicVerificationView,
)

urlpatterns = [
    path("certificates", CertificateListView.as_view(), name="certificates"),
    path(
        "certificates/<uuid:certificate_id>",
        CertificateDetailView.as_view(),
        name="certificate-detail",
    ),
    path(
        "certificates/<uuid:certificate_id>/access",
        CertificateAccessView.as_view(),
        name="certificate-access",
    ),
    path(
        "certificates/<uuid:certificate_id>/artifact",
        CertificateArtifactView.as_view(),
        name="certificate-artifact",
    ),
    path(
        "certificates/<uuid:certificate_id>/status-actions",
        CertificateStatusActionView.as_view(),
        name="certificate-status-actions",
    ),
    path(
        "certificates/<uuid:certificate_id>/renewals",
        CertificateRenewalView.as_view(),
        name="certificate-renewals",
    ),
    path(
        "certificates/<uuid:certificate_id>/declarations",
        DeclarationsView.as_view(),
        name="certificate-declarations",
    ),
    path(
        "applications/<uuid:application_id>/external-registration",
        ConditionalRouteView.as_view(),
        name="application-external-registration",
    ),
    path(
        "public/certificates/<str:token>",
        PublicVerificationView.as_view(),
        name="public-verification",
    ),
]
