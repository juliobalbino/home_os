from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.finance.models import Budget, Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.households.models import Membership

MAX_AMOUNT_MINOR = 9223372036854775807


def _validate_money(value, field="amount_minor"):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > MAX_AMOUNT_MINOR
    ):
        detail = "O valor deve ser um inteiro positivo em centavos."
        if field == "amount_minor":
            detail += f" Valor máximo suportado: {MAX_AMOUNT_MINOR}."
        raise ValidationError({field: detail})


def allocate_splits(total, entries, method):
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total <= 0
        or total > MAX_AMOUNT_MINOR
    ):
        raise ValidationError(
            {"amount_minor": "O valor deve ser um inteiro positivo em centavos."}
        )
    if not isinstance(entries, list) or not entries:
        raise ValidationError({"splits": "Informe ao menos uma pessoa."})
    try:
        if any(not isinstance(item, dict) for item in entries):
            raise ValueError
        required_keys = (
            {"membership_id"}
            if method == "equal"
            else {
                "membership_id",
                "percent" if method == "percentage" else "amount_minor",
            }
        )
        if method not in ("equal", "fixed", "percentage") or any(
            set(item) != required_keys for item in entries
        ):
            raise ValueError
        raw_ids = [item["membership_id"] for item in entries]
        if any(
            isinstance(value, bool)
            or not (
                isinstance(value, int)
                or isinstance(value, str)
                and re.fullmatch(r"[0-9]+", value)
            )
            for value in raw_ids
        ):
            raise ValueError
        ids = [int(value) for value in raw_ids]
    except (KeyError, TypeError, ValueError):
        raise ValidationError(
            {"splits": "Cada divisão deve identificar um membro válido."}
        )
    if any(member_id <= 0 for member_id in ids):
        raise ValidationError(
            {"splits": "Cada divisão deve identificar um membro válido."}
        )
    if len(set(ids)) != len(ids):
        raise ValidationError({"splits": "Não repita participantes."})
    ordered = sorted(ids)
    if method == "equal":
        base, remainder = divmod(total, len(ordered))
        return [
            (member_id, base + (index < remainder), None)
            for index, member_id in enumerate(ordered)
        ]
    field = "percent" if method == "percentage" else "amount_minor"
    try:
        values = {int(item["membership_id"]): item[field] for item in entries}
    except (KeyError, TypeError, ValueError):
        raise ValidationError({"splits": "Informe um valor para cada participante."})
    if method == "fixed":
        if (
            any(
                not isinstance(v, int)
                or isinstance(v, bool)
                or v < 0
                or v > MAX_AMOUNT_MINOR
                for v in values.values()
            )
            or sum(values.values()) != total
        ):
            raise ValidationError(
                {"splits": "Os valores fixos devem somar exatamente a despesa."}
            )
        return [(mid, values[mid], None) for mid in ordered]
    try:
        percentages = {}
        for item in entries:
            value = item[field]
            if isinstance(value, (bool, float)):
                raise ValueError
            text = str(value).replace(",", ".")
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,4})?", text):
                raise ValueError
            percentages[int(item["membership_id"])] = Decimal(text)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise ValidationError({"splits": "Informe percentuais válidos."})
    if (
        method != "percentage"
        or any(v < 0 for v in percentages.values())
        or sum(percentages.values()) != Decimal("100")
    ):
        raise ValidationError({"splits": "Os percentuais devem somar exatamente 100."})
    units = {mid: int(percentages[mid] * 10000) for mid in ordered}
    scale = 1_000_000
    cents = {mid: total * units[mid] // scale for mid in ordered}
    remainder = total - sum(cents.values())
    ranked = sorted(ordered, key=lambda mid: (-(total * units[mid] % scale), mid))
    for mid in ranked[:remainder]:
        cents[mid] += 1
    return [(mid, cents[mid], percentages[mid]) for mid in ordered]


@transaction.atomic
def create_expense(*, household, actor, payload):
    total = payload.get("amount_minor")
    allocations = allocate_splits(
        total, payload.get("splits", []), payload.get("split_method", "equal")
    )
    try:
        category = ExpenseCategory.objects.get(
            pk=payload["category_id"], household=household, is_active=True
        )
        members = {
            m.id: m
            for m in Membership.objects.filter(
                id__in=[row[0] for row in allocations],
                household=household,
                status="active",
            )
        }
        if len(members) != len(allocations):
            raise ValidationError(
                {
                    "splits": "Todos os participantes devem ser membros ativos desta residência."
                }
            )
        incurred = date.fromisoformat(payload["incurred_on"])
        description = str(payload["description"]).strip()
        if not description or len(description) > 200:
            raise ValueError
    except (KeyError, ValueError, TypeError, ExpenseCategory.DoesNotExist):
        raise ValidationError({"detail": "Categoria, descrição ou data inválida."})
    expense = Expense.objects.create(
        household=household,
        created_by=actor,
        category=category,
        description=description,
        amount_minor=total,
        incurred_on=incurred,
        notes=payload.get("notes", ""),
    )
    ExpenseSplit.objects.bulk_create(
        [
            ExpenseSplit(
                expense=expense,
                membership=members[mid],
                amount_minor=amount,
                share_percent=percent,
            )
            for mid, amount, percent in allocations
        ]
    )
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        household=household,
        actor=actor,
        action="expense.created",
        entity_type="expense",
        entity_id=str(expense.id),
        metadata={"amount_minor": total},
    )
    return expense


