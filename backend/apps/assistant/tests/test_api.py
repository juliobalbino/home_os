import json
import hashlib
import re
import time
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import Request

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.assistant.models import AssistantPairing, ChatGPTConnection
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

    def _claimed_pairing(self):
        self.client.force_authenticate(self.owner)
        started = self.client.post(
            "/api/v1/assistant/connect/pairings", {}, format="json"
        )
        self.assertEqual(started.status_code, 201)
        pairing = AssistantPairing.objects.get(pk=started.data["pairing_id"])
        self.client.force_authenticate(user=None)
        claimed = self.client.post(
            "/api/v1/assistant/connect/pairings/claim",
            {
                "pairing_code": started.data["pairing_code"],
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
            format="json",
        )
        self.assertEqual(claimed.status_code, 200)
        pairing.refresh_from_db()
        payload = claimed.json()
        state = parse_qs(urlparse(payload["authorization_url"]).query)["state"][0]
        return pairing, payload["helper_token"], state

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("apps.assistant.views.exchange_and_validate", create=True)
    def test_pairing_completion_stores_encrypted_credentials(self, exchange):
        pairing, helper_token, state = self._claimed_pairing()
        pending = pairing.get_pending()
        identity = {"sub": "synthetic-account-subject"}
        tokens = {
            "access_token": "synthetic-access-token",
            "refresh_token": "synthetic-refresh-token",
            "id_token": "synthetic-id-token",
        }
        scopes = ["openid", "chatgpt.tokens.use.direct"]
        exchange.return_value = (identity, tokens, scopes)
        code, client_id = "synthetic-authorization-code", "synthetic-client-id"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {helper_token}")

        response = self.client.post(
            "/api/v1/assistant/connect/pairings/complete",
            {"authorization_code": code, "state": state, "client_id": client_id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        exchange.assert_called_once_with(code, client_id, pending)
        connection = ChatGPTConnection.objects.get(user=self.owner)
        self.assertEqual(connection.client_id, client_id)
        self.assertEqual(connection.account_subject, identity["sub"])
        self.assertEqual(connection.host_id, pairing.host_id)
        self.assertCountEqual(connection.scopes, scopes)
        self.assertNotIn("synthetic-access-token", connection.credentials_ciphertext)
        self.assertEqual(connection.get_credentials(), tokens)
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, "completed")
        for forbidden in (
            "access_token",
            "refresh_token",
            "id_token",
            "account_subject",
            "client_id",
        ):
            self.assertNotIn(forbidden, response.data)

    @override_settings(
        ASSISTANT_ENABLED=False,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("apps.assistant.views.exchange_and_validate", create=True)
    def test_pairing_completion_while_assistant_disabled_reports_pending_configuration(
        self, exchange
    ):
        pairing, helper_token, state = self._claimed_pairing()
        exchange.return_value = (
            {"sub": "synthetic-disabled-assistant-subject"},
            {
                "access_token": "synthetic-disabled-access-token",
                "refresh_token": "synthetic-disabled-refresh-token",
                "id_token": "synthetic-disabled-id-token",
            },
            ["openid", "chatgpt.tokens.use.direct"],
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {helper_token}")

        response = self.client.post(
            "/api/v1/assistant/connect/pairings/complete",
            {
                "authorization_code": "synthetic-disabled-authorization-code",
                "state": state,
                "client_id": "synthetic-disabled-client-id",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("status"), "pending_configuration")
        self.assertFalse(response.data.get("connected"))

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("apps.assistant.views.exchange_and_validate", create=True)
    def test_pairing_completion_rejects_invalid_authorization_and_extra_fields(
        self, exchange
    ):
        pairing, helper_token, state = self._claimed_pairing()
        url = "/api/v1/assistant/connect/pairings/complete"
        body = {
            "authorization_code": "synthetic-code",
            "state": state,
            "client_id": "synthetic-client",
        }
        self.client.credentials(HTTP_AUTHORIZATION="Bearer wrong-synthetic-helper")
        self.assertEqual(self.client.post(url, body, format="json").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {helper_token}")
        wrong_state = {**body, "state": "wrong-synthetic-state"}
        self.assertEqual(
            self.client.post(url, wrong_state, format="json").status_code, 400
        )
        for field, value in (
            ("user_id", str(self.viewer.pk)),
            ("host_id", "attacker-host"),
            ("scopes", []),
            ("credentials", {}),
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    self.client.post(
                        url, {**body, field: value}, format="json"
                    ).status_code,
                    400,
                )
        exchange.assert_not_called()
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, "claimed")

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("apps.assistant.views.exchange_and_validate", create=True)
    def test_pairing_completion_without_direct_token_scope_requires_consent_and_cannot_replay(
        self, exchange
    ):
        pairing, helper_token, state = self._claimed_pairing()
        exchange.return_value = (
            {"sub": "synthetic-no-direct-scope"},
            {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh"},
            ["openid"],
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {helper_token}")
        body = {
            "authorization_code": "synthetic-code",
            "state": state,
            "client_id": "synthetic-client",
        }
        response = self.client.post(
            "/api/v1/assistant/connect/pairings/complete", body, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("status"), "consent_required")
        self.assertFalse(response.data.get("connected"))
        self.assertEqual(ChatGPTConnection.objects.filter(user=self.owner).count(), 1)
        replay = self.client.post(
            "/api/v1/assistant/connect/pairings/complete", body, format="json"
        )
        self.assertEqual(replay.status_code, 401)

    def test_pairing_creation_requires_authentication(self):
        response = self.client.post(
            "/api/v1/assistant/connect/pairings", {}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_pairing_creation_and_status_are_owner_scoped(self):
        pairing_url = "/api/v1/assistant/connect/pairings"
        self.client.force_authenticate(self.owner)
        before = time.time()
        created = self.client.post(pairing_url, {}, format="json")
        after = time.time()

        self.assertEqual(created.status_code, 201)
        self.assertIn("no-store", created["Cache-Control"])
        self.assertTrue(created.data.get("pairing_id"))
        pairing_code = created.data.get("pairing_code")
        self.assertIsInstance(pairing_code, str)
        self.assertGreaterEqual(len(pairing_code), 32)
        self.assertRegex(pairing_code, re.compile(r"^[A-Za-z0-9_-]+$"))
        created_json = created.json()
        self.assertTrue(created_json.get("expires_at"))
        from django.utils.dateparse import parse_datetime

        expires_at = parse_datetime(created_json["expires_at"])
        self.assertIsNotNone(expires_at)
        if expires_at.tzinfo is None:
            from django.utils import timezone

            expires_at = timezone.make_aware(expires_at)
        self.assertGreaterEqual(expires_at.timestamp(), before)
        self.assertLessEqual(expires_at.timestamp(), after + 10 * 60)

        pairing_id = created.data["pairing_id"]
        pairing = AssistantPairing.objects.get(pk=pairing_id)
        pairing_code_digest = hashlib.sha256(pairing_code.encode("ascii")).hexdigest()
        self.assertEqual(pairing.pairing_code_hash, pairing_code_digest)
        self.assertNotEqual(pairing.pairing_code_hash, pairing_code)
        status = self.client.get(f"{pairing_url}/{pairing_id}")
        self.assertEqual(status.status_code, 200)
        self.assertIn("no-store", status["Cache-Control"])
        self.assertEqual(status.data.get("status"), "pending")
        for forbidden in (
            "pairing_code",
            "host_id",
            "user_id",
            "client_id",
            "access_token",
            "refresh_token",
        ):
            self.assertNotIn(forbidden, status.data)
        self.assertNotIn(pairing_code, str(status.data))

        self.client.force_authenticate(self.viewer)
        hidden = self.client.get(f"{pairing_url}/{pairing_id}")
        self.assertEqual(hidden.status_code, 404)

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_expired_pending_pairing_status_hides_code_and_claim_is_gone(self):
        from datetime import timedelta
        from django.utils import timezone

        self.client.force_authenticate(self.owner)
        started = self.client.post(
            "/api/v1/assistant/connect/pairings", {}, format="json"
        )
        self.assertEqual(started.status_code, 201)
        pairing = AssistantPairing.objects.get(pk=started.data["pairing_id"])
        pairing.expires_at = timezone.now() - timedelta(seconds=1)
        pairing.save(update_fields=["expires_at"])

        status = self.client.get(f"/api/v1/assistant/connect/pairings/{pairing.pk}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.data.get("status"), "expired")
        self.assertNotIn(started.data["pairing_code"], str(status.data))
        self.client.force_authenticate(user=None)
        claimed = self.client.post(
            "/api/v1/assistant/connect/pairings/claim",
            {
                "pairing_code": started.data["pairing_code"],
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
            format="json",
        )
        self.assertEqual(claimed.status_code, 410)

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    @patch("apps.assistant.views.exchange_and_validate", create=True)
    def test_pairing_completion_oauth_access_denied_cancels_pairing(self, exchange):
        pairing, helper_token, state = self._claimed_pairing()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {helper_token}")

        response = self.client.post(
            "/api/v1/assistant/connect/pairings/complete",
            {"state": state, "error": "access_denied"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("status"), "cancelled")
        self.assertFalse(response.data.get("connected"))
        exchange.assert_not_called()
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, "cancelled")
        self.assertEqual(pairing.pending_ciphertext, "")
        self.assertEqual(pairing.helper_token_hash, "")

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_pairings_reuse_existing_connection_host_id_across_users(self):
        stable_host_id = "urn:uuid:synthetic-shared-host"
        ChatGPTConnection.objects.create(
            user=self.owner,
            client_id="synthetic-client",
            account_subject="synthetic-subject",
            scopes=["chatgpt.tokens.use.direct"],
            host_id=stable_host_id,
        )
        pairing_url = "/api/v1/assistant/connect/pairings"
        responses = []
        pairings = []

        for user in (self.owner, self.viewer):
            self.client.force_authenticate(user)
            response = self.client.post(pairing_url, {}, format="json")
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("host_id", response.json())
            responses.append(response)
            pairings.append(
                AssistantPairing.objects.get(pk=response.json()["pairing_id"])
            )

        self.assertEqual(
            [pairing.host_id for pairing in pairings], [stable_host_id] * 2
        )

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_pairing_claim_builds_authorization_url_and_claims_pairing(self):
        self.client.force_authenticate(self.owner)
        started = self.client.post(
            "/api/v1/assistant/connect/pairings", {}, format="json"
        )
        self.assertEqual(started.status_code, 201)
        pairing_code = started.data["pairing_code"]
        pairing = AssistantPairing.objects.get(pk=started.data["pairing_id"])
        persisted_host_id = pairing.host_id

        self.client.force_authenticate(user=None)
        claimed = self.client.post(
            "/api/v1/assistant/connect/pairings/claim",
            {
                "pairing_code": pairing_code,
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
            format="json",
        )

        self.assertEqual(claimed.status_code, 200)
        self.assertIn("no-store", claimed["Cache-Control"])
        payload = claimed.json()
        parsed_url = urlparse(payload["authorization_url"])
        self.assertEqual(
            f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}",
            "https://auth.openai.com/api/accounts/authorize",
        )
        query = parse_qs(parsed_url.query)
        self.assertEqual(query["ext_agent_host_id"], [persisted_host_id])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:1455/auth/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query.get("code_challenge", [""])[0])
        self.assertTrue(query.get("state", [""])[0])
        self.assertTrue(query.get("nonce", [""])[0])
        self.assertIn("chatgpt.tokens.use.direct", query["scope"][0].split())
        self.assertNotIn("id_token_hint", query)
        self.assertNotIn("login_hint", query)
        self.assertTrue(payload.get("helper_token"))
        response_text = str(payload)
        for forbidden in ("code_verifier", "access_token", "refresh_token", "id_token"):
            self.assertNotIn(forbidden, response_text)
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, "claimed")

        replay = self.client.post(
            "/api/v1/assistant/connect/pairings/claim",
            {
                "pairing_code": pairing_code,
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
            format="json",
        )
        self.assertEqual(replay.status_code, 410)

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_pairing_claim_rejects_untrusted_redirects_and_invalid_codes(self):
        from datetime import timedelta
        from django.utils import timezone

        for index, redirect_uri in enumerate(
            (
                "https://127.0.0.1:1455/auth/callback",
                "http://evil.example/auth/callback",
                "http://127.0.0.1.evil.example:1455/auth/callback",
                "http://user:pass@127.0.0.1:1455/auth/callback",
                "http://127.0.0.1:1455/auth/callback?next=evil",
                "http://127.0.0.1:1455/auth/callback#fragment",
            )
        ):
            with self.subTest(redirect_uri=redirect_uri):
                pairing_code = f"synthetic-invalid-redirect-{index}"
                AssistantPairing.objects.create(
                    user=self.owner,
                    pairing_code_hash=hashlib.sha256(
                        pairing_code.encode("ascii")
                    ).hexdigest(),
                    host_id="urn:uuid:synthetic-redirect-host",
                    expires_at=timezone.now() + timedelta(minutes=5),
                )
                result = self.client.post(
                    "/api/v1/assistant/connect/pairings/claim",
                    {"pairing_code": pairing_code, "redirect_uri": redirect_uri},
                    format="json",
                )
                self.assertEqual(result.status_code, 400)
                for secret in (
                    "helper_token",
                    "authorization_url",
                    "access_token",
                    "refresh_token",
                ):
                    self.assertNotIn(secret, result.data)

        invalid = self.client.post(
            "/api/v1/assistant/connect/pairings/claim",
            {
                "pairing_code": "not-a-valid-pairing-code",
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
            format="json",
        )
        self.assertIn(invalid.status_code, (400, 404, 410))
        invalid_body = invalid.content.decode("utf-8")
        for secret in (
            "helper_token",
            "authorization_url",
            "access_token",
            "refresh_token",
        ):
            self.assertNotIn(secret, invalid_body)

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

    def test_connect_helper_is_public_static_source_without_secrets(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/v1/assistant/connect/helper")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="homeos_chatgpt_connect.py"',
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("def run_connect", body)
        self.assertNotIn("ASSISTANT_ENCRYPTION_KEY", body)
        for secret in (
            "synthetic-access-token",
            "synthetic-refresh-token",
            "synthetic-id-token",
            "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        ):
            self.assertNotIn(secret, body)

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
