import json
from datetime import date, timedelta

from django.contrib.sessions.backends.db import SessionStore
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AccountDeactivationEvent, User
from apps.assistant.models import AssistantPairing, ChatGPTConnection
from apps.audit.models import AuditEvent
from apps.finance.models import Expense, ExpenseCategory, Payment
from apps.households.models import Household, Invitation, Membership


class AccountDeactivationFlowTests(TestCase):
    proposal_url = "/api/v1/auth/account-deactivation/proposals"

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="member@example.com", name="Member Name", password="SafePass123"
        )
        self.other_user = User.objects.create_user(
            email="owner@example.com", name="Household Owner", password="OtherPass123"
        )
        self.household = Household.objects.create(
            name="Shared Home", created_by=self.other_user
        )
        self.active_membership = Membership.objects.create(
            household=self.household, user=self.user, role="member", status="active"
        )
        self.archived_household = Household.objects.create(
            name="Old Home", created_by=self.other_user, archived_at=timezone.now()
        )
        self.archived_membership = Membership.objects.create(
            household=self.archived_household,
            user=self.user,
            role="member",
            status="archived",
        )
        self.client.force_login(self.user)

    def test_confirm_deactivates_user_without_losing_history_or_exposing_secrets(self):
        category = ExpenseCategory.objects.create(
            household=self.household, name="Household", kind="general"
        )
        expense = Expense.objects.create(
            household=self.household,
            description="Shared expense",
            category=category,
            amount_minor=12500,
            incurred_on=date(2025, 5, 1),
            created_by=self.user,
            notes="Historical note",
        )
        payment = Payment.objects.create(
            household=self.household,
            expense=expense,
            payer=self.active_membership,
            amount_minor=5000,
            notes="Historical payment",
        )
        historical_event = AuditEvent.objects.create(
            household=self.household,
            actor=self.user,
            action="expense.created",
            entity_type="expense",
            entity_id=str(expense.pk),
            metadata={"description": "Shared expense"},
        )
        invitation, _ = Invitation.issue(self.household, self.user, "member")

        connection = ChatGPTConnection(
            user=self.user,
            client_id="synthetic-client",
            account_subject="synthetic-subject",
            host_id="synthetic-host",
            credentials_ciphertext="synthetic-ciphertext",
        )
        connection.save()
        pairing = AssistantPairing(
            user=self.user,
            pairing_code_hash="synthetic-pairing-hash",
            host_id="synthetic-host",
            expires_at=timezone.now() + timedelta(minutes=10),
            pending_ciphertext="synthetic-ciphertext",
        )
        pairing.save()

        # Keep an additional authenticated session in the database as well as the
        # session established by force_login above.
        self.client.session.save()
        first_session_key = self.client.session.session_key
        second_session = SessionStore()
        second_session["_auth_user_id"] = str(self.user.pk)
        second_session["_auth_user_backend"] = (
            "django.contrib.auth.backends.ModelBackend"
        )
        second_session.save()
        second_session_key = second_session.session_key

        proposal_response = self.client.post(self.proposal_url, {}, format="json")
        self.assertEqual(proposal_response.status_code, 201)
        preview = proposal_response.json()
        self.assertNotIn("synthetic-access-secret", json.dumps(preview))
        self.assertNotIn("synthetic-refresh-secret", json.dumps(preview))
        self.assertNotIn("synthetic-pending-secret", json.dumps(preview))
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "member@example.com")
        self.assertTrue(User.objects.get(pk=self.user.pk).is_active)
        self.assertEqual(self.active_membership.status, "active")
        self.assertTrue(invitation.token_ciphertext)

        proposal_id = preview.get("proposal_id", preview.get("id"))
        self.assertIsNotNone(proposal_id)
        confirm_response = self.client.post(
            f"{self.proposal_url}/{proposal_id}/confirm",
            {"confirm": True},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.json().get("status"), "confirmed")
        confirmation_body = json.dumps(confirm_response.json())
        self.assertNotIn("synthetic-access-secret", confirmation_body)
        self.assertNotIn("synthetic-refresh-secret", confirmation_body)
        self.assertNotIn("synthetic-pending-secret", confirmation_body)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.user.name, "Conta desativada")
        self.assertNotEqual(self.user.email, "member@example.com")
        self.assertNotEqual(self.user.email, self.other_user.email)
        self.assertEqual(
            Membership.objects.get(pk=self.active_membership.pk).status, "removed"
        )
        self.assertEqual(
            Membership.objects.get(pk=self.archived_membership.pk).status, "archived"
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertEqual(invitation.token_ciphertext, "")
        self.assertFalse(ChatGPTConnection.objects.filter(pk=connection.pk).exists())
        self.assertFalse(AssistantPairing.objects.filter(pk=pairing.pk).exists())

        self.assertFalse(SessionStore().exists(first_session_key))
        self.assertFalse(SessionStore().exists(second_session_key))
        self.assertEqual(Expense.objects.filter(pk=expense.pk).count(), 1)
        self.assertEqual(Payment.objects.filter(pk=payment.pk).count(), 1)
        self.assertTrue(AuditEvent.objects.filter(pk=historical_event.pk).exists())

        deactivation_events = AccountDeactivationEvent.objects.filter(
            action="account.deactivated"
        )
        self.assertEqual(deactivation_events.count(), 1)
        self.assertNotIn(
            "synthetic-access-secret", json.dumps(deactivation_events.first().metadata)
        )
        self.assertNotIn(
            "synthetic-refresh-secret", json.dumps(deactivation_events.first().metadata)
        )
        self.assertNotIn(
            "synthetic-pending-secret", json.dumps(deactivation_events.first().metadata)
        )
        self.assertEqual(
            self.client.post(
                f"{self.proposal_url}/{proposal_id}/confirm",
                {"confirm": True},
                format="json",
            ).status_code,
            401,
        )

    def test_owner_with_active_household_is_blocked_without_side_effects(self):
        owner_user = User.objects.create_user(
            email="active-owner@example.com",
            name="Active Owner",
            password="OwnerPass123",
        )
        owned_household = Household.objects.create(
            name="Owner Home", created_by=owner_user
        )
        owner_membership = Membership.objects.create(
            household=owned_household,
            user=owner_user,
            role="owner",
            status="active",
        )
        client = APIClient()
        client.force_login(owner_user)

        response = client.post(self.proposal_url, {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Owner Home", json.dumps(response.json()))
        self.assertEqual(Membership.objects.filter(user=owner_user).count(), 1)
        self.assertEqual(
            Membership.objects.get(pk=owner_membership.pk).status, "active"
        )
        owner_user.refresh_from_db()
        self.assertTrue(owner_user.is_active)
        self.assertTrue(owner_user.has_usable_password())
        self.assertEqual(owner_user.name, "Active Owner")
        self.assertEqual(owner_user.email, "active-owner@example.com")
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(AccountDeactivationEvent.objects.exists())