@transaction.atomic
def update_expense(*, expense, actor, payload):
    expense = (
        Expense.objects.select_for_update()
        .select_related("household")
        .get(pk=expense.pk)
    )
    if "amount_minor" in payload:
        _validate_money(payload["amount_minor"])
        paid = expense.payments.aggregate(total=Sum("amount_minor"))["total"] or 0
        if payload["amount_minor"] < paid:
            raise ValidationError(
                {
                    "amount_minor": "O valor não pode ser inferior aos pagamentos registrados."
                }
            )
        expense.amount_minor = payload["amount_minor"]
    if "description" in payload:
        description = (
            payload["description"].strip()
            if isinstance(payload["description"], str)
            else ""
        )
        if not description or len(description) > 200:
            raise ValidationError({"description": "Descrição inválida."})
        expense.description = description
    if "incurred_on" in payload:
        try:
            expense.incurred_on = date.fromisoformat(payload["incurred_on"])
        except (ValueError, TypeError):
            raise ValidationError({"incurred_on": "Data inválida."})
    if "category_id" in payload:
        try:
            expense.category = ExpenseCategory.objects.get(
                pk=payload["category_id"], household=expense.household, is_active=True
            )
        except (ExpenseCategory.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"category_id": "Categoria inválida."})
    if "notes" in payload:
        if not isinstance(payload["notes"], str):
            raise ValidationError({"notes": "Notas inválidas."})
        expense.notes = payload["notes"]
    expense.save()
    if "splits" in payload:
        allocations = allocate_splits(
            expense.amount_minor,
            payload["splits"],
            payload.get("split_method", "equal"),
        )
        members = {
            m.id: m
            for m in Membership.objects.filter(
                id__in=[row[0] for row in allocations],
                household=expense.household,
                status="active",
            )
        }
        if len(members) != len(allocations):
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
                    membership=members[mid],
                    amount_minor=amount,
                    share_percent=percent,
                )
                for mid, amount, percent in allocations
            ]
        )
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        household=expense.household,
        actor=actor,
        action="expense.updated",
        entity_type="expense",
        entity_id=str(expense.id),
        metadata={"splits": len(payload["splits"]) if "splits" in payload else None},
    )
    return expense


@transaction.atomic
def create_expense_category(*, household, actor, name, kind="general"):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValidationError({"name": "Informe um nome de até 80 caracteres."})
    name = name.strip()
    if not isinstance(kind, str) or kind not in {
        "general",
        "food",
        "transport",
        "housing",
        "health",
        "entertainment",
        "utilities",
        "other",
    }:
        raise ValidationError({"kind": "Tipo de categoria inválido."})
    if ExpenseCategory.objects.filter(household=household, name=name).exists():
        raise ValidationError({"name": "Já existe uma categoria com este nome."})
    category = ExpenseCategory.objects.create(household=household, name=name, kind=kind)
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        household=household,
        actor=actor,
        action="category.created",
        entity_type="expense_category",
        entity_id=str(category.id),
        metadata={"kind": category.kind},
    )
    return category


@transaction.atomic
def record_payment(*, expense, payer, actor, amount_minor, notes=""):
    _validate_money(amount_minor)
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if payer.household_id != expense.household_id or payer.status != "active":
        raise ValidationError({"payer_id": "Pagador inválido para esta residência."})
    paid = expense.payments.aggregate(total=Sum("amount_minor"))["total"] or 0
    if paid + amount_minor > expense.amount_minor:
        raise ValidationError(
            {
                "amount_minor": f"Pagamentos acumulados não podem superar a despesa. Valor máximo suportado: {MAX_AMOUNT_MINOR}."
            }
        )
    payment = Payment.objects.create(
        household=expense.household,
        expense=expense,
        payer=payer,
        amount_minor=amount_minor,
        notes=notes,
    )
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        household=expense.household,
        actor=actor,
        action="payment.created",
        entity_type="payment",
        entity_id=str(payment.id),
        metadata={
            "expense_id": expense.id,
            "amount_minor": amount_minor,
            "payer_id": payer.id,
        },
    )
    return payment


@transaction.atomic
def set_budget(*, household, actor, period, amount_minor, category_id=None):
    _validate_money(amount_minor)
    try:
        year, month = map(int, period.split("-"))
        start = date(year, month, 1)
        if monthrange(year, month)[1] < 28:
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError({"period": "Use o formato AAAA-MM."})
    category = None
    if category_id is not None:
        try:
            category = ExpenseCategory.objects.get(
                pk=category_id, household=household, is_active=True
            )
        except ExpenseCategory.DoesNotExist:
            raise ValidationError({"category_id": "Categoria inválida."})
    budget, _ = Budget.objects.update_or_create(
        household=household,
        category=category,
        period_start=start,
        defaults={"amount_minor": amount_minor},
    )
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        household=household,
        actor=actor,
        action="budget.set",
        entity_type="budget",
        entity_id=str(budget.id),
        metadata={
            "period": period,
            "amount_minor": amount_minor,
            "category_id": category_id,
        },
    )
    return budget
