from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.assistant.operator import dispatch_tool
from apps.audit.models import AuditEvent
from apps.chores.models import Chore, ChoreAssignment, ChoreOccurrence
from apps.finance.models import Expense, ExpenseCategory
from apps.households.models import Household, Invitation, Membership
from apps.shopping.models import Product, ShoppingList, ShoppingListItem


class ShoppingListDeletionProposalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="proposal-owner@example.test", name="Owner", password="test-password"
        )
        self.viewer = user_model.objects.create_user(
            email="proposal-viewer@example.test",
            name="Viewer",
            password="test-password",
        )
        self.foreign = user_model.objects.create_user(
            email="proposal-foreign@example.test",
            name="Foreign",
            password="test-password",
        )
        self.household = Household.objects.create(
            name="Proposal home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Other home", created_by=self.foreign
        )
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        Membership.objects.create(
            user=self.foreign, household=self.foreign_household, role="owner"
        )
        self.product = Product.objects.create(
            household=self.household, name="Synthetic oats", unit="kg"
        )
        self.shopping_list = ShoppingList.objects.create(
            household=self.household,
            name="Synthetic groceries",
            status=ShoppingList.Status.ACTIVE,
            created_by=self.owner,
        )
        self.product_item = ShoppingListItem.objects.create(
            shopping_list=self.shopping_list,
            product=self.product,
            quantity=Decimal("1.2500"),
            unit="kg",
            priority=2,
            status=ShoppingListItem.Status.NEEDED,
            added_by=self.owner,
        )
        self.free_text_item = ShoppingListItem.objects.create(
            shopping_list=self.shopping_list,
            free_text_name="Synthetic basil",
            quantity=Decimal("0.5000"),
            unit="bunch",
            priority=1,
            status=ShoppingListItem.Status.PURCHASED,
            added_by=self.owner,
        )
        self.client = APIClient()

    def _propose(
        self, *, request_uuid="00000000-0000-4000-8000-000000000001", call_index=0
    ):
        return dispatch_tool(
            "propose_shopping_list_deletion",
            {"shopping_list_id": self.shopping_list.pk},
            user=self.owner,
            household_id=self.household.pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _proposal_model(self):
        # Resolve dynamically so the missing proposal feature fails at the behavior
        # boundary, rather than preventing this module from importing.
        return apps.get_model("assistant", "AssistantActionProposal")

    def _confirm(self, user, proposal_id, *, household_id=None, confirm=True):
        self.client.force_authenticate(user)
        household_id = household_id or self.household.pk
        return self.client.post(
            f"/api/v1/households/{household_id}/assistant/actions/{proposal_id}",
            {"confirm": confirm},
            format="json",
        )

    def _assert_list_unchanged(self, item_ids):
        self.assertTrue(ShoppingList.objects.filter(pk=self.shopping_list.pk).exists())
        self.assertEqual(
            set(
                ShoppingListItem.objects.filter(
                    shopping_list=self.shopping_list
                ).values_list("pk", flat=True)
            ),
            set(item_ids),
        )

    def test_proposal_is_safe_bound_snapshot_and_request_replay_is_idempotent(self):
        expected_snapshot = {
            "list": {
                "id": str(self.shopping_list.pk),
                "name": "Synthetic groceries",
                "status": "active",
            },
            "items": [
                {
                    "id": str(self.product_item.pk),
                    "product_id": str(self.product.pk),
                    "product_name": self.product.name,
                    "free_text_name": "",
                    "quantity": "1.2500",
                    "unit": "kg",
                    "priority": 2,
                    "status": "needed",
                },
                {
                    "id": str(self.free_text_item.pk),
                    "product_id": None,
                    "product_name": None,
                    "free_text_name": "Synthetic basil",
                    "quantity": "0.5000",
                    "unit": "bunch",
                    "priority": 1,
                    "status": "purchased",
                },
            ],
        }

        card = self._propose()
        replay = self._propose()

        self.assertEqual(card, replay)
        self.assertEqual(
            set(card),
            {"proposal_id", "kind", "title", "summary", "details", "expires_at"},
        )
        self.assertEqual(card["kind"], "delete_shopping_list")
        self.assertIsInstance(card["title"], str)
        self.assertIsInstance(card["summary"], str)
        self.assertIsInstance(card["details"], dict)
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.actor_id, self.owner.pk)
        self.assertEqual(proposal.household_id, self.household.pk)
        self.assertEqual(proposal.status, "pending")
        self.assertEqual(proposal.snapshot, expected_snapshot)
        self.assertEqual(proposal_model.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self._assert_list_unchanged([self.product_item.pk, self.free_text_item.pk])

    def test_confirmation_deletes_exact_snapshot_and_persists_audit_once(self):
        card = self._propose()
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])

        confirmed = self._confirm(self.owner, proposal.pk)
        replay = self._confirm(self.owner, proposal.pk)

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(ShoppingList.objects.filter(pk=self.shopping_list.pk).exists())
        self.assertFalse(
            ShoppingListItem.objects.filter(
                pk__in=[self.product_item.pk, self.free_text_item.pk]
            ).exists()
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")
        audit = AuditEvent.objects.get(action="shopping_list.deletion_confirmed")
        self.assertEqual(audit.household_id, self.household.pk)
        self.assertEqual(audit.actor_id, self.owner.pk)
        self.assertEqual(audit.entity_type, "shopping_list")
        self.assertEqual(audit.entity_id, str(self.shopping_list.pk))
        self.assertEqual(
            audit.metadata,
            {
                "shopping_list_id": str(self.shopping_list.pk),
                "item_ids": sorted(
                    [str(self.product_item.pk), str(self.free_text_item.pk)]
                ),
                "item_count": 2,
            },
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action="shopping_list.deletion_confirmed"
            ).count(),
            1,
        )

    def test_stale_snapshot_is_terminal_and_does_not_delete_changed_data(self):
        card = self._propose()
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])
        self.shopping_list.name = "Changed after proposal"
        self.shopping_list.save(update_fields=["name"])
        self.product_item.quantity = Decimal("9.0000")
        self.product_item.save(update_fields=["quantity"])

        response = self._confirm(self.owner, proposal.pk)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["status"], "stale")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "stale")
        self.assertEqual(
            ShoppingList.objects.get(pk=self.shopping_list.pk).name,
            "Changed after proposal",
        )
        self.assertEqual(
            ShoppingListItem.objects.get(pk=self.product_item.pk).quantity,
            Decimal("9.0000"),
        )
        self.assertTrue(
            ShoppingListItem.objects.filter(pk=self.free_text_item.pk).exists()
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action="shopping_list.deletion_confirmed"
            ).exists()
        )


