import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from decimal import Decimal
from datetime import date, datetime, timezone as dt_timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.assistant.operator import dispatch_tool, tool_definitions
from apps.audit.models import AuditEvent
from apps.chores.models import Chore, ChoreAssignment, ChoreCompletion, ChoreOccurrence
from apps.finance.models import Budget, Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.households.models import Household, Membership
from apps.inventory.models import InventoryEvent, InventoryItem
from apps.shopping.models import (
    PriceObservation,
    Product,
    ProductAlias,
    Purchase,
    PurchaseItem,
    ShoppingList,
    ShoppingListItem,
)


def completed_stream(output):
    event = {"type": "response.completed", "response": {"output": output}}
    return BytesIO(b"data: " + json.dumps(event).encode() + b"\n\n")


def failed_stream(code):
    event = {
        "type": "response.failed",
        "response": {"id": "resp-synthetic", "error": {"code": code}},
    }
    return BytesIO(b"data: " + json.dumps(event).encode() + b"\n\n")


class OperatorReadTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="operator@example.test", name="Operator", password="test-password"
        )
        self.household = Household.objects.create(name="Home", created_by=self.owner)
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )

    def test_household_members_tool_is_scoped_and_omits_email(self):
        result = dispatch_tool(
            "household_members", {}, user=self.owner, household_id=self.household.id
        )
        self.assertEqual(result[0]["name"], "Operator")
        self.assertNotIn("email", result[0])

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            dispatch_tool(
                "arbitrary", {}, user=self.owner, household_id=self.household.id
            )

    def test_tools_describe_the_data_they_read_and_change(self):
        definitions = {item["name"]: item["description"] for item in tool_definitions()}
        self.assertIn("shopping list", definitions["shopping_lists"].lower())
        self.assertIn("item", definitions["add_shopping_list_item"].lower())
        self.assertIn("expense", definitions["create_expense"].lower())
        self.assertIn("inventory", definitions["record_inventory_event"].lower())
        self.assertIn("chore", definitions["create_chore"].lower())
        self.assertIn("necessary", definitions["ask_clarification"].lower())

    def test_operator_returns_clickable_choices_without_writing(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        output = [
            {
                "type": "function_call",
                "call_id": "clarify-1",
                "name": "ask_clarification",
                "arguments": json.dumps(
                    {
                        "question": "Qual lista devo usar?",
                        "options": ["Mercado", "Farmácia"],
                    }
                ),
            }
        ]
        with patch(
            "apps.assistant.services.urllib.request.urlopen",
            return_value=completed_stream(output),
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Adicione leite à lista",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )
        self.assertEqual(
            result["clarification"],
            {
                "question": "Qual lista devo usar?",
                "options": [
                    {"id": "1", "label": "Mercado"},
                    {"id": "2", "label": "Farmácia"},
                ],
            },
        )
        self.assertEqual(result["applied"], [])
        self.assertFalse(ShoppingList.objects.exists())

    def test_plain_question_is_retried_as_clickable_choices(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        outputs = [
            [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Qual lista devo usar?"}
                    ],
                }
            ],
            [
                {
                    "type": "function_call",
                    "call_id": "clarify-2",
                    "name": "ask_clarification",
                    "arguments": json.dumps(
                        {
                            "question": "Qual lista devo usar?",
                            "options": ["Mercado", "Farmácia"],
                        }
                    ),
                }
            ],
        ]
        requests = []

        def mocked_urlopen(request, timeout=None):
            requests.append(json.loads(request.data))
            return completed_stream(outputs.pop(0))

        with patch(
            "apps.assistant.services.urllib.request.urlopen", side_effect=mocked_urlopen
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Adicione leite à lista",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )
        self.assertEqual(result["clarification"]["question"], "Qual lista devo usar?")
        self.assertEqual(
            requests[1]["tool_choice"],
            {"type": "function", "name": "ask_clarification"},
        )

    def test_tool_arguments_are_strict(self):
        with self.assertRaises(ValueError):
            dispatch_tool(
                "household_members",
                {"household_id": str(self.household.id)},
                user=self.owner,
                household_id=self.household.id,
            )

    def test_household_metadata_never_contains_invitation_digest(self):
        result = dispatch_tool(
            "household_metadata", {}, user=self.owner, household_id=self.household.id
        )
        self.assertNotIn("email", str(result).lower())
        self.assertNotIn("token", str(result).lower())

    def test_operator_tool_loop_is_bounded_and_returns_text_with_no_actions(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        output = [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Resumo da casa"}],
            }
        ]
        requests = []

        def mocked_urlopen(request, timeout=None):
            requests.append(json.loads(request.data))
            return completed_stream(output)

        with patch(
            "apps.assistant.services.urllib.request.urlopen", side_effect=mocked_urlopen
        ):
            answer = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Resumo",
                user=self.owner,
                household_id=self.household.id,
            )
        self.assertEqual(
            answer,
            {"text": "Resumo da casa", "actions": [], "applied": [], "issues": []},
        )
        self.assertIs(requests[0]["stream"], True)
        self.assertIs(requests[0]["store"], False)
        self.assertEqual(requests[0]["input"], [{"role": "user", "content": "Resumo"}])

    def test_operator_stream_failure_reports_plan_limit_without_writing(self):
        from unittest.mock import patch
        from apps.assistant.services import AssistantUnavailable, _operator_completion

        with patch(
            "apps.assistant.services.urllib.request.urlopen",
            return_value=failed_stream("subscription_sharing_usage_limit_exceeded"),
        ):
            with self.assertRaisesMessage(AssistantUnavailable, "Limite do plano"):
                _operator_completion(
                    model="mock-model",
                    token="synthetic-token",
                    text="Adicione arroz à lista",
                    user=self.owner,
                    household_id=self.household.id,
                )
        self.assertFalse(ShoppingList.objects.exists())

    def test_operator_replays_reasoning_and_forwards_photo(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        outputs = [
            [{"type": "reasoning", "id": "rs_1", "summary": []}],
            [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "É leite."}],
                }
            ],
        ]
        requests = []

        def mocked_urlopen(request, timeout=None):
            requests.append(json.loads(request.data))
            return completed_stream(outputs.pop(0))

        content = [
            {"type": "input_text", "text": "O que há na foto?"},
            {"type": "input_image", "image_url": "data:image/png;base64,AA=="},
        ]
        with patch(
            "apps.assistant.services.urllib.request.urlopen", side_effect=mocked_urlopen
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text=content,
                user=self.owner,
                household_id=self.household.id,
            )
        self.assertEqual(result["text"], "É leite.")
        self.assertEqual(requests[0]["input"][0]["content"], content)
        self.assertEqual(requests[1]["input"][1]["type"], "reasoning")

    def test_operator_reports_failed_write_without_claiming_success(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        outputs = [
            [
                {
                    "type": "function_call",
                    "call_id": "bad",
                    "name": "add_shopping_list_item",
                    "arguments": "{}",
                }
            ],
            [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Não consegui adicionar."}
                    ],
                }
            ],
        ]
        with patch(
            "apps.assistant.services.urllib.request.urlopen",
            side_effect=lambda request, timeout=None: completed_stream(outputs.pop(0)),
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Adicione leite",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )
        self.assertEqual(result["applied"], [])
        self.assertEqual(
            result["issues"],
            [
                {
                    "tool": "add_shopping_list_item",
                    "message": "Não foi possível concluir esta alteração.",
                }
            ],
        )

    def test_operator_preserves_confirmed_write_when_followup_response_fails(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        responses = [
            completed_stream(
                [
                    {
                        "type": "function_call",
                        "call_id": "create",
                        "name": "create_shopping_list",
                        "arguments": '{"name":"Mercado"}',
                    }
                ]
            ),
            failed_stream("subscription_sharing_usage_unavailable"),
        ]
        with patch(
            "apps.assistant.services.urllib.request.urlopen",
            side_effect=lambda request, timeout=None: responses.pop(0),
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Crie Mercado",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )
        self.assertEqual(
            result["applied"],
            [{"tool": "create_shopping_list", "summary": "Lista de compras criada"}],
        )
        self.assertTrue(ShoppingList.objects.filter(name="Mercado").exists())
        self.assertTrue(result["issues"])

    def test_operator_returns_confirmed_action_proposal_without_deleting_list(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        shopping_list = ShoppingList.objects.create(
            household=self.household, name="Synthetic groceries", created_by=self.owner
        )
        outputs = [
            [
                {
                    "type": "function_call",
                    "call_id": "call-proposal-1",
                    "name": "propose_shopping_list_deletion",
                    "arguments": json.dumps({"shopping_list_id": shopping_list.pk}),
                }
            ],
            [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "A lista está pronta para exclusão.",
                        }
                    ],
                }
            ],
        ]
        requests = []

        def mocked_urlopen(request, timeout=None):
            requests.append(json.loads(request.data))
            return completed_stream(outputs.pop(0))

        with patch(
            "apps.assistant.services.urllib.request.urlopen", side_effect=mocked_urlopen
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Apague a lista",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )

        self.assertEqual(result["text"], "A lista está pronta para exclusão.")
        self.assertEqual(len(result["actions"]), 1)
        card = result["actions"][0]
        self.assertEqual(
            set(card),
            {"proposal_id", "kind", "title", "summary", "details", "expires_at"},
        )
        self.assertEqual(card["kind"], "delete_shopping_list")
        self.assertIsInstance(card["proposal_id"], str)
        self.assertIsInstance(card["title"], str)
        self.assertIsInstance(card["summary"], str)
        self.assertIsInstance(card["details"], dict)
        self.assertTrue(card["expires_at"])
        self.assertTrue(ShoppingList.objects.filter(pk=shopping_list.pk).exists())
        self.assertFalse(
            AuditEvent.objects.filter(action="shopping_list.deleted").exists()
        )

        tool_output = requests[1]["input"][-1]["output"]
        self.assertIs(requests[1]["stream"], True)
        self.assertEqual(
            requests[1]["input"][0], {"role": "user", "content": "Apague a lista"}
        )
        self.assertEqual(requests[1]["input"][1]["type"], "function_call")
        self.assertNotIn("token", tool_output.lower())
        self.assertNotIn("credential", tool_output.lower())
        self.assertNotIn("synthetic-token", tool_output)

    def test_operator_stream_adds_item_to_existing_shopping_list(self):
        from unittest.mock import patch
        from apps.assistant.services import _operator_completion

        shopping_list = ShoppingList.objects.create(
            household=self.household, name="Compras", created_by=self.owner
        )
        outputs = [
            [
                {
                    "type": "function_call",
                    "call_id": "call-add-item",
                    "name": "add_shopping_list_item",
                    "arguments": json.dumps(
                        {
                            "shopping_list_id": shopping_list.pk,
                            "free_text_name": "Arroz",
                            "quantity": "1",
                            "unit": "kg",
                        }
                    ),
                }
            ],
            [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Arroz adicionado."}],
                }
            ],
        ]

        with patch(
            "apps.assistant.services.urllib.request.urlopen",
            side_effect=lambda request, timeout=None: completed_stream(outputs.pop(0)),
        ):
            result = _operator_completion(
                model="mock-model",
                token="synthetic-token",
                text="Adicione 1 kg de arroz à lista de compras",
                user=self.owner,
                household_id=self.household.id,
                request_uuid="7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1",
            )
        self.assertEqual(result["text"], "Arroz adicionado.")
        self.assertEqual(
            result["applied"],
            [
                {
                    "tool": "add_shopping_list_item",
                    "summary": "Item adicionado à lista de compras",
                }
            ],
        )
        self.assertEqual(
            ShoppingListItem.objects.get(shopping_list=shopping_list).free_text_name,
            "Arroz",
        )


class OperatorShoppingListWriteTests(TestCase):
    REQUEST_UUID = "7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1"

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="writer@example.test", name="Writer", password="test-password"
        )
        self.viewer = user_model.objects.create_user(
            email="viewer@example.test", name="Viewer", password="test-password"
        )
        self.foreign_user = user_model.objects.create_user(
            email="foreign@example.test", name="Foreign", password="test-password"
        )
        self.household = Household.objects.create(name="Home", created_by=self.owner)
        self.foreign_household = Household.objects.create(
            name="Other home", created_by=self.foreign_user
        )
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        Membership.objects.create(
            user=self.foreign_user, household=self.foreign_household, role="owner"
        )

    def _create_list(self, *, user=None, household_id=None, arguments=None, **context):
        return dispatch_tool(
            "create_shopping_list",
            arguments if arguments is not None else {"name": "Weekly groceries"},
            user=user or self.owner,
            household_id=household_id or self.household.id,
            **context,
        )

    def test_authorized_writer_creates_scoped_list_and_one_audit_event(self):
        result = self._create_list(request_uuid=self.REQUEST_UUID, call_index=0)

        shopping_list = ShoppingList.objects.get()
        self.assertEqual(shopping_list.household, self.household)
        self.assertEqual(shopping_list.created_by, self.owner)
        self.assertEqual(shopping_list.name, "Weekly groceries")
        self.assertEqual(result["id"], shopping_list.id)
        self.assertEqual(AuditEvent.objects.count(), 1)


