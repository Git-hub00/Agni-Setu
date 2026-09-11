from django.urls import path

from .views import (
    CertificateAccessView,
    CertificateArtifactView,
    CertificateDetailView,
    CertificateListView,
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
        "public/certificates/<str:token>",
        PublicVerificationView.as_view(),
        name="public-verification",
    ),
]
