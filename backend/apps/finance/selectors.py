from calendar import monthrange
from datetime import date

from django.db.models import Sum

from apps.finance.models import Budget, Expense, ExpenseSplit, Payment
from apps.households.models import Membership


def monthly_summary(household, period):
    year, month = map(int, period.split("-"))
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    expenses = Expense.objects.filter(
        household=household, incurred_on__range=(start, end)
    )
    budgets = Budget.objects.filter(household=household, period_start=start)
    general_budget = budgets.filter(category__isnull=True).first()
    return {
        "period": period,
        "spent_total": expenses.aggregate(total=Sum("amount_minor"))["total"] or 0,
        "budget_total": (
            general_budget.amount_minor
            if general_budget
            else budgets.aggregate(total=Sum("amount_minor"))["total"] or 0
        ),
        "expenses": [
            serialize_expense(item)
            for item in expenses.select_related("category").prefetch_related(
                "payments", "splits__membership__user"
            )
        ],
    }


def settlements(household):
    members = (
        Membership.objects.filter(household=household, status="active")
        .select_related("user")
        .order_by("id")
    )
    result = []
    for member in members:
        paid = (
            Payment.objects.filter(household=household, payer=member).aggregate(
                total=Sum("amount_minor")
            )["total"]
            or 0
        )
        owed = (
            ExpenseSplit.objects.filter(
                expense__household=household, membership=member, is_current=True
            ).aggregate(total=Sum("amount_minor"))["total"]
            or 0
        )
        result.append(
            {
                "membership_id": member.id,
                "name": member.user.name,
                "paid_minor": paid,
                "owed_minor": owed,
                "balance_minor": paid - owed,
            }
        )
    return result


def serialize_expense(expense):
    paid = sum(payment.amount_minor for payment in expense.payments.all())
    status = (
        "unpaid" if paid == 0 else "paid" if paid == expense.amount_minor else "partial"
    )
    return {
        "id": expense.id,
        "description": expense.description,
        "category_id": expense.category_id,
        "category": expense.category.name,
        "amount_minor": expense.amount_minor,
        "currency": expense.currency,
        "incurred_on": expense.incurred_on.isoformat(),
        "paid_total": paid,
        "status": status,
        "splits": [
            {
                "membership_id": split.membership_id,
                "member_name": split.membership.user.name,
                "amount_minor": split.amount_minor,
                "share_percent": str(split.share_percent)
                if split.share_percent is not None
                else None,
            }
            for split in expense.splits.filter(is_current=True)
        ],
        "payments": [
            {
                "id": payment.id,
                "payer_id": payment.payer_id,
                "payer_name": payment.payer.user.name,
                "amount_minor": payment.amount_minor,
                "paid_at": payment.paid_at.isoformat(),
                "notes": payment.notes,
            }
            for payment in expense.payments.all()
        ],
    }
