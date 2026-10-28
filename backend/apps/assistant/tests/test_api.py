import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.assistant.models import ChatGPTConnection
from apps.households.models import Household, Membership


class AssistantApiTests(TestCase):
    assistant_settings = {
        "ASSISTANT_ENABLED": True,
        "ASSISTANT_ENCRYPTION_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    }

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="ai@example.test", name="AI", password="abcdef"
        )
        self.viewer = get_user_model().objects.create_user(
            email="viewer@example.test", name="Viewer", password="abcdef"
        )
        self.house = Household.objects.create(name="Home", created_by=self.owner)
        Membership.objects.create(user=self.owner, household=self.house, role="owner")
        Membership.objects.create(user=self.viewer, household=self.house, role="viewer")
        self.client = APIClient()

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_viewer_cannot_submit_and_status_never_exposes_credentials(self):
        conn = ChatGPTConnection.objects.create(
            user=self.viewer,
            client_id="issued",
            account_subject="sub",
            scopes=["chatgpt.tokens.use.direct"],
        )
        conn.set_credentials(
            {"access_token": "never-return-this", "refresh_token": "also-secret"}
        )
        conn.save()
        self.client.force_authenticate(self.viewer)
        status = self.client.get("/api/v1/assistant/status")
        self.assertEqual(status.status_code, 200)
        self.assertNotIn("never-return-this", str(status.data))
        result = self.client.post(
            f"/api/v1/households/{self.house.pk}/assistant",
            {"text": "Hi"},
            format="json",
        )
        self.assertEqual(result.status_code, 403)

    def test_cross_household_request_is_hidden_and_disabled_feature_fails_closed(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(
            self.client.post(
                "/api/v1/households/00000000-0000-0000-0000-000000000001/assistant",
                {"text": "Hi"},
                format="json",
            ).status_code,
            404,
        )
        status = self.client.get("/api/v1/assistant/status")
        self.assertFalse(status.data["enabled"])
        self.assertFalse(status.data["connected"])

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_a_household_member_cannot_use_another_users_connection(self):
        connection = ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="issued",
            account_subject="sub",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials(
            {"access_token": "owner-access", "refresh_token": "owner-refresh"}
        )
        connection.save()
        membership = Membership.objects.get(user=self.viewer, household=self.house)
        membership.role = "member"
        membership.save(update_fields=["role"])
        self.client.force_authenticate(self.viewer)
        result = self.client.post(
            f"/api/v1/households/{self.house.pk}/assistant",
            {"text": "Ask"},
            format="json",
        )
        self.assertEqual(result.status_code, 503)
        self.assertEqual(
            ChatGPTConnection.objects.get(user=self.owner).get_credentials()[
                "access_token"
            ],
            "owner-access",
        )

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_status_does_not_report_connected_when_runtime_key_cannot_decrypt_imported_tokens(
        self,
    ):
        connection = ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="issued",
            account_subject="sub",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials({"access_token": "ciphertext"})
        connection.save()
        self.client.force_authenticate(self.owner)
        with override_settings(
            ASSISTANT_ENCRYPTION_KEY="YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXphYmNkZWY="
        ):
            status = self.client.get("/api/v1/assistant/status")
        self.assertFalse(status.data["connected"])
        self.assertEqual(status.data["configuration"], "credential_unavailable")

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_status_can_disconnect_reflects_this_users_stored_credentials(self):
        self.client.force_authenticate(self.owner)
        status = self.client.get("/api/v1/assistant/status")
        self.assertFalse(status.data["can_disconnect"])

        connection = ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="issued",
            account_subject="sub",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials(
            {"access_token": "own-access", "refresh_token": "own-refresh"}
        )
        connection.save()
        status = self.client.get("/api/v1/assistant/status")
        self.assertTrue(status.data["can_disconnect"])

    def test_disconnect_requires_authentication(self):
        self.assertEqual(
            self.client.post("/api/v1/assistant/disconnect").status_code, 401
        )

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("time.sleep")
    @patch("urllib.request.build_opener")
    @patch("urllib.request.urlopen")
    def test_disconnect_revokes_all_own_connections_and_preserves_other_users(
        self, urlopen, build_opener, sleep
    ):
        own_connections = []
        for client_id, subject in (("issued-a", "sub-a"), ("issued-b", "sub-b")):
            connection = ChatGPTConnection.objects.create(
                user=self.owner,
                client_id=client_id,
                account_subject=subject,
                scopes=["chatgpt.tokens.use.direct"],
            )
            connection.set_credentials(
                {
                    "access_token": f"fake-access-{subject}",
                    "refresh_token": f"fake-refresh-{subject}",
                }
            )
            connection.save()
            own_connections.append(connection)
        other = ChatGPTConnection.objects.create(
            user=self.viewer,
            client_id="other-client",
            account_subject="other-subject",
            scopes=["chatgpt.tokens.use.direct"],
        )
        other.set_credentials(
            {"access_token": "other-fake-access", "refresh_token": "other-fake-refresh"}
        )
        other.save()

        def successful_revocation():
            response = MagicMock()
            response.__enter__.return_value.status = 200
            response.__enter__.return_value.read.return_value = json.dumps(
                {"revocation_endpoint": "https://auth.openai.com/revoke"}
            ).encode()
            return response

        urlopen.side_effect = [successful_revocation() for _ in own_connections]
        opener = build_opener.return_value
        opener.open.return_value.__enter__.return_value.status = 200
        self.client.force_authenticate(self.owner)
        result = self.client.post("/api/v1/assistant/disconnect")

        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data["disconnected"])
        self.assertTrue(result.data["revocation_confirmed"])
        self.assertEqual(urlopen.call_count, len(own_connections))
        self.assertEqual(opener.open.call_count, len(own_connections))
        sleep.assert_not_called()
        for connection in own_connections:
            connection.refresh_from_db()
            self.assertEqual(connection.credentials_ciphertext, "")
            self.assertEqual(connection.status, "revoked")
        other.refresh_from_db()
        self.assertEqual(other.status, "connected")
        self.assertEqual(other.get_credentials()["access_token"], "other-fake-access")
        response_text = str(result.data)
        for token in (
            "fake-access-sub-a",
            "fake-refresh-sub-a",
            "fake-access-sub-b",
            "fake-refresh-sub-b",
        ):
            self.assertNotIn(token, response_text)

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("time.sleep")
    @patch("urllib.request.build_opener")
    @patch("urllib.request.urlopen")
    def test_disconnect_clears_tokens_when_revocation_is_unconfirmed_and_is_idempotent(
        self, urlopen, build_opener, sleep
    ):
        connection = ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="issued",
            account_subject="sub",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials(
            {"access_token": "fake-access", "refresh_token": "fake-refresh"}
        )
        connection.save()
        metadata = MagicMock()
        metadata.__enter__.return_value.read.return_value = json.dumps(
            {"revocation_endpoint": "https://auth.openai.com/revoke"}
        ).encode()
        busy = HTTPError(
            "https://auth.openai.com/revoke", 503, "busy", {}, BytesIO(b"")
        )
        urlopen.return_value = metadata
        build_opener.return_value.open.side_effect = [busy, busy, busy]
        self.client.force_authenticate(self.owner)
        result = self.client.post("/api/v1/assistant/disconnect")

        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data["disconnected"])
        self.assertFalse(result.data["revocation_confirmed"])
        self.assertNotIn("fake-access", str(result.data))
        self.assertNotIn("fake-refresh", str(result.data))
        connection.refresh_from_db()
        self.assertEqual(connection.credentials_ciphertext, "")
        self.assertEqual(connection.status, "revocation_unconfirmed")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(build_opener.return_value.open.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.25, 0.75])

        urlopen.reset_mock()
        build_opener.return_value.open.reset_mock()
        sleep.reset_mock()
        again = self.client.post("/api/v1/assistant/disconnect")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.data["disconnected"])
        self.assertFalse(again.data["revocation_confirmed"])
        urlopen.assert_not_called()
        sleep.assert_not_called()
        status = self.client.get("/api/v1/assistant/status")
        self.assertFalse(status.data["can_disconnect"])

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("urllib.request.build_opener")
    @patch("urllib.request.urlopen")
    def test_disconnect_rejects_untrusted_revocation_endpoints(
        self, urlopen, build_opener
    ):
        for endpoint in (
            "http://auth.openai.com/revoke",
            "https://attacker.example/revoke",
            "https://auth.openai.com.attacker.example/revoke",
            "https://user:password@auth.openai.com/revoke",
            "https://auth.openai.com:8443/revoke",
        ):
            with self.subTest(endpoint=endpoint):
                connection = ChatGPTConnection.objects.create(
                    user=self.owner,
                    client_id="issued",
                    account_subject=endpoint,
                    scopes=["chatgpt.tokens.use.direct"],
                )
                connection.set_credentials({"refresh_token": "private-refresh"})
                connection.save()
                metadata = MagicMock()
                metadata.__enter__.return_value.read.return_value = json.dumps(
                    {"revocation_endpoint": endpoint}
                ).encode()
                urlopen.return_value = metadata
                urlopen.reset_mock()
                build_opener.reset_mock()
                self.client.force_authenticate(self.owner)

                result = self.client.post("/api/v1/assistant/disconnect")

                self.assertEqual(urlopen.call_count, 1)
                self.assertEqual(
                    urlopen.call_args.args[0].full_url,
                    "https://auth.openai.com/.well-known/openid-configuration",
                )
                build_opener.assert_not_called()
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.data["revocation_confirmed"])
                connection.refresh_from_db()
                self.assertEqual(connection.credentials_ciphertext, "")
                self.assertEqual(connection.status, "revocation_unconfirmed")
                self.assertNotIn("private-refresh", str(result.data))

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("urllib.request.build_opener")
    @patch("urllib.request.urlopen")
    def test_disconnect_opener_disables_redirects(self, urlopen, build_opener):
        from apps.assistant import services

        connection = ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="issued",
            account_subject="redirect-subject",
            scopes=["chatgpt.tokens.use.direct"],
        )
        connection.set_credentials({"refresh_token": "private-refresh"})
        connection.save()
        metadata = MagicMock()
        metadata.__enter__.return_value.read.return_value = json.dumps(
            {"revocation_endpoint": "https://auth.openai.com/revoke"}
        ).encode()
        urlopen.return_value = metadata
        build_opener.return_value.open.side_effect = HTTPError(
            "https://auth.openai.com/revoke",
            307,
            "Temporary Redirect",
            {},
            BytesIO(b""),
        )
        self.client.force_authenticate(self.owner)

        result = self.client.post("/api/v1/assistant/disconnect")

        handler_class = getattr(services, "NoRedirectHandler", None)
        self.assertIsNotNone(handler_class, "NoRedirectHandler must be defined")
        handlers = build_opener.call_args.args
        self.assertTrue(any(isinstance(handler, handler_class) for handler in handlers))
        handler = next(
            handler for handler in handlers if isinstance(handler, handler_class)
        )
        self.assertIsNone(
            handler.redirect_request(
                Request(
                    "https://auth.openai.com/revoke",
                    data=b"token=fake-token",
                ),
                None,
                307,
                "Temporary Redirect",
                {},
                "https://attacker.example/",
            )
        )
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.data["revocation_confirmed"])
        build_opener.return_value.open.assert_called_once()
