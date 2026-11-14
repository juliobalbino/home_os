"""Removal proposals must name exact records and preserve unrelated data."""

import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.assistant.models import AssistantActionProposal
from apps.assistant.operator import dispatch_tool
from apps.assistant.proposals import confirm_proposal
from apps.audit.models import AuditEvent
from apps.chores.models import Chore, ChoreOccurrence
from apps.finance.models import Budget, Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.households.models import Household, Membership
from apps.inventory.models import InventoryEvent, InventoryItem
from apps.shopping.models import (
    Product,
    Purchase,
    PurchaseItem,
    ShoppingList,
    ShoppingListItem,
)


class RecordCleanupTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="cleanup@example.test", name="Owner", password="test-password"
        )
        self.house = Household.objects.create(name="Home", created_by=self.owner)
        self.member = Membership.objects.create(
            user=self.owner, household=self.house, role="owner"
        )
        self.product = Product.objects.create(
            household=self.house, name="Café DEMO", unit="un"
        )
        self.shopping_list = ShoppingList.objects.create(
            household=self.house, name="DEMO - Lista semanal", created_by=self.owner
        )
        self.list_item = ShoppingListItem.objects.create(
            shopping_list=self.shopping_list,
            product=self.product,
            quantity=Decimal("1"),
            unit="un",
            added_by=self.owner,
        )
        self.inventory_item = InventoryItem.objects.create(
            household=self.house, product=self.product, quantity=Decimal("1"), unit="un"
        )
        self.inventory_event = InventoryEvent.objects.create(
            item=self.inventory_item,
            event_type="adjustment",
            quantity_delta=Decimal("1"),
            created_by=self.owner,
        )
        self.chore = Chore.objects.create(
            household=self.house, title="Limpar DEMO", created_by=self.owner
        )
        self.occurrence = ChoreOccurrence.objects.create(
            chore=self.chore, due_at=timezone.now()
        )
        self.category = ExpenseCategory.objects.create(
            household=self.house, name="Lazer DEMO"
        )
        self.expense = Expense.objects.create(
            household=self.house,
            description="Cinema",
            category=self.category,
            amount_minor=2500,
            incurred_on=date(2026, 11, 1),
            created_by=self.owner,
        )
        self.split = ExpenseSplit.objects.create(
            expense=self.expense, membership=self.member, amount_minor=2500
        )
        self.payment = Payment.objects.create(
            household=self.house,
            expense=self.expense,
            payer=self.member,
            amount_minor=2500,
        )
        self.budget = Budget.objects.create(
            household=self.house,
            category=self.category,
            period_start=date(2026, 11, 1),
            amount_minor=5000,
        )

    def selection(self):
        return {
            "shopping_list_ids": [self.shopping_list.pk],
            "product_ids": [self.product.pk],
            "chore_ids": [self.chore.pk],
            "category_ids": [self.category.pk],
            "expense_ids": [self.expense.pk],
        }

    def propose(self, selection=None):
        return dispatch_tool(
            "propose_record_cleanup",
            selection or self.selection(),
            user=self.owner,
            household_id=self.house.pk,
            request_uuid="00000000-0000-4000-8000-000000000014",
            call_index=0,
        )

    def test_confirmation_removes_exact_selection_and_dependents(self):
        real_product = Product.objects.create(
            household=self.house, name="Café de verdade", unit="un"
        )
        card = self.propose()
        self.assertEqual(self.propose(), card)
        self.assertEqual(card["kind"], "record_cleanup")
        self.assertEqual(len(card["details"]["records"]), 5)
        expense_preview = next(
            item for item in card["details"]["records"] if item["type"] == "Despesa"
        )
        self.assertEqual(
            expense_preview["detail"], "BRL 25,00 · 01/11/2026 · Lazer DEMO"
        )
        self.assertTrue(Expense.objects.filter(pk=self.expense.pk).exists())
        result = confirm_proposal(
            user=self.owner,
            household_id=self.house.pk,
            proposal_id=card["proposal_id"],
            confirm=True,
        )
        self.assertEqual(result["status"], 200)
        self.assertFalse(ShoppingList.objects.filter(pk=self.shopping_list.pk).exists())
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())
        self.assertFalse(
            InventoryItem.objects.filter(pk=self.inventory_item.pk).exists()
        )
        self.assertFalse(
            InventoryEvent.objects.filter(pk=self.inventory_event.pk).exists()
        )
        self.assertFalse(Chore.objects.filter(pk=self.chore.pk).exists())
        self.assertFalse(ChoreOccurrence.objects.filter(pk=self.occurrence.pk).exists())
        self.assertFalse(Expense.objects.filter(pk=self.expense.pk).exists())
        self.assertFalse(ExpenseCategory.objects.filter(pk=self.category.pk).exists())
        self.assertFalse(Budget.objects.filter(pk=self.budget.pk).exists())
        self.assertFalse(Payment.objects.filter(pk=self.payment.pk).exists())
        self.assertFalse(ExpenseSplit.objects.filter(pk=self.split.pk).exists())
        self.assertTrue(Product.objects.filter(pk=real_product.pk).exists())
        self.assertTrue(
            AuditEvent.objects.filter(action="household.records_deleted").exists()
        )
        replay = confirm_proposal(
            user=self.owner,
            household_id=self.house.pk,
            proposal_id=card["proposal_id"],
            confirm=True,
        )
        self.assertEqual(replay["status"], 200)
        self.assertEqual(AssistantActionProposal.objects.count(), 1)

    def test_product_linked_to_unselected_list_blocks_proposal(self):
        other_list = ShoppingList.objects.create(
            household=self.house, name="Lista real", created_by=self.owner
        )
        ShoppingListItem.objects.create(
            shopping_list=other_list,
            product=self.product,
            quantity=Decimal("1"),
            unit="un",
            added_by=self.owner,
        )
        with self.assertRaises(ValidationError):
            self.propose()
        self.assertEqual(AssistantActionProposal.objects.count(), 0)
        self.assertTrue(ShoppingList.objects.filter(pk=other_list.pk).exists())

    def test_numeric_ids_sent_as_strings_are_resolved_to_the_same_records(self):
        selection = {
            key: [str(value) for value in values]
            for key, values in self.selection().items()
        }
        card = self.propose(selection)
        self.assertEqual(len(card["details"]["records"]), 5)
        proposal = AssistantActionProposal.objects.get(pk=card["proposal_id"])
        self.assertEqual(proposal.payload["product_ids"], [self.product.pk])

    def test_change_after_proposal_makes_it_stale(self):
        card = self.propose()
        self.product.name = "Café alterado"
        self.product.save(update_fields=["name"])
        result = confirm_proposal(
            user=self.owner,
            household_id=self.house.pk,
            proposal_id=card["proposal_id"],
            confirm=True,
        )
        self.assertEqual(result["status"], 409)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_blocked_cleanup_explains_the_link_to_an_unselected_list(self):
        from apps.assistant.services import _operator_completion

        other_list = ShoppingList.objects.create(
            household=self.house, name="Lista real", created_by=self.owner
        )
        ShoppingListItem.objects.create(
            shopping_list=other_list,
            product=self.product,
            quantity=Decimal("1"),
            unit="un",
            added_by=self.owner,
        )
        outputs = [
            [
                {
                    "type": "function_call",
                    "call_id": "cleanup",
                    "name": "propose_record_cleanup",
                    "arguments": json.dumps(self.selection()),
                }
            ],
            [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Não foi possível preparar a remoção.",
                        }
                    ],
                }
            ],
        ]

        def response(*args, **kwargs):
            event = {
                "type": "response.completed",
                "response": {"output": outputs.pop(0)},
            }
            return BytesIO(b"data: " + json.dumps(event).encode() + b"\n\n")

        with patch(
            "apps.assistant.services.urllib.request.urlopen", side_effect=response
        ):
            result = _operator_completion(
                model="test-model",
                token="test-token",
                text="Remova os dados DEMO",
                user=self.owner,
                household_id=self.house.pk,
                request_uuid="00000000-0000-4000-8000-000000000014",
            )
        self.assertIn("fora da seleção", result["issues"][0]["message"])

    def test_linked_purchase_is_removed_with_its_expense_and_product(self):
        purchase = Purchase.objects.create(
            household=self.house,
            purchased_at=date(2026, 11, 1),
            total_amount_minor=2500,
            created_by=self.owner,
            buyer=self.member,
            shopping_list=self.shopping_list,
            idempotency_key="demo-purchase",
            payload_hash="a" * 64,
            expense=self.expense,
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            quantity=Decimal("1"),
            unit="un",
            unit_price_minor=2500,
            line_total_minor=2500,
            shopping_list_item=self.list_item,
        )
        InventoryEvent.objects.create(
            item=self.inventory_item,
            event_type="purchase",
            quantity_delta=Decimal("1"),
            created_by=self.owner,
            source_purchase_item=purchase_item,
        )
        card = self.propose()
        self.assertEqual(card["details"]["dependent_count"], 10)
        confirmed = confirm_proposal(
            user=self.owner,
            household_id=self.house.pk,
            proposal_id=card["proposal_id"],
            confirm=True,
        )
        self.assertEqual(confirmed["status"], 200)
        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertFalse(PurchaseItem.objects.filter(pk=purchase_item.pk).exists())

    def test_list_item_used_by_an_unselected_purchase_blocks_proposal(self):
        purchase = Purchase.objects.create(
            household=self.house,
            purchased_at=date(2026, 11, 1),
            total_amount_minor=2500,
            created_by=self.owner,
            buyer=self.member,
            idempotency_key="real-purchase",
            payload_hash="b" * 64,
            expense=self.expense,
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            quantity=Decimal("1"),
            unit="un",
            unit_price_minor=2500,
            line_total_minor=2500,
            shopping_list_item=self.list_item,
        )
        selection = {
            "shopping_list_ids": [self.shopping_list.pk],
            "product_ids": [],
            "chore_ids": [],
            "category_ids": [],
            "expense_ids": [],
        }
        with self.assertRaises(ValidationError):
            self.propose(selection)
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
