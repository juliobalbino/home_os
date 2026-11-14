"""Exact, reviewable removal of household demonstration records."""

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.assistant.models import AssistantActionProposal
from apps.households.permissions import require_membership


class CleanupBlocked(ValidationError):
    def __init__(self, message):
        self.safe_message = message
        super().__init__(message)


KEYS = (
    "shopping_list_ids",
    "product_ids",
    "chore_ids",
    "category_ids",
    "expense_ids",
)


def validate_selection(arguments):
    if not isinstance(arguments, dict) or set(arguments) != set(KEYS):
        raise CleanupBlocked("Seleção de registros incompleta.")
    selection = {}
    for key in KEYS:
        values = arguments[key]
        if not isinstance(values, list) or len(values) > 100:
            raise CleanupBlocked("A seleção contém identificadores inválidos.")
        normalized = []
        for value in values:
            if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,17}", value):
                value = int(value)
            if type(value) is not int or not 0 < value <= 2**63 - 1:
                raise CleanupBlocked("A seleção contém identificadores inválidos.")
            normalized.append(value)
        if len(normalized) != len(set(normalized)):
            raise CleanupBlocked("A seleção contém identificadores repetidos.")
        selection[key] = sorted(normalized)
    if not any(selection.values()):
        raise CleanupBlocked("Selecione ao menos um registro para remover.")
    return selection


def _ids(queryset):
    return list(queryset.order_by("pk").values_list("pk", flat=True))


def snapshot(household, selection):
    from apps.chores.models import (
        Chore,
        ChoreAssignment,
        ChoreCompletion,
        ChoreOccurrence,
    )
    from apps.finance.models import (
        Budget,
        Expense,
        ExpenseCategory,
        ExpenseSplit,
        Payment,
    )
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

    models = (
        ("shopping_list_ids", ShoppingList, "Lista", "name"),
        ("product_ids", Product, "Produto", "name"),
        ("chore_ids", Chore, "Tarefa", "title"),
        ("category_ids", ExpenseCategory, "Categoria", "name"),
        ("expense_ids", Expense, "Despesa", "description"),
    )
    records = []
    for key, model, label, name_field in models:
        query = model.objects.filter(household=household, pk__in=selection[key])
        if key == "expense_ids":
            query = query.select_related("category")
        rows = list(query.order_by("pk"))
        if [row.pk for row in rows] != selection[key]:
            raise CleanupBlocked(
                "Um registro selecionado não pertence a esta residência ou não existe mais."
            )
        for row in rows:
            record = {"type": label, "id": row.pk, "name": getattr(row, name_field)}
            if key == "expense_ids":
                record["detail"] = (
                    f"{row.currency} {row.amount_minor // 100},{row.amount_minor % 100:02d}"
                    f" · {row.incurred_on:%d/%m/%Y} · {row.category.name}"
                )
            records.append(record)

    list_items = _ids(
        ShoppingListItem.objects.filter(
            shopping_list_id__in=selection["shopping_list_ids"]
        )
    )
    inventory_items = _ids(
        InventoryItem.objects.filter(
            household=household, product_id__in=selection["product_ids"]
        )
    )
    inventory_events = _ids(InventoryEvent.objects.filter(item_id__in=inventory_items))
    purchases = _ids(
        Purchase.objects.filter(
            household=household, expense_id__in=selection["expense_ids"]
        )
    )
    purchase_items = _ids(PurchaseItem.objects.filter(purchase_id__in=purchases))
    budgets = _ids(
        Budget.objects.filter(
            household=household, category_id__in=selection["category_ids"]
        )
    )
    payments = _ids(
        Payment.objects.filter(
            household=household, expense_id__in=selection["expense_ids"]
        )
    )
    splits = _ids(ExpenseSplit.objects.filter(expense_id__in=selection["expense_ids"]))
    occurrences = _ids(
        ChoreOccurrence.objects.filter(chore_id__in=selection["chore_ids"])
    )
    assignments = _ids(
        ChoreAssignment.objects.filter(chore_id__in=selection["chore_ids"])
    )
    completions = _ids(ChoreCompletion.objects.filter(occurrence_id__in=occurrences))
    aliases = _ids(ProductAlias.objects.filter(product_id__in=selection["product_ids"]))
    prices = _ids(
        PriceObservation.objects.filter(product_id__in=selection["product_ids"])
    )

    if (
        ShoppingListItem.objects.filter(product_id__in=selection["product_ids"])
        .exclude(pk__in=list_items)
        .exists()
    ):
        raise CleanupBlocked(
            "Um produto selecionado também está em uma lista fora da seleção."
        )
    if (
        Purchase.objects.filter(
            household=household, shopping_list_id__in=selection["shopping_list_ids"]
        )
        .exclude(pk__in=purchases)
        .exists()
    ):
        raise CleanupBlocked(
            "Uma lista selecionada está vinculada a uma compra fora da seleção."
        )
    if (
        PurchaseItem.objects.filter(shopping_list_item_id__in=list_items)
        .exclude(pk__in=purchase_items)
        .exists()
    ):
        raise CleanupBlocked(
            "Um item da lista selecionada está vinculado a uma compra fora da seleção."
        )
    if (
        PurchaseItem.objects.filter(product_id__in=selection["product_ids"])
        .exclude(pk__in=purchase_items)
        .exists()
    ):
        raise CleanupBlocked(
            "Um produto selecionado está em uma compra fora da seleção."
        )
    if (
        Expense.objects.filter(
            household=household, category_id__in=selection["category_ids"]
        )
        .exclude(pk__in=selection["expense_ids"])
        .exists()
    ):
        raise CleanupBlocked(
            "Uma categoria selecionada possui despesas fora da seleção."
        )
    if (
        Purchase.objects.filter(pk__in=purchases)
        .exclude(shopping_list_id__isnull=True)
        .exclude(shopping_list_id__in=selection["shopping_list_ids"])
        .exists()
    ):
        raise CleanupBlocked(
            "Uma despesa selecionada possui compra vinculada a uma lista fora da seleção."
        )
    if (
        PurchaseItem.objects.filter(pk__in=purchase_items)
        .exclude(product_id__in=selection["product_ids"])
        .exists()
    ):
        raise CleanupBlocked("Uma compra selecionada possui produtos fora da seleção.")
    if (
        PurchaseItem.objects.filter(
            pk__in=purchase_items, shopping_list_item_id__isnull=False
        )
        .exclude(shopping_list_item_id__in=list_items)
        .exists()
    ):
        raise CleanupBlocked(
            "Uma compra selecionada possui itens em uma lista fora da seleção."
        )
    if (
        InventoryEvent.objects.filter(source_purchase_item_id__in=purchase_items)
        .exclude(pk__in=inventory_events)
        .exists()
    ):
        raise CleanupBlocked(
            "Uma compra selecionada atualizou o estoque de um produto fora da seleção."
        )
    if (
        InventoryEvent.objects.filter(
            pk__in=inventory_events, source_purchase_item_id__isnull=False
        )
        .exclude(source_purchase_item_id__in=purchase_items)
        .exists()
    ):
        raise CleanupBlocked("O estoque selecionado contém uma compra fora da seleção.")

    dependencies = {
        "list_items": list_items,
        "inventory_items": inventory_items,
        "inventory_events": inventory_events,
        "purchases": purchases,
        "purchase_items": purchase_items,
        "budgets": budgets,
        "payments": payments,
        "splits": splits,
        "occurrences": occurrences,
        "assignments": assignments,
        "completions": completions,
        "aliases": aliases,
        "prices": prices,
    }
    return {"records": records, "dependencies": dependencies}


