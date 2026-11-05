from django.urls import path

from apps.accounts import api

urlpatterns = [
    path("auth/csrf", api.csrf),
    path("auth/register", api.register),
    path("auth/login", api.login_view),
    path("auth/logout", api.logout_view),
    path("auth/account-deactivation/proposals", api.account_deactivation_proposals),
    path(
        "auth/account-deactivation/proposals/<uuid:proposal_id>/confirm",
        api.confirm_account_deactivation,
    ),
    path("me", api.me),
]
