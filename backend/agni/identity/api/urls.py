from django.urls import path

from . import delegation_views, staff_views, views

urlpatterns = [
    # Staff and authority governance (API-087..093, UI-21).
    path("staff", staff_views.StaffListView.as_view(), name="staff"),
    path("staff/invitations", staff_views.StaffInvitationView.as_view(), name="staff-invitations"),
    path("staff/<uuid:staff_id>", staff_views.StaffDetailView.as_view(), name="staff-detail"),
    path(
        "staff/<uuid:staff_id>/deactivate",
        staff_views.StaffDeactivateView.as_view(),
        name="staff-deactivate",
    ),
    path(
        "staff/<uuid:staff_id>/reactivate",
        staff_views.StaffReactivateView.as_view(),
        name="staff-reactivate",
    ),
    path("authority-grants", staff_views.GrantListView.as_view(), name="authority-grants"),
    path(
        "authority-grants/<uuid:grant_id>/approve",
        staff_views.GrantApproveView.as_view(),
        name="authority-grant-approve",
    ),
    path(
        "authority-grants/<uuid:grant_id>/revoke",
        staff_views.GrantRevokeView.as_view(),
        name="authority-grant-revoke",
    ),
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
