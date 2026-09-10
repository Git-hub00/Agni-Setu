from django.urls import path

from . import delegation_views, views

urlpatterns = [
    path("auth/csrf", views.CsrfBootstrapView.as_view(), name="auth-csrf"),
    path("auth/otp/challenges", views.OtpChallengeView.as_view(), name="auth-otp-challenge"),
    path("auth/otp/verify", views.OtpVerifyView.as_view(), name="auth-otp-verify"),
    path("auth/oidc/start", views.OidcStartView.as_view(), name="auth-oidc-start"),
    path("auth/oidc/callback", views.OidcCallbackView.as_view(), name="auth-oidc-callback"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("me", views.MeView.as_view(), name="me"),
    path("delegations", delegation_views.DelegationListView.as_view(), name="delegations"),
    path(
        "delegations/<uuid:delegation_id>/confirm",
        delegation_views.DelegationConfirmView.as_view(),
        name="delegation-confirm",
    ),
    path(
        "delegations/<uuid:delegation_id>/revoke",
        delegation_views.DelegationRevokeView.as_view(),
        name="delegation-revoke",
    ),
]
