import hashlib
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from django.http import FileResponse, Http404
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.configuration import (
    assistant_configuration_status,
    assistant_is_ready,
)
from apps.assistant.models import (
    AssistantHostIdentity,
    AssistantPairing,
    ChatGPTConnection,
)
from apps.assistant.services import (
    create_response,
    disconnect_user,
    exchange_and_validate,
    new_authorization,
    save_token_set,
)
from apps.households.permissions import require_membership


class HostIdentityConfigurationError(Exception):
    """Raised when legacy host IDs conflict and cannot be adopted safely."""


class NoStoreAPIView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


class AssistantHelperDownloadView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        helper_path = Path(__file__).with_name("connect_helper.py")
        response = FileResponse(
            helper_path.open("rb"),
            content_type="text/x-python",
            as_attachment=True,
            filename="homeos_chatgpt_connect.py",
        )
        return response


def _stable_host_id(user):
    """Return a persisted host identity without touching encrypted credentials."""
    identity = AssistantHostIdentity.objects.filter(pk=1).first()
    if identity:
        return identity.host_id

    host_ids = set(
        ChatGPTConnection.objects.exclude(host_id="")
        .values_list("host_id", flat=True)
        .distinct()
    )
    if len(host_ids) > 1:
        raise HostIdentityConfigurationError
    host_id = next(iter(host_ids), None) or f"urn:uuid:{uuid.uuid4()}"
    identity, _ = AssistantHostIdentity.objects.get_or_create(
        pk=1, defaults={"host_id": host_id}
    )
    return identity.host_id


