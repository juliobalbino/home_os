from django.urls import path

from apps.accounts import api

urlpatterns = [
    path("auth/csrf", api.csrf),
    path("auth/register", api.register),
    path("auth/login", api.login_view),
    path("auth/logout", api.logout_view),
    path("me", api.me),
]
