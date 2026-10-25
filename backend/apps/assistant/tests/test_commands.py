import json
import os
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
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
    @patch("apps.assistant.management.commands.assistant_oauth.webbrowser.open")
    @patch("apps.assistant.management.commands.assistant_oauth.exchange_and_validate")
    @patch("apps.assistant.management.commands.assistant_oauth.new_authorization")
    @patch("apps.assistant.management.commands.assistant_oauth.HTTPServer")
    @patch("apps.assistant.management.commands.assistant_oauth.get_user_model")
    def test_authorize_without_user_id_exports_encrypted_bundle_only(
        self, get_user_model, http_server, new_authorization, exchange, _open
    ):
        from cryptography.fernet import Fernet

        from apps.assistant.management.commands import assistant_oauth

        key = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        pending = {"state": "expected"}
        new_authorization.return_value = ("https://example.test/authorize", pending)
        exchange.return_value = (
            {"sub": "account-subject"},
            {"access_token": "private-access", "refresh_token": "private-refresh"},
            ["chatgpt.tokens.use.direct"],
        )
        server = http_server.return_value

        # Exercise the real command callback without opening a browser or network listener.
        def serve_callback():
            handler = http_server.call_args.args[1]
            instance = object.__new__(handler)
            instance.path = (
                "/auth/callback?state=expected&code=test-code&client_id=oaiapp_test"
            )
            instance.send_response = MagicMock()
            instance.send_header = MagicMock()
            instance.end_headers = MagicMock()
            instance.wfile = MagicMock()
            handler.do_GET(instance)

        server.handle_request.side_effect = serve_callback
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            bundle_path = Path(directory) / "credentials.enc"
            with patch.object(assistant_oauth, "assistant_is_ready", return_value=True):
                call_command(
                    "assistant_oauth",
                    "--host-id",
                    "urn:uuid:stable-host",
                    "--output",
                    str(bundle_path),
                    stdout=output,
                )
            get_user_model.assert_not_called()
            self.assertEqual(ChatGPTConnection.objects.count(), 0)
            payload = json.loads(Fernet(key.encode()).decrypt(bundle_path.read_bytes()))
            self.assertEqual(payload["client_id"], "oaiapp_test")
            self.assertEqual(payload["account_subject"], "account-subject")
            self.assertEqual(payload["credentials"]["refresh_token"], "private-refresh")
            self.assertNotIn("private-access", output.getvalue())
            self.assertNotIn("private-refresh", output.getvalue())
            if os.name != "nt":
                self.assertEqual(bundle_path.stat().st_mode & 0o777, 0o600)

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
