import json
from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.assistant.models import ChatGPTConnection


@override_settings(
    ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
)
class AssistantCommandTests(TestCase):
    @patch("apps.assistant.management.commands.assistant_oauth.urllib.request.urlopen")
    @patch("apps.assistant.management.commands.assistant_oauth.time.sleep")
    def test_empty_http_200_revocation_succeeds_and_never_prints_refresh_token(
        self, sleep, urlopen
    ):
        user = get_user_model().objects.create_user(
            email="revoke@example.test", name="Revoke", password="abcdef"
        )
        connection = ChatGPTConnection.objects.create(
            user=user,
            client_id="oaiapp_revoke",
            account_subject="subject",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials(
            {"access_token": "private-access", "refresh_token": "private-refresh"}
        )
        connection.save()
        metadata = MagicMock()
        metadata.__enter__.return_value.read.return_value = json.dumps(
            {"revocation_endpoint": "https://auth.openai.com/revoke"}
        ).encode()
        revoked = MagicMock()
        revoked.__enter__.return_value.status = 200
        revoked.__enter__.return_value.read.return_value = b""
        temporary = HTTPError(
            "https://auth.openai.com/revoke", 503, "busy", {}, BytesIO(b"")
        )
        urlopen.side_effect = [metadata, temporary, revoked]
        output = StringIO()
        call_command(
            "assistant_oauth",
            "--revoke-client-id",
            "oaiapp_revoke",
            "--user-id",
            str(user.pk),
            stdout=output,
        )
        connection.refresh_from_db()
        self.assertEqual(connection.status, "revoked")
        self.assertEqual(connection.credentials_ciphertext, "")
        self.assertNotIn("private-refresh", output.getvalue())
        self.assertIn(b"token_type_hint=refresh_token", urlopen.call_args.args[0].data)
        self.assertEqual(urlopen.call_count, 3)
        sleep.assert_called_once_with(0.25)
