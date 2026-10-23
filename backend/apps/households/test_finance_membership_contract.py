from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.households.models import Household, Membership


class MembershipFinanceContractTests(TestCase):
    def test_members_endpoint_exposes_membership_id_for_finance(self):
        user = User.objects.create_user(
            email="finance@example.com", password="secret1", name="Fin"
        )
        household = Household.objects.create(name="Casa", created_by=user)
        membership = Membership.objects.create(
            household=household, user=user, role="owner"
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.get(f"/api/v1/households/{household.id}/members")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["id"], membership.id)