class ChoreOccurrenceGenerationProposalTests(TestCase):
    start_date = "2026-11-05"
    end_date = "2026-11-06"

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="occurrence-owner@example.test",
            name="Owner",
            password="test-password",
        )
        self.viewer = user_model.objects.create_user(
            email="occurrence-viewer@example.test",
            name="Viewer",
            password="test-password",
        )
        self.household = Household.objects.create(
            name="Occurrence home",
            timezone="America/Sao_Paulo",
            created_by=self.owner,
        )
        self.owner_membership = Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        self.chore = Chore.objects.create(
            household=self.household,
            title="Synthetic daily chore",
            is_active=True,
            recurrence_rule={"frequency": "daily", "time": "09:00"},
            due_at=None,
            created_by=self.owner,
        )
        self.assignment = ChoreAssignment.objects.create(
            chore=self.chore, membership=self.owner_membership
        )
        self.client = APIClient()

    def _propose(
        self,
        *,
        arguments=None,
        request_uuid="00000000-0000-4000-8000-000000000101",
        call_index=0,
        user=None,
    ):
        return dispatch_tool(
            "propose_chore_occurrence_generation",
            arguments
            or {
                "chore_id": self.chore.pk,
                "start_date": self.start_date,
                "end_date": self.end_date,
            },
            user=user or self.owner,
            household_id=self.household.pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _proposal_model(self):
        # Resolve dynamically so RED reports missing proposal behavior after dispatch.
        return apps.get_model("assistant", "AssistantActionProposal")

    def _confirm(self, user, proposal_id, *, confirm=True):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/v1/households/{self.household.pk}/assistant/actions/{proposal_id}",
            {"confirm": confirm},
            format="json",
        )

    def _occurrences(self):
        return list(
            ChoreOccurrence.objects.filter(chore=self.chore).order_by("due_at", "id")
        )

    def test_proposal_previews_safe_dates_and_snapshot_without_creating_occurrences(
        self,
    ):
        card = self._propose()
        replay = self._propose()

        self.assertEqual(card, replay)
        self.assertEqual(card["kind"], "generate_chore_occurrences")
        self.assertEqual(card["details"]["chore_title"], "Synthetic daily chore")
        self.assertEqual(card["details"]["start_date"], self.start_date)
        self.assertEqual(card["details"]["end_date"], self.end_date)
        self.assertEqual(card["details"]["count"], 2)
        self.assertEqual(
            card["details"]["due_at"],
            ["2026-11-05T12:00:00+00:00", "2026-11-06T12:00:00+00:00"],
        )
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.status, "pending")
        self.assertEqual(
            proposal.snapshot,
            {
                "chore": {
                    "id": str(self.chore.pk),
                    "title": "Synthetic daily chore",
                    "is_active": True,
                    "recurrence_rule": {"frequency": "daily", "time": "09:00"},
                    "due_at": None,
                    "assignment_ids": [str(self.owner_membership.pk)],
                },
                "start_date": self.start_date,
                "end_date": self.end_date,
                "occurrence_ids": [],
            },
        )
        self.assertEqual(ChoreOccurrence.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_preview_and_confirmation_include_only_missing_occurrences(self):
        existing = ChoreOccurrence.objects.create(
            chore=self.chore,
            due_at=datetime(2026, 11, 5, 12, tzinfo=dt_timezone.utc),
        )

        card = self._propose()

        self.assertEqual(card["details"]["count"], 1)
        self.assertEqual(card["details"]["due_at"], ["2026-11-06T12:00:00+00:00"])
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.snapshot["occurrence_ids"], [str(existing.pk)])

        response = self._confirm(self.owner, proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChoreOccurrence.objects.filter(chore=self.chore).count(), 2)
        self.assertEqual(response.data["generated_count"], 1)
        self.assertEqual(
            AuditEvent.objects.filter(action="chore.occurrences_generated").count(),
            1,
        )

    def test_proposal_rejects_when_all_occurrences_in_range_already_exist(self):
        existing = [
            ChoreOccurrence.objects.create(
                chore=self.chore,
                due_at=datetime(2026, 11, day, 12, tzinfo=dt_timezone.utc),
            )
            for day in (5, 6)
        ]

        with self.assertRaisesRegex(ValidationError, "nothing remains to generate"):
            self._propose()

        self.assertEqual(self._proposal_model().objects.count(), 0)
        self.assertEqual(self._occurrences(), existing)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_confirmation_generates_exact_occurrences_audits_once_and_replays(self):
        card = self._propose()
        proposal_model = self._proposal_model()
        proposal = proposal_model.objects.get(pk=card["proposal_id"])

        response = self._confirm(self.owner, proposal.pk)
        replay = self._confirm(self.owner, proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            [row.due_at.isoformat() for row in self._occurrences()],
            ["2026-11-05T12:00:00+00:00", "2026-11-06T12:00:00+00:00"],
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")
        self.assertEqual(
            AuditEvent.objects.filter(action="chore.occurrences_generated").count(), 1
        )

    def test_changed_rule_assignments_or_new_occurrence_make_proposal_terminal_stale(
        self,
    ):
        for index, change in enumerate(("rule", "assignment", "occurrence"), start=102):
            card = self._propose(request_uuid=f"00000000-0000-4000-8000-{index:012d}")
            proposal_model = self._proposal_model()
            proposal = proposal_model.objects.get(pk=card["proposal_id"])
            if change == "rule":
                self.chore.recurrence_rule = {"frequency": "daily", "time": "10:00"}
                self.chore.save(update_fields=["recurrence_rule"])
            elif change == "assignment":
                self.assignment.delete()
            else:
                ChoreOccurrence.objects.create(
                    chore=self.chore,
                    due_at=datetime(2026, 11, 5, 12, tzinfo=dt_timezone.utc),
                )
            before = list(self._occurrences())

            response = self._confirm(self.owner, proposal.pk)

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["status"], "stale")
            proposal.refresh_from_db()
            self.assertEqual(proposal.status, "stale")
            self.assertEqual(list(self._occurrences()), before)
            ChoreOccurrence.objects.all().delete()
            self.chore.recurrence_rule = {"frequency": "daily", "time": "09:00"}
            self.chore.save(update_fields=["recurrence_rule"])
            if not ChoreAssignment.objects.filter(pk=self.assignment.pk).exists():
                self.assignment = ChoreAssignment.objects.create(
                    chore=self.chore, membership=self.owner_membership
                )

    def test_invalid_ranges_reject_before_proposal_creation(self):
        for index, arguments in enumerate(
            (
                {
                    "chore_id": self.chore.pk,
                    "start_date": "2026-11-06",
                    "end_date": "2026-11-05",
                },
                {
                    "chore_id": self.chore.pk,
                    "start_date": "2026-11-05",
                    "end_date": "2027-11-07",
                },
            ),
            start=110,
        ):
            with self.assertRaises(ValidationError):
                self._propose(
                    arguments=arguments,
                    request_uuid=f"00000000-0000-4000-8000-{index:012d}",
                )
        proposal_model = self._proposal_model()
        self.assertEqual(proposal_model.objects.count(), 0)
        self.assertEqual(ChoreOccurrence.objects.count(), 0)

    def test_viewer_cannot_propose_or_confirm(self):
        with self.assertRaises(PermissionDenied):
            self._propose(user=self.viewer)

        card = self._propose()
        response = self._confirm(self.viewer, card["proposal_id"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ChoreOccurrence.objects.count(), 0)

    def test_cancel_expiry_and_unauthorized_actors_never_generate_occurrences(self):
        cancelled_card = self._propose(
            request_uuid="00000000-0000-4000-8000-000000000102"
        )
        proposal_model = self._proposal_model()
        cancelled = proposal_model.objects.get(pk=cancelled_card["proposal_id"])
        response = self._confirm(self.owner, cancelled.pk, confirm=False)
        self.assertEqual(response.status_code, 200)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(ChoreOccurrence.objects.count(), 0)

        expired_card = self._propose(
            request_uuid="00000000-0000-4000-8000-000000000103"
        )
        expired = proposal_model.objects.get(pk=expired_card["proposal_id"])
        expired.expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=["expires_at"])
        expired_response = self._confirm(self.owner, expired.pk)
        self.assertEqual(expired_response.status_code, 410)
        expired.refresh_from_db()
        self.assertEqual(expired.status, "expired")
        self.assertEqual(ChoreOccurrence.objects.count(), 0)

        viewer_card = self._propose(request_uuid="00000000-0000-4000-8000-000000000104")
        viewer_response = self._confirm(self.viewer, viewer_card["proposal_id"])
        self.assertEqual(viewer_response.status_code, 403)
        self.assertEqual(ChoreOccurrence.objects.count(), 0)
        self.assertFalse(
            AuditEvent.objects.filter(action="chore.occurrences_generated").exists()
        )


class MembershipAccessProposalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="membership-owner@example.test",
            name="Owner",
            password="test-password",
        )
        self.target = user_model.objects.create_user(
            email="membership-target@example.test",
            name="Target Member",
            password="test-password",
        )
        self.viewer = user_model.objects.create_user(
            email="membership-viewer@example.test",
            name="Viewer",
            password="test-password",
        )
        self.foreign = user_model.objects.create_user(
            email="membership-foreign@example.test",
            name="Foreign",
            password="test-password",
        )
        self.household = Household.objects.create(
            name="Membership home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Foreign home", created_by=self.foreign
        )
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        self.target_membership = Membership.objects.create(
            user=self.target, household=self.household, role="member"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        self.foreign_membership = Membership.objects.create(
            user=self.foreign, household=self.foreign_household, role="member"
        )
        self.client = APIClient()

    def _propose(
        self,
        *,
        membership=None,
        role="viewer",
        user=None,
        household_id=None,
        request_uuid="00000000-0000-4000-8000-000000000201",
        call_index=0,
    ):
        return dispatch_tool(
            "propose_membership_role_change",
            {"membership_id": (membership or self.target_membership).pk, "role": role},
            user=user or self.owner,
            household_id=household_id or self.household.pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _propose_ownership_transfer(
        self, membership=None, *, user=None, request_uuid, call_index
    ):
        return dispatch_tool(
            "propose_ownership_transfer",
            {"new_owner_membership_id": (membership or self.target_membership).pk},
            user=user or self.owner,
            household_id=self.household.pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _proposal_model(self):
        return apps.get_model("assistant", "AssistantActionProposal")

    def _confirm(self, proposal_id, *, household_id=None):
        self.client.force_authenticate(self.owner)
        return self.client.post(
            f"/api/v1/households/{household_id or self.household.pk}/assistant/actions/{proposal_id}",
            {"confirm": True},
            format="json",
        )

    def test_role_change_preview_confirmation_and_replay(self):
        before_audit = list(AuditEvent.objects.values_list("pk", flat=True))

        card = self._propose()

        self.assertEqual(card["kind"], "membership_role_change")
        self.assertIn(self.target.name, str(card["details"]))
        self.assertIn("member", str(card["details"]))
        self.assertIn("viewer", str(card["details"]))
        self.assertEqual(self.target_membership.role, "member")
        self.assertEqual(
            list(AuditEvent.objects.values_list("pk", flat=True)), before_audit
        )
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])

        response = self._confirm(proposal.pk)
        replay = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.role, "viewer")
        self.assertEqual(
            Membership.objects.filter(household=self.household, role="viewer").count(),
            2,
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="membership.role_changed").count(), 1
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")
        self.assertEqual(response.data, replay.data)

    def test_membership_removal_preview_confirmation_and_replay(self):
        card = dispatch_tool(
            "propose_membership_removal",
            {"membership_id": self.target_membership.pk},
            user=self.owner,
            household_id=self.household.pk,
            request_uuid="00000000-0000-4000-8000-000000000301",
            call_index=0,
        )

        self.assertEqual(card["kind"], "membership_removal")
        self.assertIn(self.target.name, str(card["details"]))
        self.assertIn("member", str(card["details"]))
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.status, "active")
        self.assertFalse(AuditEvent.objects.exists())
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])

        response = self._confirm(proposal.pk)
        replay = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.status, "removed")
        self.assertTrue(
            Membership.objects.filter(pk=self.target_membership.pk).exists()
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")
        self.assertEqual(
            AuditEvent.objects.filter(action="membership.removed").count(), 1
        )

    def test_owner_cannot_propose_removal_of_self_or_another_owner(self):
        owner_membership = Membership.objects.get(
            user=self.owner, household=self.household
        )
        another_owner = get_user_model().objects.create_user(
            email="membership-another-owner@example.test",
            name="Another Owner",
            password="test-password",
        )
        another_owner_membership = Membership.objects.create(
            user=another_owner, household=self.household, role="owner"
        )

        for index, membership in enumerate(
            (owner_membership, another_owner_membership), start=302
        ):
            with self.subTest(membership_id=membership.pk):
                with self.assertRaises((ValidationError, PermissionDenied)):
                    dispatch_tool(
                        "propose_membership_removal",
                        {"membership_id": membership.pk},
                        user=self.owner,
                        household_id=self.household.pk,
                        request_uuid=f"00000000-0000-4000-8000-{index:012d}",
                        call_index=0,
                    )

        owner_membership.refresh_from_db()
        another_owner_membership.refresh_from_db()
        self.assertEqual(owner_membership.status, "active")
        self.assertEqual(another_owner_membership.status, "active")
        self.assertFalse(self._proposal_model().objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_viewer_cannot_propose_role_change(self):
        with self.assertRaises(PermissionDenied):
            self._propose(user=self.viewer)
        self.assertEqual(self.target_membership.role, "member")
        self.assertFalse(self._proposal_model().objects.exists())

    def test_membership_from_another_household_cannot_be_proposed(self):
        with self.assertRaises((PermissionDenied, ValidationError)):
            self._propose(membership=self.foreign_membership)
        self.assertEqual(self.foreign_membership.role, "member")
        self.assertFalse(self._proposal_model().objects.exists())

    def test_proposal_cannot_be_confirmed_through_another_household(self):
        card = self._propose()
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])

        response = self._confirm(proposal.pk, household_id=self.foreign_household.pk)

        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.target_membership.role, "member")
        self.assertFalse(
            AuditEvent.objects.filter(action="membership.role_changed").exists()
        )

    def test_owner_role_cannot_be_assigned_through_role_change_tool(self):
        with self.assertRaises(ValidationError):
            self._propose(role="owner")
        self.assertEqual(self.target_membership.role, "member")
        self.assertFalse(self._proposal_model().objects.exists())

    def test_changed_target_membership_snapshot_makes_proposal_stale_without_mutation(
        self,
    ):
        card = self._propose()
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
        self.target_membership.status = "removed"
        self.target_membership.save(update_fields=["status"])
        audit_count = AuditEvent.objects.count()

        response = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["status"], "stale")
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.status, "removed")
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "stale")

    def test_ownership_transfer_preview_is_non_mutating_and_confirmation_replays(self):
        owner_membership = Membership.objects.get(
            user=self.owner, household=self.household
        )
        card = self._propose_ownership_transfer(
            request_uuid="00000000-0000-4000-8000-000000000401", call_index=1
        )

        self.assertEqual(card["kind"], "ownership_transfer")
        self.assertIn(self.owner.name, str(card["details"]))
        self.assertIn(self.target.name, str(card["details"]))
        owner_membership.refresh_from_db()
        self.target_membership.refresh_from_db()
        self.assertEqual(owner_membership.role, "owner")
        self.assertEqual(self.target_membership.role, "member")
        self.assertEqual(owner_membership.status, "active")
        self.assertEqual(self.target_membership.status, "active")
        self.assertFalse(AuditEvent.objects.exists())
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.status, "pending")

        response = self._confirm(proposal.pk)
        replay = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(response.data, replay.data)
        owner_membership.refresh_from_db()
        self.target_membership.refresh_from_db()
        self.assertEqual(owner_membership.role, "member")
        self.assertEqual(self.target_membership.role, "owner")
        self.assertEqual(owner_membership.status, "active")
        self.assertEqual(self.target_membership.status, "active")
        self.assertEqual(
            Membership.objects.filter(
                household=self.household, role="owner", status="active"
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="household.ownership_transferred").count(),
            1,
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")

    def test_ownership_transfer_rejects_invalid_self_foreign_and_viewer_targets(self):
        owner_membership = Membership.objects.get(
            user=self.owner, household=self.household
        )
        invalid_target = Membership.objects.create(
            user=get_user_model().objects.create_user(
                email="membership-invalid@example.test",
                name="Invalid",
                password="test-password",
            ),
            household=self.household,
            role="viewer",
        )
        cases = (
            (owner_membership, "00000000-0000-4000-8000-000000000402"),
            (invalid_target, "00000000-0000-4000-8000-000000000403"),
            (self.foreign_membership, "00000000-0000-4000-8000-000000000404"),
        )
        for index, (membership, request_uuid) in enumerate(cases, start=1):
            with self.subTest(membership_id=membership.pk):
                with self.assertRaises((ValidationError, PermissionDenied)):
                    self._propose_ownership_transfer(
                        membership,
                        request_uuid=request_uuid,
                        call_index=index,
                    )

        with self.assertRaises(PermissionDenied):
            self._propose_ownership_transfer(
                user=self.viewer,
                request_uuid="00000000-0000-4000-8000-000000000405",
                call_index=1,
            )
        self.assertFalse(self._proposal_model().objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
        owner_membership.refresh_from_db()
        self.assertEqual(owner_membership.role, "owner")
        self.assertEqual(self.target_membership.role, "member")
        self.assertEqual(invalid_target.role, "viewer")
        self.assertEqual(self.foreign_membership.role, "member")

    def test_changed_ownership_transfer_target_role_or_status_makes_proposal_stale(
        self,
    ):
        for index, change in enumerate(("role", "status"), start=406):
            with self.subTest(change=change):
                card = self._propose_ownership_transfer(
                    request_uuid=f"00000000-0000-4000-8000-{index:012d}",
                    call_index=index,
                )
                proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
                if change == "role":
                    self.target_membership.role = "viewer"
                    self.target_membership.save(update_fields=["role"])
                else:
                    self.target_membership.status = "removed"
                    self.target_membership.save(update_fields=["status"])
                changed_role = self.target_membership.role
                changed_status = self.target_membership.status
                audit_count = AuditEvent.objects.count()

                response = self._confirm(proposal.pk)

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["status"], "stale")
                self.target_membership.refresh_from_db()
                self.assertEqual(self.target_membership.role, changed_role)
                self.assertEqual(self.target_membership.status, changed_status)
                self.assertEqual(AuditEvent.objects.count(), audit_count)
                proposal.refresh_from_db()
                self.assertEqual(proposal.status, "stale")
                self.target_membership.role = "member"
                self.target_membership.status = "active"
                self.target_membership.save(update_fields=["role", "status"])


class InvitationProposalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="invitation-owner@example.test",
            name="Owner",
            password="test-password",
        )
        self.viewer = user_model.objects.create_user(
            email="invitation-viewer@example.test",
            name="Viewer",
            password="test-password",
        )
        self.foreign = user_model.objects.create_user(
            email="invitation-foreign@example.test",
            name="Foreign",
            password="test-password",
        )
        self.acceptor = user_model.objects.create_user(
            email="invitation-acceptor@example.test",
            name="Acceptor",
            password="test-password",
        )
        self.household = Household.objects.create(
            name="Invitation home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Other invitation home", created_by=self.foreign
        )
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        Membership.objects.create(
            user=self.foreign, household=self.foreign_household, role="owner"
        )
        self.client = APIClient()

    def _proposal_model(self):
        return apps.get_model("assistant", "AssistantActionProposal")

    def _propose(
        self, tool, arguments, *, request_uuid, call_index=0, user=None, household=None
    ):
        return dispatch_tool(
            tool,
            arguments,
            user=user or self.owner,
            household_id=(household or self.household).pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _confirm(self, proposal_id):
        self.client.force_authenticate(self.owner)
        return self.client.post(
            f"/api/v1/households/{self.household.pk}/assistant/actions/{proposal_id}",
            {"confirm": True},
            format="json",
        )

    def test_invitation_creation_preview_confirmation_secret_storage_and_replay(self):
        for index, role in enumerate(("member", "viewer"), start=501):
            with self.subTest(role=role):
                card = self._propose(
                    "propose_invitation_creation",
                    {"role": role},
                    request_uuid=f"00000000-0000-4000-8000-{index:012d}",
                    call_index=index,
                )
                self.assertEqual(card["kind"], "invitation_creation")
                self.assertIn(role, str(card))
                self.assertIn("7", str(card))
                self.assertNotIn("token", str(card).lower())
                self.assertEqual(Invitation.objects.count(), 0)
                proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
                self.assertEqual(proposal.status, "pending")
                self.assertEqual(AuditEvent.objects.count(), 0)

                response = self._confirm(proposal.pk)
                replay = self._confirm(proposal.pk)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(response.data, replay.data)
                token = response.data["token"]
                self.assertTrue(token)
                invitation = Invitation.objects.get()
                self.assertEqual(invitation.role, role)
                self.assertEqual(invitation.household_id, self.household.pk)
                self.assertEqual(invitation.token_hash, Invitation.hash_token(token))
                self.assertNotEqual(invitation.token_hash, token)
                self.assertNotIn(token, invitation.token_hash)
                self.assertTrue(invitation.token_ciphertext)
                self.assertNotEqual(invitation.token_ciphertext, token)
                self.assertEqual(invitation.get_token(), token)
                proposal.refresh_from_db()
                self.assertNotIn(token, str(proposal.result))
                self.assertEqual(proposal.status, "confirmed")
                self.assertNotIn(token, str(card))
                self.assertEqual(
                    AuditEvent.objects.filter(action="invitation.created").count(), 1
                )
                audit = AuditEvent.objects.get(action="invitation.created")
                self.assertNotIn(token, str(audit.metadata))
                self.assertNotIn("token", str(audit.metadata).lower())
                self.assertEqual(Invitation.objects.count(), 1)
                Invitation.objects.all().delete()
                self._proposal_model().objects.all().delete()
                AuditEvent.objects.all().delete()

    def test_invitation_creation_rejects_viewer_and_owner_role(self):
        with self.assertRaises(PermissionDenied):
            self._propose(
                "propose_invitation_creation",
                {"role": "member"},
                request_uuid="00000000-0000-4000-8000-000000000511",
                user=self.viewer,
            )
        with self.assertRaises(ValidationError):
            self._propose(
                "propose_invitation_creation",
                {"role": "owner"},
                request_uuid="00000000-0000-4000-8000-000000000512",
                call_index=1,
            )
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertFalse(self._proposal_model().objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def _issue(self, household=None, *, role="member"):
        return Invitation.issue(household or self.household, self.owner, role)

    def test_invitation_revocation_preview_confirmation_and_replay(self):
        invitation, token = self._issue()
        card = self._propose(
            "propose_invitation_revocation",
            {"invitation_id": invitation.pk},
            request_uuid="00000000-0000-4000-8000-000000000521",
        )
        self.assertEqual(card["kind"], "invitation_revocation")
        self.assertNotIn(token, str(card))
        self.assertNotIn("token", str(card).lower())
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
        self.assertIsNone(invitation.revoked_at)
        self.assertEqual(AuditEvent.objects.count(), 0)

        response = self._confirm(proposal.pk)
        replay = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(response.data, replay.data)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertEqual(invitation.token_ciphertext, "")
        self.assertEqual(
            AuditEvent.objects.filter(action="invitation.revoked").count(), 1
        )
        audit = AuditEvent.objects.get(action="invitation.revoked")
        self.assertNotIn(token, str(audit.metadata))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")
        self.assertEqual(proposal.result["status"], "confirmed")
        self.assertEqual(proposal.result["invitation_id"], str(invitation.pk))
        self.assertNotIn(token, str(proposal.result))
        self.client.force_authenticate(self.acceptor)
        accepted = self.client.post(
            f"/api/v1/invitations/{token}/accept", {}, format="json"
        )
        self.assertEqual(accepted.status_code, 404)

    def test_invitation_revocation_rejects_accepted_foreign_and_revoked(self):
        accepted, _ = self._issue()
        accepted.accepted_at = timezone.now()
        accepted.save(update_fields=["accepted_at"])
        foreign, _ = self._issue(self.foreign_household)
        revoked, _ = self._issue()
        revoked.revoked_at = timezone.now()
        revoked.save(update_fields=["revoked_at"])
        for index, invitation in enumerate((accepted, foreign, revoked), start=531):
            with self.subTest(invitation_id=invitation.pk):
                with self.assertRaises((ValidationError, PermissionDenied)):
                    self._propose(
                        "propose_invitation_revocation",
                        {"invitation_id": invitation.pk},
                        request_uuid=f"00000000-0000-4000-8000-{index:012d}",
                        call_index=index,
                    )
        self.assertFalse(self._proposal_model().objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_invitation_accepted_after_preview_makes_revocation_stale(self):
        invitation, _ = self._issue()
        card = self._propose(
            "propose_invitation_revocation",
            {"invitation_id": invitation.pk},
            request_uuid="00000000-0000-4000-8000-000000000541",
        )
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])

        response = self._confirm(proposal.pk)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["status"], "stale")
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertIsNone(invitation.revoked_at)
        self.assertNotEqual(invitation.token_ciphertext, "")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "stale")
        self.assertFalse(
            AuditEvent.objects.filter(action="invitation.revoked").exists()
        )


class HouseholdArchiveProposalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="archive-owner@example.test", name="Owner", password="test-password"
        )
        self.member = user_model.objects.create_user(
            email="archive-member@example.test", name="Member", password="test-password"
        )
        self.viewer = user_model.objects.create_user(
            email="archive-viewer@example.test", name="Viewer", password="test-password"
        )
        self.household = Household.objects.create(
            name="Archive home", created_by=self.owner
        )
        self.owner_membership = Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        self.member_membership = Membership.objects.create(
            user=self.member, household=self.household, role="member"
        )
        self.viewer_membership = Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        self.category = ExpenseCategory.objects.create(
            household=self.household, name="Synthetic category"
        )
        self.expense = Expense.objects.create(
            household=self.household,
            description="Synthetic expense",
            category=self.category,
            amount_minor=1200,
            incurred_on="2026-11-01",
            created_by=self.owner,
        )
        self.shopping_list = ShoppingList.objects.create(
            household=self.household,
            name="Synthetic list",
            status=ShoppingList.Status.ACTIVE,
            created_by=self.owner,
        )
        self.invitation, self.invitation_token = Invitation.issue(
            self.household, self.owner, "member"
        )
        self.client = APIClient()

    def _proposal_model(self):
        return apps.get_model("assistant", "AssistantActionProposal")

    def _propose(
        self,
        user=None,
        *,
        request_uuid="00000000-0000-4000-8000-000000000601",
        call_index=0,
        arguments=None,
    ):
        return dispatch_tool(
            "propose_household_archive",
            {} if arguments is None else arguments,
            user=user or self.owner,
            household_id=self.household.pk,
            request_uuid=request_uuid,
            call_index=call_index,
        )

    def _confirm(self, proposal_id, user=None, confirm=True):
        self.client.force_authenticate(user or self.owner)
        return self.client.post(
            f"/api/v1/households/{self.household.pk}/assistant/actions/{proposal_id}",
            {"confirm": confirm},
            format="json",
        )

    def test_archive_preview_confirmation_and_replay(self):
        before_audits = list(AuditEvent.objects.values_list("pk", flat=True))
        card = self._propose()
        self.assertEqual(card["kind"], "household_archive")
        self.assertIn("Archive home", str(card["details"]))
        self.assertIn("3", str(card["details"]))
        self.assertIn("1", str(card["details"]))
        self.assertIn("read-only", str(card["details"]).lower())
        self.assertEqual(self._propose(call_index=0), card)
        self.assertEqual(
            set(card),
            {"proposal_id", "kind", "title", "summary", "details", "expires_at"},
        )
        proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.status, "pending")
        self.assertFalse(self.household.is_archived)
        self.assertEqual(
            Membership.objects.filter(
                household=self.household, status="active"
            ).count(),
            3,
        )
        self.assertIsNone(self.invitation.revoked_at)
        self.assertEqual(
            list(AuditEvent.objects.values_list("pk", flat=True)), before_audits
        )
        expense_id, list_id = self.expense.pk, self.shopping_list.pk

        confirmed = self._confirm(proposal.pk)
        replay = self._confirm(proposal.pk)

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.household.refresh_from_db()
        self.assertTrue(self.household.is_archived)
        self.assertEqual(self.household.archived_by_id, self.owner.pk)
        self.assertIsNotNone(self.household.archived_at)
        self.assertEqual(
            set(
                Membership.objects.filter(household=self.household).values_list(
                    "status", flat=True
                )
            ),
            {"archived"},
        )
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.revoked_at)
        self.assertEqual(self.invitation.token_ciphertext, "")
        self.assertTrue(Expense.objects.filter(pk=expense_id).exists())
        self.assertTrue(ShoppingList.objects.filter(pk=list_id).exists())
        self.assertEqual(
            list(
                AuditEvent.objects.exclude(action="household.archived").values_list(
                    "pk", flat=True
                )
            ),
            before_audits,
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="household.archived").count(), 1
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "confirmed")

    def test_archive_retains_reads_denies_writes_and_member_can_create_household(self):
        card = self._propose()
        self.assertEqual(
            self._confirm(
                self._proposal_model().objects.get(pk=card["proposal_id"]).pk
            ).status_code,
            200,
        )
        expense_count, list_count, audit_count = (
            Expense.objects.count(),
            ShoppingList.objects.count(),
            AuditEvent.objects.count(),
        )
        for user in (self.owner, self.member, self.viewer):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/v1/households").status_code, 200)
            self.assertEqual(
                self.client.get(
                    f"/api/v1/households/{self.household.pk}/members"
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/v1/households/{self.household.pk}/expenses"
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/v1/households/{self.household.pk}/shopping-lists"
                ).status_code,
                200,
            )
        self.client.force_authenticate(self.owner)
        self.assertGreaterEqual(
            self.client.post(
                f"/api/v1/households/{self.household.pk}/expenses",
                {
                    "description": "Denied",
                    "category_id": self.category.pk,
                    "amount_minor": 1,
                    "incurred_on": "2026-11-02",
                    "split_method": "equal",
                    "splits": [{"membership_id": self.owner_membership.pk}],
                },
                format="json",
            ).status_code,
            400,
        )
        self.assertGreaterEqual(
            self.client.post(
                f"/api/v1/households/{self.household.pk}/shopping-lists",
                {"name": "Denied"},
                format="json",
            ).status_code,
            400,
        )
        with self.assertRaises((PermissionDenied, ValidationError)):
            dispatch_tool(
                "create_shopping_list",
                {"name": "Denied"},
                user=self.owner,
                household_id=self.household.pk,
                request_uuid="00000000-0000-4000-8000-000000000602",
                call_index=0,
            )
        self.assertEqual(Expense.objects.count(), expense_count)
        self.assertEqual(ShoppingList.objects.count(), list_count)
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        self.client.force_authenticate(self.member)
        created = self.client.post(
            "/api/v1/households", {"name": "New active home"}, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(
            self.client.get(
                f"/api/v1/households/{self.household.pk}/expenses"
            ).status_code,
            200,
        )

    def test_new_membership_or_invitation_after_preview_makes_archive_stale(self):
        user_model = get_user_model()
        for index, kind in enumerate(("membership", "invitation"), start=603):
            with self.subTest(kind=kind):
                card = self._propose(
                    request_uuid=f"00000000-0000-4000-8000-{index:012d}"
                )
                proposal = self._proposal_model().objects.get(pk=card["proposal_id"])
                if kind == "membership":
                    added_user = user_model.objects.create_user(
                        email=f"archive-added-{index}@example.test",
                        name="Added",
                        password="test-password",
                    )
                    added = Membership.objects.create(
                        user=added_user, household=self.household, role="member"
                    )
                else:
                    added, token = Invitation.issue(
                        self.household, self.owner, "viewer"
                    )
                memberships_before = list(
                    Membership.objects.filter(household=self.household).values_list(
                        "pk", "status"
                    )
                )
                invitations_before = list(
                    Invitation.objects.filter(household=self.household).values_list(
                        "pk", "revoked_at", "token_ciphertext"
                    )
                )
                response = self._confirm(proposal.pk)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["status"], "stale")
                self.household.refresh_from_db()
                self.assertFalse(self.household.is_archived)
                self.assertEqual(
                    list(
                        Membership.objects.filter(household=self.household).values_list(
                            "pk", "status"
                        )
                    ),
                    memberships_before,
                )
                self.assertEqual(
                    list(
                        Invitation.objects.filter(household=self.household).values_list(
                            "pk", "revoked_at", "token_ciphertext"
                        )
                    ),
                    invitations_before,
                )
                proposal.refresh_from_db()
                self.assertEqual(proposal.status, "stale")
                if kind == "membership":
                    added.delete()
                else:
                    added.delete()
                self._proposal_model().objects.filter(pk=proposal.pk).delete()

    def test_viewer_cannot_propose_household_archive(self):
        with self.assertRaises(PermissionDenied):
            self._propose(user=self.viewer)
        self.assertFalse(self._proposal_model().objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
