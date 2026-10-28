from django.urls import path

from apps.assistant.views import (
    AssistantDisconnectView,
    AssistantHelperDownloadView,
    AssistantPairingCollectionView,
    AssistantPairingDetailView,
    AssistantPairingClaimView,
    AssistantPairingCompleteView,
    AssistantRequestView,
    AssistantStatusView,
)

urlpatterns = [
    path(
        "assistant/connect/helper",
        AssistantHelperDownloadView.as_view(),
        name="assistant-helper-download",
    ),
    path(
        "assistant/connect/pairings/complete",
        AssistantPairingCompleteView.as_view(),
        name="assistant-pairing-complete",
    ),
    path(
        "assistant/connect/pairings/claim",
        AssistantPairingClaimView.as_view(),
        name="assistant-pairing-claim",
    ),
    path(
        "assistant/connect/pairings",
        AssistantPairingCollectionView.as_view(),
        name="assistant-pairings",
    ),
    path(
        "assistant/connect/pairings/<uuid:pairing_id>",
        AssistantPairingDetailView.as_view(),
        name="assistant-pairing-detail",
    ),
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
