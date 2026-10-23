from django.test import TestCase
from decimal import Decimal
from datetime import date
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.accounts.models import User
from apps.finance.models import Budget, Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.finance.services import allocate_splits
from apps.audit.models import AuditEvent
from apps.households.models import Household, Membership


class SplitAllocationTests(TestCase):
    def test_three_hundred_reais_splits_into_one_fifty_each(self):
        self.assertEqual(
            allocate_splits(
                30000,
                [{"membership_id": 1}, {"membership_id": 2}],
                "equal",
            ),
            [(1, 15000, None), (2, 15000, None)],
        )

    def test_equal_divides_odd_cent_in_membership_order(self):
        self.assertEqual(
            allocate_splits(
                100,
                [{"membership_id": 7}, {"membership_id": 3}, {"membership_id": 5}],
                "equal",
            ),
            [(3, 34, None), (5, 33, None), (7, 33, None)],
        )

    def test_percentage_rounds_by_largest_remainder_and_closes(self):
        result = allocate_splits(
            101,
            [{"membership_id": 2, "percent": 50}, {"membership_id": 1, "percent": 50}],
            "percentage",
        )
        self.assertEqual(result, [(1, 51, 50), (2, 50, 50)])

    def test_fractional_percentages_are_exact_and_close(self):
        result = allocate_splits(
            10000,
            [
                {"membership_id": 1, "percent": "33.3333"},
                {"membership_id": 2, "percent": "33.3333"},
                {"membership_id": 3, "percent": "33.3334"},
            ],
            "percentage",
        )
        self.assertEqual(
            result,
            [
                (1, 3333, Decimal("33.3333")),
                (2, 3333, Decimal("33.3333")),
                (3, 3334, Decimal("33.3334")),
            ],
        )

    def test_fixed_splits_must_close(self):
        with self.assertRaises(ValidationError):
            allocate_splits(100, [{"membership_id": 1, "amount_minor": 70}], "fixed")


class FinanceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="secret1", name="Owner"
        )
        self.household = Household.objects.create(name="Casa", created_by=self.user)
        self.member = Membership.objects.create(
            household=self.household, user=self.user, role="owner"
        )
        self.category = ExpenseCategory.objects.create(
            household=self.household, name="Moradia"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def expense_payload(self):
        return {
            "description": "Conta de luz",
            "category_id": self.category.id,
            "amount_minor": 1000,
            "incurred_on": "2026-10-02",
            "split_method": "equal",
            "splits": [{"membership_id": self.member.id}],
        }

    def test_expense_and_split_are_created_atomically(self):
        response = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ExpenseSplit.objects.get().amount_minor, 1000)
        self.assertTrue(AuditEvent.objects.filter(action="expense.created").exists())

    def test_invalid_expense_leaves_no_partial_records(self):
        payload = self.expense_payload()
        payload["amount_minor"] = 1.5
        response = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses", payload, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Expense.objects.count(), 0)

    def test_malformed_split_member_is_a_validation_error_without_records(self):
        payload = self.expense_payload()
        payload["splits"] = [{"membership_id": "not-an-id"}]
        response = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            payload,
            format="json",
            follow=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Expense.objects.count(), 0)

    def test_boolean_and_fractional_membership_ids_are_rejected_without_expense(self):
        for invalid_id in (True, 1.9):
            with self.subTest(invalid_id=invalid_id):
                payload = self.expense_payload()
                payload["splits"] = [{"membership_id": invalid_id}]
                response = self.client.post(
                    f"/api/v1/households/{self.household.id}/expenses",
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(Expense.objects.count(), 0)

    def test_financial_summary_rejects_invalid_periods(self):
        for period in ("not-a-period", "2026-13"):
            with self.subTest(period=period):
                response = self.client.get(
                    f"/api/v1/households/{self.household.id}/financial-summary?period={period}"
                )
                self.assertEqual(response.status_code, 400)

    @patch("apps.finance.api.timezone.localdate", return_value=date(2026, 10, 31))
    def test_financial_summary_defaults_to_local_month(self, _localdate):
        response = self.client.get(
            f"/api/v1/households/{self.household.id}/financial-summary"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["period"], "2026-10")

    def test_category_creation_is_audited(self):
        response = self.client.post(
            "/api/v1/finance/categories",
            {"household_id": str(self.household.id), "name": "Transporte"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(AuditEvent.objects.filter(action="category.created").exists())

    @patch(
        "apps.audit.models.AuditEvent.objects.create",
        side_effect=RuntimeError("audit unavailable"),
    )
    def test_category_is_not_created_when_audit_fails(self, _audit_create):
        with self.assertRaises(RuntimeError):
            self.client.post(
                "/api/v1/finance/categories",
                {"household_id": str(self.household.id), "name": "Transporte"},
                format="json",
            )
        self.assertFalse(
            ExpenseCategory.objects.filter(
                household=self.household, name="Transporte"
            ).exists()
        )

    def test_monthly_summary_prefers_general_budget_over_category_budgets(self):
        Budget.objects.create(
            household=self.household, period_start="2026-10-01", amount_minor=10000
        )
        Budget.objects.create(
            household=self.household,
            category=self.category,
            period_start="2026-10-01",
            amount_minor=4000,
        )
        summary = self.client.get(
            f"/api/v1/households/{self.household.id}/financial-summary?period=2026-10"
        )
        self.assertEqual(summary.data["budget_total"], 10000)

    def test_monthly_summary_sums_category_budgets_without_general_budget(self):
        second_category = ExpenseCategory.objects.create(
            household=self.household, name="Mercado"
        )
        Budget.objects.create(
            household=self.household,
            category=self.category,
            period_start="2026-10-01",
            amount_minor=4000,
        )
        Budget.objects.create(
            household=self.household,
            category=second_category,
            period_start="2026-10-01",
            amount_minor=6000,
        )
        summary = self.client.get(
            f"/api/v1/households/{self.household.id}/financial-summary?period=2026-10"
        )
        self.assertEqual(summary.data["budget_total"], 10000)

    def test_partial_payment_status_and_overpayment_rejection(self):
        created = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        expense_id = created.data["id"]
        url = f"/api/v1/expenses/{expense_id}/payments"
        response = self.client.post(
            url, {"payer_id": self.member.id, "amount_minor": 400}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "partial")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="payment.created").exists())
        balances = self.client.get(
            f"/api/v1/households/{self.household.id}/settlements"
        )
        self.assertEqual(balances.data[0]["balance_minor"], -600)
        completed = self.client.post(
            url, {"payer_id": self.member.id, "amount_minor": 600}, format="json"
        )
        self.assertEqual(completed.status_code, 201)
        self.assertEqual(completed.data["status"], "paid")
        rejected = self.client.post(
            url, {"payer_id": self.member.id, "amount_minor": 601}, format="json"
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(Payment.objects.count(), 2)

    def test_viewer_cannot_create_expense(self):
        self.member.role = "viewer"
        self.member.save(update_fields=["role"])
        response = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_budget_and_summary_use_integer_totals(self):
        budget_url = f"/api/v1/households/{self.household.id}/budgets/2026-10"
        saved = self.client.put(budget_url, {"amount_minor": 2500}, format="json")
        self.assertEqual(saved.status_code, 200, saved.data)
        self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        summary = self.client.get(
            f"/api/v1/households/{self.household.id}/financial-summary?period=2026-10"
        )
        self.assertEqual(summary.data["spent_total"], 1000)
        self.assertEqual(summary.data["budget_total"], 2500)
        repeated = self.client.put(budget_url, {"amount_minor": 2700}, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(
            Budget.objects.filter(
                household=self.household, category__isnull=True
            ).count(),
            1,
        )

    def test_expenses_are_isolated_from_non_members(self):
        self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        stranger = User.objects.create_user(
            email="stranger@example.com", password="secret1", name="Stranger"
        )
        client = APIClient()
        client.force_authenticate(stranger)
        response = client.get(f"/api/v1/households/{self.household.id}/expenses")
        self.assertEqual(response.status_code, 404)

    def test_split_replacement_preserves_history_and_settlement_uses_current_obligation(
        self,
    ):
        created = self.client.post(
            f"/api/v1/households/{self.household.id}/expenses",
            self.expense_payload(),
            format="json",
        )
        expense_id = created.data["id"]
        updated = self.client.put(
            f"/api/v1/expenses/{expense_id}/splits",
            {
                "split_method": "fixed",
                "splits": [{"membership_id": self.member.id, "amount_minor": 1000}],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(ExpenseSplit.objects.filter(expense_id=expense_id).count(), 2)
        self.assertEqual(
            ExpenseSplit.objects.filter(expense_id=expense_id, is_current=True).count(),
            1,
        )
        balances = self.client.get(
            f"/api/v1/households/{self.household.id}/settlements"
        )
        self.assertEqual(balances.data[0]["balance_minor"], -1000)