class OperatorFinanceWriteTests(TestCase):
    REQUEST_UUID = "5d90f5bb-29ad-42af-81c3-fdbb434a4f68"
    MAX_AMOUNT = 9223372036854775807

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="finance-owner@example.test", name="Finance owner", password="test"
        )
        self.partner = user_model.objects.create_user(
            email="finance-partner@example.test", name="Partner", password="test"
        )
        self.viewer = user_model.objects.create_user(
            email="finance-viewer@example.test", name="Viewer", password="test"
        )
        self.foreign_user = user_model.objects.create_user(
            email="finance-foreign@example.test", name="Foreign", password="test"
        )
        self.household = Household.objects.create(
            name="Finance home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Foreign home", created_by=self.foreign_user
        )
        self.owner_membership = Membership.objects.create(
            household=self.household, user=self.owner, role="owner"
        )
        self.partner_membership = Membership.objects.create(
            household=self.household, user=self.partner, role="member"
        )
        Membership.objects.create(
            household=self.household, user=self.viewer, role="viewer"
        )
        self.foreign_membership = Membership.objects.create(
            household=self.foreign_household, user=self.foreign_user, role="owner"
        )
        self.category = ExpenseCategory.objects.create(
            household=self.household, name="Utilities", kind="general"
        )
        self.foreign_category = ExpenseCategory.objects.create(
            household=self.foreign_household, name="Foreign", kind="general"
        )

    def _call(self, tool, arguments, call_index, *, user=None, household_id=None):
        return dispatch_tool(
            tool,
            arguments,
            user=user or self.owner,
            household_id=household_id or self.household.id,
            request_uuid=self.REQUEST_UUID,
            call_index=call_index,
        )

    def _expense_arguments(self, **overrides):
        arguments = {
            "description": "Electricity",
            "category_id": self.category.id,
            "amount_minor": 1001,
            "incurred_on": "2026-10-02",
            "split_method": "equal",
            "splits": [
                {"membership_id": self.owner_membership.id},
                {"membership_id": self.partner_membership.id},
            ],
        }
        arguments.update(overrides)
        return arguments

    def test_create_expense_is_scoped_split_audited_and_idempotent(self):
        arguments = self._expense_arguments()
        first = self._call("create_expense", arguments, 0)
        repeated = self._call("create_expense", arguments, 0)

        expense = Expense.objects.get()
        self.assertEqual(first, repeated)
        self.assertEqual(expense.household, self.household)
        self.assertEqual(expense.category, self.category)
        self.assertEqual(expense.created_by, self.owner)
        self.assertEqual(
            list(
                expense.splits.order_by("membership_id").values_list(
                    "amount_minor", flat=True
                )
            ),
            [501, 500],
        )
        self.assertEqual(ExpenseSplit.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="expense.created").count(), 1)

    def test_update_expense_preserves_split_history_and_audits(self):
        expense = Expense.objects.create(
            household=self.household,
            created_by=self.owner,
            category=self.category,
            description="Old description",
            amount_minor=1000,
            incurred_on="2026-10-01",
        )
        old_split = ExpenseSplit.objects.create(
            expense=expense, membership=self.owner_membership, amount_minor=1000
        )
        result = self._call(
            "update_expense",
            {
                "expense_id": expense.id,
                **self._expense_arguments(
                    description="Updated electricity", amount_minor=1200
                ),
            },
            1,
        )

        expense.refresh_from_db()
        old_split.refresh_from_db()
        self.assertEqual(expense.description, "Updated electricity")
        self.assertEqual(expense.amount_minor, 1200)
        self.assertEqual(result["id"], expense.id)
        self.assertFalse(old_split.is_current)
        self.assertEqual(ExpenseSplit.objects.filter(expense=expense).count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action="expense.updated").count(), 1)

    def test_record_payment_requires_scoped_payer_and_audits(self):
        expense = Expense.objects.create(
            household=self.household,
            created_by=self.owner,
            category=self.category,
            description="Electricity",
            amount_minor=1000,
            incurred_on="2026-10-01",
        )
        result = self._call(
            "record_expense_payment",
            {
                "expense_id": expense.id,
                "payer_id": self.partner_membership.id,
                "amount_minor": 400,
            },
            2,
        )

        payment = Payment.objects.get()
        self.assertEqual(payment.household, self.household)
        self.assertEqual(payment.payer, self.partner_membership)
        self.assertEqual(payment.amount_minor, 400)
        self.assertEqual(result["id"], payment.id)
        self.assertEqual(AuditEvent.objects.filter(action="payment.created").count(), 1)

        with self.assertRaises(ValidationError):
            self._call(
                "record_expense_payment",
                {
                    "expense_id": expense.id,
                    "payer_id": self.foreign_membership.id,
                    "amount_minor": 100,
                },
                6,
            )
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="payment.created").count(), 1)

    def test_set_budget_creates_updates_and_audits(self):
        arguments = {
            "period": "2026-10",
            "amount_minor": 2500,
            "category_id": self.category.id,
        }
        first = self._call("set_budget", arguments, 3)
        updated = self._call("set_budget", {**arguments, "amount_minor": 3000}, 4)

        self.assertEqual(Budget.objects.count(), 1)
        budget = Budget.objects.get()
        self.assertEqual(budget.household, self.household)
        self.assertEqual(budget.category, self.category)
        self.assertEqual(budget.amount_minor, 3000)
        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(AuditEvent.objects.filter(action="budget.set").count(), 2)

    def test_create_category_validates_and_audits_scoped_category(self):
        result = self._call(
            "create_expense_category",
            {"name": "Transport", "kind": "general"},
            5,
        )

        category = ExpenseCategory.objects.get(name="Transport")
        self.assertEqual(category.household, self.household)
        self.assertEqual(result["id"], category.id)
        self.assertEqual(
            AuditEvent.objects.filter(action="category.created").count(), 1
        )
        for invalid in (
            {"name": "  ", "kind": "general"},
            {"name": "Other", "kind": ""},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self._call("create_expense_category", invalid, 6)

    def test_viewer_and_foreign_household_writes_are_denied_without_mutation(self):
        expense = Expense.objects.create(
            household=self.household,
            created_by=self.owner,
            category=self.category,
            description="Existing expense",
            amount_minor=1000,
            incurred_on="2026-10-01",
        )
        operations = (
            ("create_expense", self._expense_arguments()),
            (
                "update_expense",
                {"expense_id": expense.id, **self._expense_arguments()},
            ),
            (
                "record_expense_payment",
                {
                    "expense_id": expense.id,
                    "payer_id": self.owner_membership.id,
                    "amount_minor": 100,
                },
            ),
            ("create_expense_category", {"name": "Denied", "kind": "general"}),
            ("set_budget", {"period": "2026-10", "amount_minor": 500}),
        )
        for index, (tool, arguments) in enumerate(operations):
            with self.subTest(tool=tool):
                with self.assertRaises(PermissionDenied):
                    self._call(tool, arguments, 10 + index, user=self.viewer)
                with self.assertRaises(NotFound):
                    self._call(
                        tool,
                        arguments,
                        20 + index,
                        household_id=self.foreign_household.id,
                    )

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Budget.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
        self.assertFalse(ExpenseCategory.objects.filter(name="Denied").exists())
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_amounts_above_signed_bigint_are_validation_errors_without_partial_writes(
        self,
    ):
        expense = Expense.objects.create(
            household=self.household,
            created_by=self.owner,
            category=self.category,
            description="Existing expense",
            amount_minor=self.MAX_AMOUNT,
            incurred_on="2026-10-01",
        )
        expense_args = self._expense_arguments(
            amount_minor=self.MAX_AMOUNT + 1,
            splits=[{"membership_id": self.owner_membership.id}],
        )
        for tool, arguments, index in (
            ("create_expense", expense_args, 30),
            (
                "update_expense",
                {"expense_id": expense.id, **expense_args},
                31,
            ),
            (
                "record_expense_payment",
                {
                    "expense_id": expense.id,
                    "payer_id": self.owner_membership.id,
                    "amount_minor": self.MAX_AMOUNT + 1,
                },
                32,
            ),
            (
                "set_budget",
                {"period": "2026-10", "amount_minor": self.MAX_AMOUNT + 1},
                33,
            ),
        ):
            with self.subTest(tool=tool), self.assertRaises(ValidationError):
                self._call(tool, arguments, index)

        self.assertEqual(Expense.objects.count(), 1)
        expense.refresh_from_db()
        self.assertEqual(expense.amount_minor, self.MAX_AMOUNT)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Budget.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_payment_overflow_validation_explains_supported_upper_bound(self):
        expense = Expense.objects.create(
            household=self.household,
            created_by=self.owner,
            category=self.category,
            description="Electricity",
            amount_minor=self.MAX_AMOUNT,
            incurred_on="2026-10-01",
        )
        with self.assertRaises(ValidationError) as raised:
            self._call(
                "record_expense_payment",
                {
                    "expense_id": expense.id,
                    "payer_id": self.owner_membership.id,
                    "amount_minor": self.MAX_AMOUNT + 1,
                },
                34,
            )
        self.assertIn("9223372036854775807", str(raised.exception))
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_maximum_signed_bigint_is_accepted_for_budget(self):
        result = self._call(
            "set_budget",
            {"period": "2026-10", "amount_minor": self.MAX_AMOUNT},
            35,
        )
        self.assertEqual(Budget.objects.get().amount_minor, self.MAX_AMOUNT)
        self.assertEqual(result["amount_minor"], self.MAX_AMOUNT)


class OperatorShoppingListWriteRemainingTests(TestCase):
    REQUEST_UUID = "7c8e4f4a-fb6d-4c31-86cc-0d57e976d2a1"

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="writer@example.test", name="Writer", password="test-password"
        )
        self.viewer = user_model.objects.create_user(
            email="viewer@example.test", name="Viewer", password="test-password"
        )
        self.foreign_user = user_model.objects.create_user(
            email="foreign@example.test", name="Foreign", password="test-password"
        )
        self.household = Household.objects.create(name="Home", created_by=self.owner)
        self.foreign_household = Household.objects.create(
            name="Other home", created_by=self.foreign_user
        )
        Membership.objects.create(
            user=self.owner, household=self.household, role="owner"
        )
        Membership.objects.create(
            user=self.viewer, household=self.household, role="viewer"
        )
        Membership.objects.create(
            user=self.foreign_user, household=self.foreign_household, role="owner"
        )

    def _create_list(self, *, user=None, household_id=None, arguments=None, **context):
        return dispatch_tool(
            "create_shopping_list",
            arguments if arguments is not None else {"name": "Weekly groceries"},
            user=user or self.owner,
            household_id=household_id or self.household.id,
            **context,
        )

    def test_viewer_is_denied_without_mutation(self):
        with self.assertRaises(PermissionDenied):
            self._create_list(
                user=self.viewer, request_uuid=self.REQUEST_UUID, call_index=0
            )

        self.assertEqual(ShoppingList.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_foreign_household_is_denied_without_mutation(self):
        with self.assertRaises(NotFound):
            self._create_list(
                user=self.owner,
                household_id=self.foreign_household.id,
                request_uuid=self.REQUEST_UUID,
                call_index=0,
            )

        self.assertEqual(ShoppingList.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_write_requires_valid_server_request_uuid_and_call_index(self):
        invalid_contexts = (
            {"call_index": 0},
            {"request_uuid": "not-a-uuid", "call_index": 0},
            {"request_uuid": self.REQUEST_UUID},
            {"request_uuid": self.REQUEST_UUID, "call_index": -1},
        )
        for context in invalid_contexts:
            with self.subTest(context=context), self.assertRaises(ValueError):
                self._create_list(**context)

        self.assertEqual(ShoppingList.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_repeated_identity_returns_same_result_without_duplicate_mutations(self):
        kwargs = {"request_uuid": self.REQUEST_UUID, "call_index": 3}
        first = self._create_list(**kwargs)
        repeated = self._create_list(**kwargs)

        self.assertEqual(repeated, first)
        self.assertEqual(ShoppingList.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_reused_identity_with_different_arguments_is_rejected_without_mutation(
        self,
    ):
        kwargs = {"request_uuid": self.REQUEST_UUID, "call_index": 3}
        self._create_list(**kwargs)

        with self.assertRaises(ValueError):
            self._create_list(arguments={"name": "Different list"}, **kwargs)

        self.assertEqual(ShoppingList.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)


class OperatorShoppingInventoryWriteTests(TestCase):
    REQUEST_UUID = "f6a28e2a-66fb-46e9-beb8-22682c6d01bc"
    MAX_AMOUNT = 9223372036854775807

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="shopping-owner@example.test", name="Shopping owner", password="test"
        )
        self.viewer = user_model.objects.create_user(
            email="shopping-viewer@example.test", name="Viewer", password="test"
        )
        self.foreign_user = user_model.objects.create_user(
            email="shopping-foreign@example.test", name="Foreign", password="test"
        )
        self.household = Household.objects.create(
            name="Shop home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Other home", created_by=self.foreign_user
        )
        self.member = Membership.objects.create(
            household=self.household, user=self.owner, role="owner"
        )
        Membership.objects.create(
            household=self.household, user=self.viewer, role="viewer"
        )
        Membership.objects.create(
            household=self.foreign_household, user=self.foreign_user, role="owner"
        )
        self.category = ExpenseCategory.objects.create(
            household=self.household, name="Groceries", kind="general"
        )
        self.product = Product.objects.create(
            household=self.household,
            name="Rice",
            brand="Home",
            category="Pantry",
            unit="kg",
        )
        self.foreign_product = Product.objects.create(
            household=self.foreign_household, name="Foreign rice", unit="kg"
        )
        self.shopping_list = ShoppingList.objects.create(
            household=self.household, name="Weekly", created_by=self.owner
        )

    def _call(self, tool, arguments, call_index, *, user=None, household_id=None):
        return dispatch_tool(
            tool,
            arguments,
            user=user or self.owner,
            household_id=household_id or self.household.id,
            request_uuid=self.REQUEST_UUID,
            call_index=call_index,
        )

    def test_product_create_update_alias_and_price_are_scoped_validated_and_audited(
        self,
    ):
        created = self._call(
            "create_shopping_product",
            {"name": "Oats", "brand": "Mill", "category": "Breakfast", "unit": "kg"},
            0,
        )
        product = Product.objects.get(name="Oats")
        self.assertEqual(product.household, self.household)
        self.assertEqual(created["id"], product.id)
        self._call(
            "update_shopping_product",
            {"product_id": product.id, "brand": "New Mill", "is_active": False},
            1,
        )
        product.refresh_from_db()
        self.assertEqual((product.brand, product.is_active), ("New Mill", False))
        self._call(
            "update_shopping_product",
            {"product_id": product.id, "brand": "New Mill", "is_active": False},
            1,
        )
        self._call(
            "add_shopping_product_alias",
            {"product_id": product.id, "alias": "Porridge oats"},
            2,
        )
        self._call(
            "record_price_observation",
            {
                "product_id": product.id,
                "price_minor": 499,
                "quantity": "1.5",
                "unit": "kg",
                "store_name": "Market",
            },
            3,
        )
        self.assertEqual(ProductAlias.objects.get().product, product)
        self.assertEqual(PriceObservation.objects.get().household, self.household)
        for arguments in (
            {"name": "Oats", "brand": "New Mill", "unit": "kg"},
            {"name": "", "unit": "kg"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                self._call(
                    "create_shopping_product",
                    arguments,
                    4 if arguments.get("name") else 8,
                )
        differently_branded = self._call(
            "create_shopping_product",
            {"name": "Oats", "brand": "Other Mill", "unit": "kg"},
            7,
        )
        self.assertNotEqual(differently_branded["id"], product.id)
        for tool, arguments in (
            (
                "update_shopping_product",
                {"product_id": self.foreign_product.id, "name": "Changed"},
            ),
            (
                "add_shopping_product_alias",
                {"product_id": self.foreign_product.id, "alias": "Other"},
            ),
            (
                "record_price_observation",
                {
                    "product_id": self.foreign_product.id,
                    "price_minor": 1,
                    "quantity": "1",
                    "unit": "kg",
                },
            ),
        ):
            with (
                self.subTest(tool=tool),
                self.assertRaises((NotFound, ValidationError)),
            ):
                self._call(tool, arguments, 5)
        for invalid in (
            {
                "product_id": product.id,
                "price_minor": self.MAX_AMOUNT + 1,
                "quantity": "1",
                "unit": "kg",
            },
            {
                "product_id": product.id,
                "price_minor": 10,
                "quantity": "1.12345",
                "unit": "kg",
            },
            {
                "product_id": product.id,
                "price_minor": True,
                "quantity": "1",
                "unit": "kg",
            },
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self._call("record_price_observation", invalid, 6)
        self.assertEqual(AuditEvent.objects.filter(action="product.created").count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="product.updated").count(), 1)
        self.assertEqual(
            AuditEvent.objects.filter(action="product.alias_added").count(), 1
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="price_observation.created").count(), 1
        )

    def test_product_update_reused_identity_with_changed_arguments_is_rejected(self):
        product = Product.objects.create(
            household=self.household, name="Beans", brand="Farm", unit="kg"
        )
        original = {
            "product_id": product.id,
            "brand": "First brand",
            "is_active": False,
        }
        self._call("update_shopping_product", original, 20)

        with self.assertRaises(ValueError):
            self._call(
                "update_shopping_product",
                {"product_id": product.id, "brand": "Changed brand", "is_active": True},
                20,
            )

        product.refresh_from_db()
        self.assertEqual((product.brand, product.is_active), ("First brand", False))
        self.assertEqual(AuditEvent.objects.filter(action="product.updated").count(), 1)

    def test_list_item_create_replay_update_validation_and_scoping(self):
        args = {
            "shopping_list_id": self.shopping_list.id,
            "product_id": self.product.id,
            "quantity": "2",
            "unit": "kg",
        }
        result = self._call("add_shopping_list_item", args, 0)
        self.assertEqual(result, self._call("add_shopping_list_item", args, 0))
        item = ShoppingListItem.objects.get()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.shopping_list, self.shopping_list)
        self.assertEqual(
            AuditEvent.objects.filter(action="shopping_list_item.created").count(), 1
        )
        self._call(
            "update_shopping_list_item",
            {"item_id": item.id, "status": "purchased", "quantity": "3.25"},
            1,
        )
        item.refresh_from_db()
        self.assertEqual((item.status, item.quantity), ("purchased", Decimal("3.25")))
        for changes in (
            {"status": "unknown"},
            {"quantity": "0"},
            {"quantity": "1.12345"},
            {"quantity": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self._call(
                    "update_shopping_list_item", {"item_id": item.id, **changes}, 2
                )
        self.assertEqual(
            AuditEvent.objects.filter(action="shopping_list_item.updated").count(), 1
        )

    def test_inventory_events_require_reason_and_balance_and_reject_manual_purchase(
        self,
    ):
        stock = InventoryItem.objects.create(
            household=self.household,
            product=self.product,
            quantity=Decimal("3"),
            unit="kg",
        )
        self._call(
            "record_inventory_event",
            {
                "inventory_item_id": stock.id,
                "event_type": "consumption",
                "quantity_delta": "-1",
                "notes": "Used",
            },
            0,
        )
        self._call(
            "record_inventory_event",
            {
                "inventory_item_id": stock.id,
                "event_type": "loss",
                "quantity_delta": "-0.5",
                "notes": "Spill",
            },
            1,
        )
        self._call(
            "record_inventory_event",
            {
                "inventory_item_id": stock.id,
                "event_type": "adjustment",
                "quantity_delta": "1",
                "notes": "Counted",
            },
            2,
        )
        self._call(
            "record_inventory_event",
            {
                "inventory_item_id": stock.id,
                "event_type": "correction",
                "quantity_delta": "-0.5",
                "notes": "Corrected count",
            },
            3,
        )
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("2.0000"))
        for arguments in (
            {
                "inventory_item_id": stock.id,
                "event_type": "consumption",
                "quantity_delta": "-3",
                "notes": "Use",
            },
            {
                "inventory_item_id": stock.id,
                "event_type": "purchase",
                "quantity_delta": "1",
                "notes": "Buy",
            },
            {
                "inventory_item_id": stock.id,
                "event_type": "adjustment",
                "quantity_delta": "1",
            },
            {
                "inventory_item_id": stock.id,
                "event_type": "correction",
                "quantity_delta": "-1",
            },
            {
                "inventory_item_id": stock.id,
                "event_type": "loss",
                "quantity_delta": "1.12345",
                "notes": "Loss",
            },
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                self._call("record_inventory_event", arguments, 4)
        self.assertEqual(InventoryEvent.objects.count(), 4)
        self.assertEqual(
            AuditEvent.objects.filter(action="inventory.event_recorded").count(), 4
        )

    def test_purchase_is_atomic_audited_and_idempotent_on_server_identity(self):
        needed_item = ShoppingListItem.objects.create(
            shopping_list=self.shopping_list,
            product=self.product,
            quantity=Decimal("2"),
            unit="kg",
            added_by=self.owner,
        )
        args = {
            "purchased_at": date(2026, 10, 2).isoformat(),
            "store_name": "Market",
            "category_id": self.category.id,
            "shopping_list_id": self.shopping_list.id,
            "items": [
                {
                    "product_id": self.product.id,
                    "quantity": "2",
                    "unit": "kg",
                    "unit_price_minor": 250,
                    "line_total_minor": 500,
                    "shopping_list_item_id": needed_item.id,
                }
            ],
        }
        first = self._call("record_purchase", args, 10)
        replay = self._call("record_purchase", args, 10)
        self.assertEqual(first, replay)
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.household, self.household)
        self.assertEqual(
            (purchase.total_amount_minor, purchase.expense.amount_minor), (500, 500)
        )
        self.assertEqual(PurchaseItem.objects.count(), 1)
        self.assertEqual(ExpenseSplit.objects.count(), 2)
        self.assertEqual(
            sum(ExpenseSplit.objects.values_list("amount_minor", flat=True)), 500
        )
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(
            InventoryItem.objects.get(product=self.product).quantity, Decimal("2.0000")
        )
        self.assertEqual(InventoryEvent.objects.count(), 1)
        self.assertEqual(PriceObservation.objects.count(), 1)
        self.assertEqual(
            AuditEvent.objects.filter(action="purchase.confirmed").count(), 1
        )
        needed_item.refresh_from_db()
        self.assertEqual(needed_item.status, "purchased")

    def test_purchase_rejects_stale_foreign_and_invalid_rows_without_side_effects(self):
        foreign_list = ShoppingList.objects.create(
            household=self.foreign_household,
            name="Foreign",
            created_by=self.foreign_user,
        )
        linked_item = ShoppingListItem.objects.create(
            shopping_list=self.shopping_list,
            product=self.product,
            quantity=Decimal("1"),
            unit="kg",
            added_by=self.owner,
        )
        foreign_item = ShoppingListItem.objects.create(
            shopping_list=foreign_list,
            product=self.foreign_product,
            quantity=Decimal("1"),
            unit="kg",
            added_by=self.foreign_user,
        )
        valid = {
            "purchased_at": "2026-10-02",
            "category_id": self.category.id,
            "items": [
                {
                    "product_id": self.product.id,
                    "quantity": "1",
                    "unit": "kg",
                    "unit_price_minor": 100,
                    "shopping_list_item_id": linked_item.id,
                }
            ],
        }
        invalids = (
            {
                **valid,
                "items": [
                    {**valid["items"][0], "shopping_list_item_id": foreign_item.id}
                ],
            },
            {**valid, "items": [{**valid["items"][0], "quantity": "-1"}]},
            {
                **valid,
                "items": [
                    {**valid["items"][0], "unit_price_minor": self.MAX_AMOUNT + 1}
                ],
            },
            {
                **valid,
                "items": [
                    {**valid["items"][0], "line_total_minor": self.MAX_AMOUNT + 1}
                ],
            },
        )
        for index, arguments in enumerate(invalids):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                self._call("record_purchase", arguments, 11 + index)
        linked_item.refresh_from_db()
        self.assertEqual(linked_item.status, "needed")
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
        self.assertEqual(PurchaseItem.objects.count(), 0)
        self.assertEqual(InventoryItem.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), 0)
        self.assertEqual(PriceObservation.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_purchase_rounding_to_zero_minor_units_has_no_side_effects(self):
        with self.assertRaises(ValidationError):
            self._call(
                "record_purchase",
                {
                    "purchased_at": "2026-10-02",
                    "category_id": self.category.id,
                    "items": [
                        {
                            "product_id": self.product.id,
                            "quantity": "0.0001",
                            "unit": "kg",
                            "unit_price_minor": 1,
                        }
                    ],
                },
                15,
            )

        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
        self.assertEqual(PurchaseItem.objects.count(), 0)
        self.assertEqual(InventoryItem.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), 0)
        self.assertEqual(PriceObservation.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_purchase_rejects_even_actor_matching_buyer_id_argument(self):
        with self.assertRaises(ValueError):
            self._call(
                "record_purchase",
                {
                    "purchased_at": "2026-10-02",
                    "buyer_id": self.member.id,
                    "category_id": self.category.id,
                    "items": [
                        {
                            "product_id": self.product.id,
                            "quantity": "1",
                            "unit": "kg",
                            "unit_price_minor": 100,
                        }
                    ],
                },
                16,
            )

        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)


class OperatorChoreWriteTests(TestCase):
    REQUEST_UUID = "ac80a408-564b-4948-9da4-5c7e0412b547"

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="chore-owner@example.test", name="Chore owner", password="test"
        )
        self.member_user = user_model.objects.create_user(
            email="chore-member@example.test", name="Chore member", password="test"
        )
        self.viewer = user_model.objects.create_user(
            email="chore-viewer@example.test", name="Chore viewer", password="test"
        )
        self.foreign_user = user_model.objects.create_user(
            email="chore-foreign@example.test", name="Foreign", password="test"
        )
        self.household = Household.objects.create(
            name="Chore home", created_by=self.owner
        )
        self.foreign_household = Household.objects.create(
            name="Foreign home", created_by=self.foreign_user
        )
        self.owner_membership = Membership.objects.create(
            household=self.household, user=self.owner, role="owner"
        )
        self.member_membership = Membership.objects.create(
            household=self.household, user=self.member_user, role="member"
        )
        self.viewer_membership = Membership.objects.create(
            household=self.household, user=self.viewer, role="viewer"
        )
        self.foreign_membership = Membership.objects.create(
            household=self.foreign_household, user=self.foreign_user, role="owner"
        )
        self.inactive_membership = Membership.objects.create(
            household=self.household,
            user=user_model.objects.create_user(
                email="inactive@example.test", name="Inactive", password="test"
            ),
            role="member",
            status="inactive",
        )

    def _call(self, tool, arguments, call_index, *, user=None, household_id=None):
        return dispatch_tool(
            tool,
            arguments,
            user=user or self.owner,
            household_id=household_id or self.household.id,
            request_uuid=self.REQUEST_UUID,
            call_index=call_index,
        )

    def _create_arguments(self, **overrides):
        arguments = {
            "title": "Wash dishes",
            "description": "After dinner",
            "category": "Kitchen",
            "due_at": "2026-11-05T18:30:00+00:00",
            "assignment_ids": [self.member_membership.id],
            "is_active": True,
        }
        arguments.update(overrides)
        return arguments

    def _create_chore(self, **overrides):
        values = {
            "household": self.household,
            "created_by": self.owner,
            "title": "Existing chore",
            "description": "Before",
            "category": "Home",
        }
        values.update(overrides)
        return Chore.objects.create(**values)

    def test_create_is_scoped_assigned_audited_and_idempotent(self):
        args = self._create_arguments()
        first = self._call("create_chore", args, 0)
        replay = self._call("create_chore", args, 0)

        chore = Chore.objects.get()
        self.assertEqual(first, replay)
        self.assertEqual(chore.household, self.household)
        self.assertEqual(chore.created_by, self.owner)
        self.assertEqual(
            (chore.title, chore.description, chore.category),
            ("Wash dishes", "After dinner", "Kitchen"),
        )
        self.assertEqual(
            list(chore.assignments.values_list("membership_id", flat=True)),
            [self.member_membership.id],
        )
        self.assertEqual(ChoreAssignment.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="chore.created").count(), 1)

    def test_create_accepts_a_valid_recurrence(self):
        result = self._call(
            "create_chore",
            self._create_arguments(
                due_at=None,
                recurrence_rule={"frequency": "weekly", "time": "09:00", "weekday": 2},
            ),
            1,
        )
        chore = Chore.objects.get(pk=result["id"])
        self.assertEqual(chore.recurrence_rule["frequency"], "weekly")
        self.assertIsNone(chore.due_at)

    def test_read_chores_includes_bounded_schedule_context(self):
        due_at = datetime(2026, 11, 5, 18, 30, tzinfo=dt_timezone.utc)
        due_chore = self._create_chore(due_at=due_at, recurrence_rule=None)
        ChoreAssignment.objects.create(
            chore=due_chore, membership=self.member_membership
        )
        recurring_chore = self._create_chore(
            title="Take out bins",
            due_at=None,
            recurrence_rule={"frequency": "weekly", "time": "09:00", "weekday": 2},
        )
        ChoreAssignment.objects.create(
            chore=recurring_chore, membership=self.owner_membership
        )

        result = dispatch_tool(
            "chores", {}, user=self.owner, household_id=self.household.id
        )
        chores = {chore["id"]: chore for chore in result["chores"]}

        self.assertEqual(chores[due_chore.id]["due_at"], due_at.isoformat())
        self.assertIsNone(chores[recurring_chore.id]["due_at"])
        self.assertIsNone(chores[due_chore.id]["recurrence_rule"])
        self.assertEqual(
            chores[recurring_chore.id]["recurrence_rule"],
            {"frequency": "weekly", "time": "09:00", "weekday": 2},
        )
        self.assertEqual(
            chores[due_chore.id]["assigned_membership_ids"],
            [self.member_membership.id],
        )
        self.assertEqual(
            chores[recurring_chore.id]["assigned_membership_ids"],
            [self.owner_membership.id],
        )
        self.assertEqual(chores[due_chore.id]["title"], "Existing chore")
        self.assertTrue(chores[due_chore.id]["is_active"])
        self.assertEqual(len(chores), 2)
        self.assertEqual(len(result["occurrences"]), 0)

    def test_update_cannot_add_recurrence_without_clearing_single_due_at(self):
        due_at = datetime(2026, 11, 5, 18, 30, tzinfo=dt_timezone.utc)
        chore = self._create_chore(due_at=due_at)
        original = (chore.title, chore.due_at, chore.recurrence_rule)

        with self.assertRaises(ValidationError):
            self._call(
                "update_chore",
                {
                    "chore_id": chore.id,
                    "recurrence_rule": {
                        "frequency": "weekly",
                        "time": "09:00",
                        "weekday": 2,
                    },
                },
                52,
            )

        chore.refresh_from_db()
        self.assertEqual((chore.title, chore.due_at, chore.recurrence_rule), original)
        self.assertFalse(chore.due_at is not None and chore.recurrence_rule is not None)
        self.assertEqual(AuditEvent.objects.filter(action="chore.updated").count(), 0)

    def test_update_uses_domain_service_and_rejects_bad_assignment_atomically(self):
        chore = self._create_chore()
        ChoreAssignment.objects.create(chore=chore, membership=self.member_membership)
        self._call(
            "update_chore",
            {
                "chore_id": chore.id,
                "title": "Updated",
                "description": "Details",
                "category": "Laundry",
                "is_active": False,
                "assignment_ids": [self.owner_membership.id],
            },
            2,
        )
        chore.refresh_from_db()
        self.assertEqual(
            (chore.title, chore.description, chore.category, chore.is_active),
            ("Updated", "Details", "Laundry", False),
        )
        self.assertEqual(
            list(chore.assignments.values_list("membership_id", flat=True)),
            [self.owner_membership.id],
        )
        self.assertEqual(AuditEvent.objects.filter(action="chore.updated").count(), 1)

        with self.assertRaises(ValidationError):
            self._call(
                "update_chore",
                {
                    "chore_id": chore.id,
                    "title": "Must not persist",
                    "assignment_ids": [self.foreign_membership.id],
                },
                3,
            )
        chore.refresh_from_db()
        self.assertEqual(chore.title, "Updated")
        self.assertEqual(
            list(chore.assignments.values_list("membership_id", flat=True)),
            [self.owner_membership.id],
        )
        self.assertEqual(AuditEvent.objects.filter(action="chore.updated").count(), 1)

    def test_occurrence_status_completion_and_transition_auditing(self):
        chore = self._create_chore()
        occurrence = ChoreOccurrence.objects.create(
            chore=chore, due_at=datetime(2026, 11, 5, 18, tzinfo=dt_timezone.utc)
        )
        self._call(
            "set_chore_occurrence_status",
            {"occurrence_id": occurrence.id, "status": "completed"},
            4,
        )
        self.assertEqual(
            ChoreCompletion.objects.filter(occurrence=occurrence).count(), 1
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="chore_occurrence.completed").count(), 1
        )
        self._call(
            "set_chore_occurrence_status",
            {"occurrence_id": occurrence.id, "status": "completed"},
            5,
        )
        self.assertEqual(
            ChoreCompletion.objects.filter(occurrence=occurrence).count(), 1
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="chore_occurrence.completed").count(), 1
        )

        for index, status in enumerate(("skipped", "cancelled"), start=6):
            other = ChoreOccurrence.objects.create(
                chore=chore,
                due_at=datetime(2026, 11, index, 18, tzinfo=dt_timezone.utc),
            )
            self._call(
                "set_chore_occurrence_status",
                {"occurrence_id": other.id, "status": status},
                index,
            )
            self.assertFalse(ChoreCompletion.objects.filter(occurrence=other).exists())
            self.assertEqual(
                AuditEvent.objects.filter(action=f"chore_occurrence.{status}").count(),
                1,
            )

    def test_invalid_create_inputs_and_unexpected_arguments_have_no_side_effects(self):
        base = self._create_arguments()
        invalid = (
            {
                **base,
                "recurrence_rule": {"frequency": "yearly", "time": "09:00"},
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {"frequency": "daily", "time": "25:00"},
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {"frequency": "weekly", "weekday": 7},
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {"frequency": "monthly", "day": 32},
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {"frequency": "daily", "unexpected": True},
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {
                    "frequency": "weekly",
                    "time": "09:00",
                    "day": 12,
                },
                "due_at": None,
            },
            {
                **base,
                "recurrence_rule": {
                    "frequency": "daily",
                    "time": "09:00",
                    "weekday": 2,
                },
                "due_at": None,
            },
            {**base, "due_at": "2026-11-05T18:30:00"},
            {**base, "recurrence_rule": {"frequency": "daily"}},
            {**base, "assignment_ids": [True]},
            {**base, "is_active": 1},
            {**base, "surprise": True},
            {**base, "assignment_ids": [self.inactive_membership.id]},
        )
        for index, arguments in enumerate(invalid, start=10):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises((ValidationError, ValueError)),
            ):
                self._call("create_chore", arguments, index)
        self.assertEqual(Chore.objects.count(), 0)
        self.assertEqual(ChoreAssignment.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_viewer_foreign_household_and_foreign_ids_are_denied_without_side_effects(
        self,
    ):
        foreign_chore = Chore.objects.create(
            household=self.foreign_household,
            created_by=self.foreign_user,
            title="Foreign",
        )
        foreign_occurrence = ChoreOccurrence.objects.create(
            chore=foreign_chore,
            due_at=datetime(2026, 11, 5, 18, tzinfo=dt_timezone.utc),
        )
        ops = (
            ("create_chore", self._create_arguments()),
            ("update_chore", {"chore_id": 999999, "title": "No"}),
            (
                "set_chore_occurrence_status",
                {"occurrence_id": foreign_occurrence.id, "status": "completed"},
            ),
        )
        for index, (tool, arguments) in enumerate(ops):
            with self.subTest(tool=tool), self.assertRaises(PermissionDenied):
                self._call(tool, arguments, 30 + index, user=self.viewer)
            with self.subTest(tool=tool), self.assertRaises(NotFound):
                self._call(
                    tool, arguments, 40 + index, household_id=self.foreign_household.id
                )
        with self.assertRaises((NotFound, ValidationError)):
            self._call(
                "update_chore", {"chore_id": foreign_chore.id, "title": "No"}, 50
            )
        with self.assertRaises((NotFound, ValidationError)):
            self._call(
                "set_chore_occurrence_status",
                {"occurrence_id": foreign_occurrence.id, "status": "completed"},
                51,
            )
        self.assertEqual(Chore.objects.count(), 1)
        self.assertEqual(ChoreOccurrence.objects.count(), 1)
        self.assertEqual(ChoreCompletion.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
