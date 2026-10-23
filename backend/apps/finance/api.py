from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.finance.models import Budget, Expense, ExpenseCategory, ExpenseSplit
from apps.finance.selectors import monthly_summary, serialize_expense, settlements
from apps.finance.services import create_expense, record_payment, set_budget
from apps.households.models import Membership
from apps.households.permissions import require_membership


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def categories(request):
    household_id = (
        request.query_params.get("household_id")
        if request.method == "GET"
        else request.data.get("household_id")
    )
    membership = require_membership(
        request.user, household_id, write=request.method == "POST"
    )
    if request.method == "GET":
        return Response(
            list(
                ExpenseCategory.objects.filter(
                    household=membership.household, is_active=True
                ).values("id", "name", "kind")
            )
        )
    name = str(request.data.get("name", "")).strip()
    if not name or len(name) > 80:
        return Response({"name": ["Informe um nome de até 80 caracteres."]}, status=400)
    with transaction.atomic():
        category, created = ExpenseCategory.objects.get_or_create(
            household=membership.household,
            name=name,
            defaults={"kind": request.data.get("kind", "general")},
        )
        if not created:
            return Response(
                {"name": ["Já existe uma categoria com este nome."]}, status=400
            )
        from apps.audit.models import AuditEvent

        AuditEvent.objects.create(
            household=membership.household,
            actor=request.user,
            action="category.created",
            entity_type="expense_category",
            entity_id=str(category.id),
            metadata={"kind": category.kind},
        )
    return Response(
        {"id": category.id, "name": category.name, "kind": category.kind}, status=201
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def expenses(request, household_id):
    membership = require_membership(
        request.user, household_id, write=request.method == "POST"
    )
    if request.method == "GET":
        qs = (
            Expense.objects.filter(household=membership.household)
            .select_related("category")
            .prefetch_related(
                "payments", "splits__membership__user", "payments__payer__user"
            )
        )
        return Response(
            [serialize_expense(item) for item in qs.order_by("-incurred_on", "-id")]
        )
    with transaction.atomic():
        expense = create_expense(
            household=membership.household, actor=request.user, payload=request.data
        )
    return Response(serialize_expense(expense), status=201)


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def expense_detail(request, expense_id):
    expense = (
        Expense.objects.filter(pk=expense_id)
        .select_related("household", "category")
        .prefetch_related("payments__payer__user", "splits__membership__user")
        .first()
    )
    if expense is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Despesa não encontrada")
    require_membership(
        request.user, expense.household_id, write=request.method == "PUT"
    )
    if request.method == "GET":
        return Response(serialize_expense(expense))
    with transaction.atomic():
        Expense.objects.select_for_update().get(pk=expense.pk)
        rows = request.data.get("splits", [])
        from apps.finance.services import allocate_splits

        allocations = allocate_splits(
            expense.amount_minor, rows, request.data.get("split_method", "equal")
        )
        active = {
            item.id: item
            for item in Membership.objects.filter(
                id__in=[row[0] for row in allocations],
                household=expense.household,
                status="active",
            )
        }
        if len(active) != len(allocations):
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"splits": "Participantes inválidos para esta residência."}
            )
        ExpenseSplit.objects.filter(expense=expense, is_current=True).update(
            is_current=False
        )
        ExpenseSplit.objects.bulk_create(
            [
                ExpenseSplit(
                    expense=expense,
                    membership=active[mid],
                    amount_minor=amount,
                    share_percent=percent,
                )
                for mid, amount, percent in allocations
            ]
        )
        from apps.audit.models import AuditEvent

        AuditEvent.objects.create(
            household=expense.household,
            actor=request.user,
            action="expense.splits_updated",
            entity_type="expense",
            entity_id=str(expense.id),
            metadata={"splits": len(allocations)},
        )
    return Response(serialize_expense(expense))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def payments(request, expense_id):
    expense = Expense.objects.filter(pk=expense_id).select_related("household").first()
    if expense is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Despesa não encontrada")
    require_membership(request.user, expense.household_id, write=True)
    try:
        payer = Membership.objects.get(
            pk=request.data.get("payer_id"),
            household=expense.household,
            status="active",
        )
    except (Membership.DoesNotExist, ValueError, TypeError):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"payer_id": "Pagador inválido."})
    payment = record_payment(
        expense=expense,
        payer=payer,
        actor=request.user,
        amount_minor=request.data.get("amount_minor"),
        notes=str(request.data.get("notes", ""))[:240],
    )
    return Response(
        {
            "id": payment.id,
            "expense_id": expense.id,
            "payer_id": payer.id,
            "amount_minor": payment.amount_minor,
            "status": expense.status,
        },
        status=201,
    )


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def budgets(request, household_id, period):
    membership = require_membership(
        request.user, household_id, write=request.method == "PUT"
    )
    if request.method == "PUT":
        budget = set_budget(
            household=membership.household,
            actor=request.user,
            period=period,
            amount_minor=request.data.get("amount_minor"),
            category_id=request.data.get("category_id"),
        )
        return Response(
            {
                "id": budget.id,
                "period": period,
                "category_id": budget.category_id,
                "amount_minor": budget.amount_minor,
            }
        )
    try:
        year, month = map(int, period.split("-"))
        date(year, month, 1)
    except ValueError:
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"period": "Use o formato AAAA-MM."})
    start = date(year, month, 1)
    return Response(
        [
            {"id": b.id, "category_id": b.category_id, "amount_minor": b.amount_minor}
            for b in Budget.objects.filter(
                household=membership.household, period_start=start
            )
        ]
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def financial_summary(request, household_id):
    membership = require_membership(request.user, household_id)
    period = request.query_params.get("period", timezone.localdate().strftime("%Y-%m"))
    try:
        year, month = map(int, period.split("-"))
        if len(period) != 7 or period[4] != "-":
            raise ValueError
        date(year, month, 1)
    except (ValueError, TypeError):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"period": "Use o formato AAAA-MM."})
    return Response(monthly_summary(membership.household, period))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def financial_settlements(request, household_id):
    membership = require_membership(request.user, household_id)
    return Response(settlements(membership.household))