class AssistantPairingCollectionView(NoStoreAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Ignore caller identity fields: ownership always comes from authentication.
        code = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(minutes=5)
        try:
            host_id = _stable_host_id(request.user)
        except HostIdentityConfigurationError:
            return Response(
                {"error": "Assistant host identity configuration is ambiguous."},
                status=503,
            )
        pairing = AssistantPairing.objects.create(
            user=request.user,
            pairing_code_hash=hashlib.sha256(code.encode("ascii")).hexdigest(),
            host_id=host_id,
            expires_at=expires_at,
        )
        return Response(
            {
                "pairing_id": str(pairing.pairing_id),
                "pairing_code": code,
                "expires_at": pairing.expires_at,
            },
            status=201,
        )


class AssistantPairingDetailView(NoStoreAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pairing_id):
        try:
            pairing = AssistantPairing.objects.get(
                pairing_id=pairing_id, user=request.user
            )
        except (AssistantPairing.DoesNotExist, ValueError):
            raise Http404
        if (
            pairing.status in {"pending", "claimed"}
            and pairing.expires_at <= timezone.now()
        ):
            pairing.status = "expired"
            pairing.pending_ciphertext = ""
            pairing.helper_token_hash = ""
            pairing.save(
                update_fields=["status", "pending_ciphertext", "helper_token_hash"]
            )
        return Response({"status": pairing.status, "expires_at": pairing.expires_at})


class AssistantPairingClaimView(NoStoreAPIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not isinstance(request.data, dict) or set(request.data) != {
            "pairing_code",
            "redirect_uri",
        }:
            return Response({"error": "Invalid request."}, status=400)
        code, redirect_uri = (
            request.data.get("pairing_code"),
            request.data.get("redirect_uri"),
        )
        if (
            not isinstance(code, str)
            or not code.isascii()
            or not isinstance(redirect_uri, str)
        ):
            return Response({"error": "Invalid request."}, status=400)
        digest = hashlib.sha256(code.encode("ascii")).hexdigest()
        try:
            # Validate before acquiring/consuming a pairing.
            new_authorization("urn:uuid:validation", redirect_uri)
        except ValidationError:
            return Response({"error": "Invalid redirect_uri."}, status=400)
        with transaction.atomic():
            pairing = (
                AssistantPairing.objects.select_for_update()
                .filter(pairing_code_hash=digest)
                .first()
            )
            if pairing is None:
                return Response({"error": "Pairing not found."}, status=404)
            if pairing.status != "pending":
                return Response(
                    {"error": "Pairing is no longer available."}, status=410
                )
            if pairing.expires_at <= timezone.now():
                pairing.status = "expired"
                pairing.save(update_fields=["status"])
                return Response({"error": "Pairing expired."}, status=410)
            authorization_url, pending = new_authorization(
                pairing.host_id, redirect_uri, client_id="dynamic_agent_client"
            )
            helper_token = secrets.token_urlsafe(32)
            pairing.set_pending(pending)
            pairing.helper_token_hash = hashlib.sha256(
                helper_token.encode("ascii")
            ).hexdigest()
            pairing.status = "claimed"
            pairing.save(
                update_fields=["pending_ciphertext", "helper_token_hash", "status"]
            )
            return Response(
                {
                    "authorization_url": authorization_url,
                    "helper_token": helper_token,
                    "expires_at": pairing.expires_at,
                }
            )


class AssistantPairingCompleteView(NoStoreAPIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        authorization = request.headers.get("Authorization", "")
        scheme, separator, helper_token = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not helper_token
            or " " in helper_token
        ):
            return Response({"error": "Invalid authorization."}, status=401)
        success_fields = {"authorization_code", "state", "client_id"}
        cancellation_fields = {"state", "error"}
        if not isinstance(request.data, dict):
            return Response({"error": "Invalid request."}, status=400)
        request_fields = frozenset(request.data)
        if request_fields not in {
            frozenset(success_fields),
            frozenset(cancellation_fields),
        }:
            return Response({"error": "Invalid request."}, status=400)
        is_cancellation = request_fields == frozenset(cancellation_fields)
        state = request.data.get("state")
        if not isinstance(state, str) or not state:
            return Response({"error": "Invalid request."}, status=400)
        if is_cancellation:
            error = request.data.get("error")
            if (
                not isinstance(error, str)
                or not 1 <= len(error) <= 128
                or not error.isascii()
                or not all(
                    character.isalnum() or character in "._-" for character in error
                )
            ):
                return Response({"error": "Invalid request."}, status=400)
        else:
            code, client_id = (
                request.data.get("authorization_code"),
                request.data.get("client_id"),
            )
            if not all(isinstance(value, str) and value for value in (code, client_id)):
                return Response({"error": "Invalid request."}, status=400)

        token_hash = hashlib.sha256(helper_token.encode("utf-8")).hexdigest()
        with transaction.atomic():
            pairing = (
                AssistantPairing.objects.select_for_update()
                .filter(helper_token_hash=token_hash)
                .first()
            )
            if pairing is None:
                return Response({"error": "Invalid authorization."}, status=401)
            if pairing.status != "claimed":
                return Response(
                    {"error": "Pairing is no longer available."}, status=410
                )
            if pairing.expires_at <= timezone.now():
                pairing.status = "expired"
                pairing.helper_token_hash = ""
                pairing.save(update_fields=["status", "helper_token_hash"])
                return Response({"error": "Pairing expired."}, status=410)

            pending = pairing.get_pending()
            if not secrets.compare_digest(str(pending.get("state", "")), state):
                return Response({"error": "Invalid state."}, status=400)
            if is_cancellation:
                pairing.status = "cancelled"
                pairing.pending_ciphertext = ""
                pairing.helper_token_hash = ""
                pairing.save(
                    update_fields=["status", "pending_ciphertext", "helper_token_hash"]
                )
                return Response({"status": "cancelled", "connected": False})
            pairing.status = "completing"
            pairing.save(update_fields=["status"])
            pairing_id = pairing.pk

        try:
            claims, token, scopes = exchange_and_validate(code, client_id, pending)
            token = dict(token)
            if token.get("expires_in") is not None:
                token["expires_at"] = timezone.now().timestamp() + int(
                    token["expires_in"]
                )
            with transaction.atomic():
                current = AssistantPairing.objects.select_for_update().get(
                    pk=pairing_id
                )
                if current.status != "completing":
                    raise ValueError("Pairing is no longer available.")
                connection = save_token_set(
                    current.user, client_id, claims, token, scopes
                )
                connection.host_id = current.host_id
                connection.save(update_fields=["host_id", "updated_at"])
                current.status = "completed"
                current.pending_ciphertext = ""
                current.helper_token_hash = ""
                current.save(
                    update_fields=["status", "pending_ciphertext", "helper_token_hash"]
                )
        except Exception:
            # Keep the claimed pairing consumed even when provider exchange or persistence fails.
            AssistantPairing.objects.filter(pk=pairing_id, status="completing").update(
                status="failed", pending_ciphertext="", helper_token_hash=""
            )
            return Response(
                {"error": "Authorization could not be completed."}, status=502
            )

        connected = connection.status == "connected"
        return Response({"status": connection.status, "connected": connected})


class AssistantStatusView(NoStoreAPIView):
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
