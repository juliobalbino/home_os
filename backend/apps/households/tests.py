from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.households.models import Household, Invitation, Membership
from apps.audit.models import AuditEvent


class HouseholdFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", name="Owner", password="safe-password-123"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_household_creator_is_owner_and_households_are_isolated(self):
        response = self.client.post(
            "/api/v1/households", {"name": "Casa"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        household = Household.objects.get()
        self.assertTrue(
            Membership.objects.filter(
                user=self.owner, household=household, role="owner"
            ).exists()
        )
        other = User.objects.create_user(
            email="other@example.com", name="Other", password="safe-password-123"
        )
        self.client.force_authenticate(other)
        self.assertEqual(
            self.client.get(f"/api/v1/households/{household.id}").status_code, 404
        )

    def test_user_cannot_create_a_second_household(self):
        first = self.client.post("/api/v1/households", {"name": "Casa"}, format="json")
        second = self.client.post(
            "/api/v1/households", {"name": "Outra"}, format="json"
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(Household.objects.count(), 1)

    def test_single_use_invitation_adds_member_and_viewer_cannot_write(self):
        household = Household.objects.create(name="Casa", created_by=self.owner)
        Membership.objects.create(household=household, user=self.owner, role="owner")
        response = self.client.post(
            f"/api/v1/households/{household.id}/invitations",
            {"role": "viewer"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        card = response.json()
        self.assertEqual(card["kind"], "invitation_creation")
        self.assertTrue(card["proposal_id"])
        self.assertNotIn("token", card)
        self.assertEqual(Invitation.objects.count(), 0)

        confirmation = self.client.post(
            f"/api/v1/households/{household.id}/assistant/actions/{card['proposal_id']}",
            {"confirm": True},
            format="json",
        )
        self.assertEqual(confirmation.status_code, 200)
        token = confirmation.json()["token"]
        self.assertTrue(token)
        self.assertIn("expiresAt", confirmation.json())
        invitation = Invitation.objects.get()
        self.assertNotEqual(invitation.token_hash, token)
        self.assertEqual(invitation.token_hash, Invitation.hash_token(token))

        accept = APIClient()
        guest = User.objects.create_user(
            email="guest@example.com", name="Guest", password="safe-password-123"
        )
        accept.force_authenticate(guest)
        url = f"/api/v1/invitations/{token}/accept"
        self.assertEqual(accept.post(url, {}, format="json").status_code, 200)
        self.assertEqual(accept.post(url, {}, format="json").status_code, 404)
        self.assertEqual(
            Membership.objects.get(user=guest, household=household).role, "viewer"
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.token_hash, Invitation.hash_token(token))
        self.assertEqual(invitation.token_ciphertext, "")
        self.assertEqual(
            accept.post(
                f"/api/v1/households/{household.id}/invitations", {}, format="json"
            ).status_code,
            403,
        )

    def test_invitation_proposal_can_be_cancelled_without_creating_invitation(self):
        household = Household.objects.create(name="Casa", created_by=self.owner)
        Membership.objects.create(household=household, user=self.owner, role="owner")
        response = self.client.post(
            f"/api/v1/households/{household.id}/invitations",
            {"role": "viewer"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        proposal_id = response.json()["proposal_id"]

        cancelled = self.client.post(
            f"/api/v1/households/{household.id}/assistant/actions/{proposal_id}",
            {"confirm": False},
            format="json",
        )

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json().get("status"), "cancelled")
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_invitation_proposal_rejects_invalid_role_without_creating_invitation(self):
        household = Household.objects.create(name="Casa", created_by=self.owner)
        Membership.objects.create(household=household, user=self.owner, role="owner")

        response = self.client.post(
            f"/api/v1/households/{household.id}/invitations",
            {"role": "owner"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        from django.apps import apps

        proposal_model = apps.get_model("assistant", "AssistantActionProposal")
        self.assertFalse(proposal_model.objects.exists())

    def test_expired_invitation_cannot_be_used(self):
        household = Household.objects.create(name="Casa", created_by=self.owner)
        invitation, token = Invitation.issue(household, self.owner, "member")
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        guest = User.objects.create_user(
            email="expired@example.com", name="Guest", password="safe-password-123"
        )
        client = APIClient()
        client.force_authenticate(guest)
        self.assertEqual(
            client.post(
                f"/api/v1/invitations/{token}/accept", {}, format="json"
            ).status_code,
            404,
        )

    def test_invitation_to_another_household_does_not_change_membership(self):
        current = Household.objects.create(name="Atual", created_by=self.owner)
        guest = User.objects.create_user(
            email="guest2@example.com", name="Guest", password="safe-password-123"
        )
        Membership.objects.create(household=current, user=guest, role="member")
        target = Household.objects.create(name="Alvo", created_by=self.owner)
        invitation, token = Invitation.issue(target, self.owner, "member")
        client = APIClient()
        client.force_authenticate(guest)
        response = client.post(f"/api/v1/invitations/{token}/accept", {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(
            invitation.__class__.objects.get(pk=invitation.pk).accepted_at
        )
        self.assertFalse(
            Membership.objects.filter(user=guest, household=target).exists()
        )

    def test_database_allows_only_one_active_membership_per_user(self):
        first = Household.objects.create(name="Uma", created_by=self.owner)
        second = Household.objects.create(name="Duas", created_by=self.owner)
        Membership.objects.create(household=first, user=self.owner, role="owner")
        with self.assertRaises(IntegrityError):
            Membership.objects.create(household=second, user=self.owner, role="owner")

    def test_removed_member_can_rejoin_same_household_with_new_invitation(self):
        household = Household.objects.create(name="Casa", created_by=self.owner)
        guest = User.objects.create_user(
            email="rejoining@example.com", name="Guest", password="safe-password-123"
        )
        membership = Membership.objects.create(
            household=household, user=guest, role="viewer", status="removed"
        )
        invitation, token = Invitation.issue(household, self.owner, "member")
        client = APIClient()
        client.force_authenticate(guest)

        response = client.post(f"/api/v1/invitations/{token}/accept", {}, format="json")

        self.assertEqual(response.status_code, 200)
        memberships = Membership.objects.filter(household=household, user=guest)
        self.assertEqual(memberships.count(), 1)
        membership.refresh_from_db()
        self.assertEqual(membership.pk, memberships.get().pk)
        self.assertEqual(membership.status, "active")
        self.assertEqual(membership.role, "member")
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.token_ciphertext, "")
