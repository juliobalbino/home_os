"""Scoped, bounded discovery of household records for assistant actions."""

from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q

from apps.households.permissions import require_membership

PAGE_SIZE = 20


def search_records(user, household_id, arguments):
    from apps.chores.models import Chore, ChoreOccurrence
    from apps.finance.models import Budget, Expense, ExpenseCategory, Payment
    from apps.households.models import Invitation, Membership
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

    if not isinstance(arguments, dict) or set(arguments) != {
        "entity",
        "query",
        "offset",
    }:
        raise ValueError("Invalid assistant search arguments")
    entity, query, offset = (
        arguments["entity"],
        arguments["query"],
        arguments["offset"],
    )
    if (
        not isinstance(query, str)
        or len(query) > 120
        or type(offset) is not int
        or not 0 <= offset <= 1_000_000
    ):
        raise ValueError("Invalid assistant search arguments")
    catalog = {
        "products": (
            Product,
            "household",
            ("name", "brand", "category"),
            ("id", "name", "brand", "category", "unit", "is_active"),
        ),
        "product_aliases": (
            ProductAlias,
            "product__household",
            ("alias", "product__name"),
            ("id", "product_id", "alias"),
        ),
        "price_observations": (
            PriceObservation,
            "household",
            ("store_name", "product__name"),
            (
                "id",
                "product_id",
                "store_name",
                "price_minor",
                "quantity",
                "unit",
                "observed_at",
            ),
        ),
        "shopping_lists": (
            ShoppingList,
            "household",
            ("name",),
            ("id", "name", "status", "created_at"),
        ),
        "shopping_list_items": (
            ShoppingListItem,
            "shopping_list__household",
            ("free_text_name", "product__name", "shopping_list__name"),
            (
                "id",
                "shopping_list_id",
                "product_id",
                "free_text_name",
                "quantity",
                "unit",
                "status",
                "priority",
            ),
        ),
        "inventory_items": (
            InventoryItem,
            "household",
            ("product__name",),
            ("id", "product_id", "product__name", "quantity", "unit"),
        ),
        "inventory_events": (
            InventoryEvent,
            "item__household",
            ("notes", "item__product__name"),
            ("id", "item_id", "event_type", "quantity_delta", "notes", "occurred_at"),
        ),
        "purchases": (
            Purchase,
            "household",
            ("store_name",),
            (
                "id",
                "purchased_at",
                "store_name",
                "total_amount_minor",
                "expense_id",
                "shopping_list_id",
            ),
        ),
        "purchase_items": (
            PurchaseItem,
            "purchase__household",
            ("product__name",),
            (
                "id",
                "purchase_id",
                "product_id",
                "quantity",
                "unit",
                "unit_price_minor",
                "line_total_minor",
            ),
        ),
        "chores": (
            Chore,
            "household",
            ("title", "description", "category"),
            ("id", "title", "description", "category", "is_active", "due_at"),
        ),
        "chore_occurrences": (
            ChoreOccurrence,
            "chore__household",
            ("chore__title",),
            ("id", "chore_id", "chore__title", "due_at", "assigned_to_id", "status"),
        ),
        "categories": (
            ExpenseCategory,
            "household",
            ("name", "kind"),
            ("id", "name", "kind", "is_active"),
        ),
        "expenses": (
            Expense,
            "household",
            ("description", "notes", "category__name"),
            (
                "id",
                "description",
                "category_id",
                "amount_minor",
                "currency",
                "incurred_on",
                "notes",
            ),
        ),
        "payments": (
            Payment,
            "household",
            ("expense__description", "notes"),
            ("id", "expense_id", "payer_id", "amount_minor", "paid_at", "notes"),
        ),
        "budgets": (
            Budget,
            "household",
            ("category__name",),
            ("id", "category_id", "period_start", "amount_minor"),
        ),
        "members": (
            Membership,
            "household",
            ("user__name",),
            ("id", "role", "status", "user__name"),
        ),
        "invitations": (
            Invitation,
            "household",
            (),
            ("id", "role", "created_at", "expires_at", "accepted_at", "revoked_at"),
        ),
    }
    if not isinstance(entity, str) or entity not in catalog:
        raise ValueError("Unsupported assistant search entity")
    household = require_membership(user, household_id).household
    model, household_field, searchable, fields = catalog[entity]
    records = model.objects.filter(**{household_field: household})
    query = query.strip()
    if query:
        conditions = Q()
        if query.isascii() and query.isdecimal() and len(query) <= 18:
            conditions |= Q(pk=int(query))
        for field in searchable:
            conditions |= Q(**{f"{field}__icontains": query})
        records = records.filter(conditions) if conditions else records.none()
    total = records.count()
    rows = list(records.order_by("pk")[offset : offset + PAGE_SIZE].values(*fields))
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                row[key] = value.isoformat()
            elif isinstance(value, Decimal):
                row[key] = str(value)
    return {
        "entity": entity,
        "query": query,
        "offset": offset,
        "total": total,
        "items": rows,
    }
