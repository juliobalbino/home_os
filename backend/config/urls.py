from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.health.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.households.urls")),
    path("api/v1/", include("apps.finance.urls")),
    path("api/v1/", include("apps.shopping.urls")),
    path("api/v1/", include("apps.chores.urls")),
    path("api/v1/", include("apps.assistant.urls")),
]
