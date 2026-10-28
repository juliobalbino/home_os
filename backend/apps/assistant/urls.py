from django.urls import path

from apps.assistant.views import (
    AssistantDisconnectView,
    AssistantRequestView,
    AssistantStatusView,
)

urlpatterns = [
    path("assistant/status", AssistantStatusView.as_view(), name="assistant-status"),
    path(
        "assistant/disconnect",
        AssistantDisconnectView.as_view(),
        name="assistant-disconnect",
    ),
    path(
        "households/<uuid:household_id>/assistant",
        AssistantRequestView.as_view(),
        name="household-assistant",
    ),
]
