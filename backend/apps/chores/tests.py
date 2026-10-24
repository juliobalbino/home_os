from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.households.models import Household, Membership
from apps.chores.models import ChoreCompletion


class ChoreApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="chores@example.com", password="abcdef", name="Chore User"
        )
        self.house = Household.objects.create(
            name="Casa", timezone="America/New_York", created_by=self.user
        )
        self.member = Membership.objects.create(
            household=self.house, user=self.user, role="owner"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_chore_and_generate_daily_occurrences_idempotently_in_household_timezone(
        self,
    ):
        created = self.client.post(
            f"/api/v1/households/{self.house.pk}/chores",
            {
                "title": "Water plants",
                "category": "Garden",
                "description": "Backyard",
                "recurrence_rule": {"frequency": "daily", "time": "09:00"},
                "assignment_ids": [self.member.pk],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        chore_id = created.data["id"]
        result = self.client.post(
            f"/api/v1/chores/{chore_id}/generate-occurrences",
            {"start_date": "2026-03-08", "end_date": "2026-03-09"},
            format="json",
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["created"], 2)
        repeated = self.client.post(
            f"/api/v1/chores/{chore_id}/generate-occurrences",
            {"start_date": "2026-03-08", "end_date": "2026-03-09"},
            format="json",
        )
        self.assertEqual(repeated.data["created"], 0)
        rows = self.client.get(
            f"/api/v1/households/{self.house.pk}/chore-occurrences"
        ).data
        self.assertEqual(
            [row["due_at"].isoformat() for row in rows],
            ["2026-03-08T13:00:00+00:00", "2026-03-09T13:00:00+00:00"],
        )

    def test_viewer_can_read_but_cannot_mutate_and_invalid_input_is_400(self):
        endpoint = f"/api/v1/households/{self.house.pk}/chores"
        self.assertEqual(
            self.client.post(endpoint, {"title": "Clean"}, format="json").status_code,
            201,
        )
        self.assertEqual(
            self.client.post(endpoint, {"title": ""}, format="json").status_code,
            400,
        )
        self.member.role = "viewer"
        self.member.save(update_fields=["role"])
        self.assertEqual(
            self.client.post(endpoint, {"title": "Again"}, format="json").status_code,
            403,
        )

    def test_completion_preserves_history_and_cross_household_ids_are_hidden(self):
        created = self.client.post(
            f"/api/v1/households/{self.house.pk}/chores",
            {
                "title": "Sweep",
                "recurrence_rule": {"frequency": "daily", "time": "08:00"},
            },
            format="json",
        )
        self.client.post(
            f"/api/v1/chores/{created.data['id']}/generate-occurrences",
            {"start_date": "2026-10-23", "end_date": "2026-10-23"},
            format="json",
        )
        occurrence = self.client.get(
            f"/api/v1/households/{self.house.pk}/chore-occurrences"
        ).data[0]
        completed = self.client.post(
            f"/api/v1/chore-occurrences/{occurrence['id']}/complete",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(ChoreCompletion.objects.count(), 1)
        self.assertEqual(
            self.client.get(
                f"/api/v1/households/{self.house.pk}/chore-occurrences"
            ).data[0]["status"],
            "completed",
        )
        other = get_user_model().objects.create_user(
            email="other@example.com", password="abcdef", name="Other"
        )
        self.client.force_authenticate(other)
        self.assertEqual(
            self.client.post(
                f"/api/v1/chores/{created.data['id']}/generate-occurrences",
                {"start_date": "2026-10-23", "end_date": "2026-10-23"},
                format="json",
            ).status_code,
            404,
        )
