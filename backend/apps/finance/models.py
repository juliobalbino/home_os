from django.conf import settings
from django.db import models

from apps.households.models import Household, Membership


class ExpenseCategory(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="expense_categories"
    )
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=30, default="general")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "name"), name="unique_expense_category_name"
            )
        ]
        ordering = ("name", "id")


class Expense(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="expenses"
    )
    description = models.CharField(max_length=200)
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="expenses"
    )
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    incurred_on = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def paid_total(self):
        return sum(self.payments.values_list("amount_minor", flat=True))

    @property
    def status(self):
        if self.paid_total == 0:
            return self.Status.UNPAID
        return (
            self.Status.PAID
            if self.paid_total == self.amount_minor
            else self.Status.PARTIAL
        )


class ExpenseSplit(models.Model):
    expense = models.ForeignKey(
        Expense, on_delete=models.PROTECT, related_name="splits"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="expense_splits"
    )
    amount_minor = models.PositiveBigIntegerField()
    share_percent = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True
    )
    is_current = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("expense", "membership"),
                condition=models.Q(is_current=True),
                name="unique_current_expense_split_member",
            )
        ]


class Payment(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="payments"
    )
    expense = models.ForeignKey(
        Expense, on_delete=models.PROTECT, related_name="payments"
    )
    payer = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="payments"
    )
    amount_minor = models.PositiveBigIntegerField()
    paid_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=240, blank=True)


class Budget(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="budgets"
    )
    category = models.ForeignKey(
        ExpenseCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="budgets",
    )
    period_start = models.DateField()
    amount_minor = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "period_start"),
                condition=models.Q(category__isnull=True),
                name="unique_household_general_budget_period",
            ),
            models.UniqueConstraint(
                fields=("household", "category", "period_start"),
                condition=models.Q(category__isnull=False),
                name="unique_household_category_budget_period",
            ),
        ]