@transaction.atomic
def create_record_cleanup(*, user, household_id, selection):
    from apps.assistant.proposals import proposal_card

    household = require_membership(user, household_id, write=True).household
    selection = validate_selection(selection)
    current = snapshot(household, selection)
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="record_cleanup",
        payload=selection,
        snapshot=current,
        preview={
            "title": "Remover registros selecionados?",
            "summary": f"Remover {len(current['records'])} registros e seus dados vinculados.",
            "details": {
                "records": current["records"],
                "dependent_count": sum(
                    len(values) for values in current["dependencies"].values()
                ),
            },
        },
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return proposal_card(proposal)


def confirm_record_cleanup(*, proposal, user, household):
    from apps.audit.models import AuditEvent
    from apps.chores.models import Chore
    from apps.finance.models import (
        Budget,
        Expense,
        ExpenseCategory,
        ExpenseSplit,
        Payment,
    )
    from apps.inventory.models import InventoryEvent, InventoryItem
    from apps.shopping.models import (
        Product,
        Purchase,
        PurchaseItem,
        ShoppingList,
        ShoppingListItem,
    )

    require_membership(user, household.pk, write=True)
    try:
        current = snapshot(household, proposal.payload)
    except CleanupBlocked:
        current = None
    if current != proposal.snapshot:
        proposal.status = "stale"
        proposal.completed_at = timezone.now()
        proposal.save(update_fields=["status", "completed_at"])
        return {"status": 409, "data": {"status": "stale"}}

    selected = proposal.payload
    dependent = current["dependencies"]
    InventoryEvent.objects.filter(pk__in=dependent["inventory_events"]).delete()
    PurchaseItem.objects.filter(pk__in=dependent["purchase_items"]).delete()
    Purchase.objects.filter(pk__in=dependent["purchases"]).delete()
    Payment.objects.filter(pk__in=dependent["payments"]).delete()
    ExpenseSplit.objects.filter(pk__in=dependent["splits"]).delete()
    Expense.objects.filter(pk__in=selected["expense_ids"], household=household).delete()
    Budget.objects.filter(pk__in=dependent["budgets"]).delete()
    ExpenseCategory.objects.filter(
        pk__in=selected["category_ids"], household=household
    ).delete()
    ShoppingListItem.objects.filter(pk__in=dependent["list_items"]).delete()
    ShoppingList.objects.filter(
        pk__in=selected["shopping_list_ids"], household=household
    ).delete()
    InventoryItem.objects.filter(pk__in=dependent["inventory_items"]).delete()
    Product.objects.filter(pk__in=selected["product_ids"], household=household).delete()
    Chore.objects.filter(pk__in=selected["chore_ids"], household=household).delete()

    result = {"status": "confirmed", "deleted_count": len(current["records"])}
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="household.records_deleted",
        entity_type="household",
        entity_id=str(household.pk),
        metadata={"selection": selected, "deleted_count": result["deleted_count"]},
    )
    proposal.status = "confirmed"
    proposal.completed_at = timezone.now()
    proposal.result = result
    proposal.save(update_fields=["status", "completed_at", "result"])
    return {"status": 200, "data": result}
