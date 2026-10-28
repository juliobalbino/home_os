from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.configuration import (
    assistant_configuration_status,
    assistant_is_ready,
)
from apps.assistant.models import ChatGPTConnection
from apps.assistant.services import create_response, disconnect_user
from apps.households.permissions import require_membership


class AssistantStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        connections = ChatGPTConnection.objects.filter(user=request.user).order_by(
            "-updated_at"
        )
        connection = connections.first()
        connected = False
        credential_error = False
        if assistant_is_ready():
            for candidate in connections.filter(
                status__in=("connected", "pending_configuration")
            ):
                if "chatgpt.tokens.use.direct" not in candidate.scopes:
                    continue
                try:
                    credentials = candidate.get_credentials()
                except Exception:
                    credential_error = True
                    continue
                if credentials.get("access_token") and credentials.get("refresh_token"):
                    connected = True
                    break
        return Response(
            {
                "enabled": assistant_is_ready(),
                "connected": connected,
                "can_disconnect": connections.exclude(
                    credentials_ciphertext=""
                ).exists(),
                "status": "connected"
                if connected
                else (connection.status if connection else "not_connected"),
                "configuration": "credential_unavailable"
                if credential_error
                else assistant_configuration_status(),
            }
        )


class AssistantDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(disconnect_user(request.user))


class AssistantRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, household_id):
        require_membership(request.user, household_id, write=True)
        result = create_response(
            request.user,
            request.data.get("text"),
            request.data.get("image_data"),
            household_id,
            request.data.get("mode", "label"),
        )
        return Response(result)
