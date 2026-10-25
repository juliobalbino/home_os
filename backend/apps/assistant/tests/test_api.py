from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.assistant.models import ChatGPTConnection
from apps.households.models import Household, Membership


class AssistantApiTests(TestCase):
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
