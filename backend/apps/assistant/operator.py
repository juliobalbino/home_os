"""Strict allowlisted household tools exposed to the assistant operator."""

import hashlib
import json
import uuid

from django.db import transaction
from apps.households.permissions import require_membership

MAX_ROWS = 100


def _members(user, household_id):
    member = require_membership(user, household_id)
    return [
        {"membership_id": row["id"], "role": row["role"], "name": row["user__name"]}
        for row in member.household.memberships.filter(status="active")
        .select_related("user")
        .order_by("id")[:MAX_ROWS]
        .values("id", "role", "user__name")
    ]


def _categories(user, household_id):
    member = require_membership(user, household_id)
    from apps.finance.models import ExpenseCategory

    return list(
        ExpenseCategory.objects.filter(household=member.household, is_active=True)
        .order_by("name", "id")[:MAX_ROWS]
        .values("id", "name", "kind")
    )


def _finance(user, household_id):
    member = require_membership(user, household_id)
    from apps.finance.models import Budget, Expense, ExpenseCategory, Payment

    from apps.finance.selectors import settlements

    return {
        "expenses": [
            {
                "id": row.id,
                "description": row.description,
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "incurred_on": row.incurred_on.isoformat(),
                "category": row.category.name,
                "paid_minor": sum(row.payments.values_list("amount_minor", flat=True)),
            }
            for row in Expense.objects.filter(household=member.household)
            .select_related("category")
            .order_by("-incurred_on", "-id")[:MAX_ROWS]
        ],
        "categories": list(
            ExpenseCategory.objects.filter(household=member.household, is_active=True)
            .order_by("name", "id")[:MAX_ROWS]
            .values("id", "name", "kind")
        ),
        "budgets": list(
            Budget.objects.filter(household=member.household)
            .select_related("category")
            .order_by("-period_start", "id")[:MAX_ROWS]
            .values("id", "period_start", "amount_minor", "category_id")
        ),
        "payments": list(
            Payment.objects.filter(household=member.household)
            .order_by("-paid_at", "-id")[:MAX_ROWS]
            .values("id", "expense_id", "payer_id", "amount_minor", "paid_at")
        ),
        "settlements": settlements(member.household)[:MAX_ROWS],
    }


def _products(user, household_id):
    member = require_membership(user, household_id)
    from apps.shopping.models import Product

    return list(
        Product.objects.filter(household=member.household, is_active=True)
        .order_by("name", "id")[:MAX_ROWS]
        .values("id", "name", "brand", "category", "unit")
    )


def _lists(user, household_id):
    member = require_membership(user, household_id)
    from apps.shopping.models import ShoppingList

    return [
        {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "items": [
                {
                    "id": item.id,
                    "name": item.free_text_name or item.product.name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "status": item.status,
                }
                for item in row.items.select_related("product").all()[:MAX_ROWS]
            ],
        }
        for row in ShoppingList.objects.filter(household=member.household).order_by(
            "-created_at", "-id"
        )[:MAX_ROWS]
    ]


def _inventory(user, household_id):
    member = require_membership(user, household_id)
    from apps.inventory.models import InventoryItem

    return [
        {
            "product_id": row.product_id,
            "name": row.product.name,
            "quantity": str(row.quantity),
            "unit": row.unit,
        }
        for row in InventoryItem.objects.filter(household=member.household)
        .select_related("product")
        .order_by("product__name", "id")[:MAX_ROWS]
    ]


def _chores(user, household_id):
    member = require_membership(user, household_id)
    from apps.chores.models import Chore, ChoreOccurrence
    from django.db.models import Prefetch
    from apps.chores.models import ChoreAssignment

    chores = [
        {
            "id": chore.id,
            "title": chore.title,
            "description": chore.description,
            "category": chore.category,
            "is_active": chore.is_active,
            "due_at": chore.due_at.isoformat() if chore.due_at else None,
            "recurrence_rule": chore.recurrence_rule,
            "assigned_membership_ids": [
                assignment.membership_id for assignment in chore.operator_assignments
            ],
        }
        for chore in Chore.objects.filter(household=member.household)
        .prefetch_related(
            Prefetch(
                "assignments",
                queryset=ChoreAssignment.objects.order_by("membership_id")[:MAX_ROWS],
                to_attr="operator_assignments",
            )
        )
        .order_by("id")[:MAX_ROWS]
    ]
    occurrences = [
        {
            "id": item.id,
            "chore_id": item.chore_id,
            "title": item.chore.title,
            "due_at": item.due_at.isoformat(),
            "status": item.status,
        }
        for item in ChoreOccurrence.objects.filter(chore__household=member.household)
        .select_related("chore")
        .order_by("due_at", "id")[:MAX_ROWS]
    ]
    return {"chores": chores, "occurrences": occurrences}


def _household_metadata(user, household_id):
    member = require_membership(user, household_id)
    household = member.household
    # Invitation tokens and hashes are deliberately never selected or serialized.
    return {
        "household": {
            "id": str(household.id),
            "name": household.name,
            "currency": household.currency,
            "timezone": household.timezone,
        },
        "members": _members(user, household_id),
        "invitations": [
            {
                "id": row.id,
                "role": row.role,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "accepted": row.accepted_at is not None,
            }
            for row in household.invitations.order_by("-created_at", "-id")[:MAX_ROWS]
        ],
    }


TOOLS = {
    "household_members": (set(), _members),
    "finance_categories": (set(), _categories),
    "finance_records": (set(), _finance),
    "shopping_products": (set(), _products),
    "shopping_lists": (set(), _lists),
    "inventory": (set(), _inventory),
    "chores": (set(), _chores),
    "household_metadata": (set(), _household_metadata),
}


def _create_shopping_list(user, household_id, arguments):
    from apps.audit.models import AuditEvent
    from apps.households.permissions import require_membership
    from apps.shopping.models import ShoppingList

    name = arguments["name"]
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError("Invalid shopping list name")
    name = name.strip()
    membership = require_membership(user, household_id, write=True)
    shopping_list = ShoppingList.objects.create(
        household=membership.household, name=name, created_by=user
    )
    result = {
        "id": shopping_list.id,
        "name": shopping_list.name,
        "status": shopping_list.status,
    }
    AuditEvent.objects.create(
        household=membership.household,
        actor=user,
        action="shopping_list.created",
        entity_type="shopping_list",
        entity_id=str(shopping_list.id),
        metadata={},
    )
    return result


FINANCE_SCHEMAS = {
    "create_expense": {
        "description",
        "category_id",
        "amount_minor",
        "incurred_on",
        "split_method",
        "splits",
    },
    "update_expense": {
        "expense_id",
        "description",
        "category_id",
        "amount_minor",
        "incurred_on",
        "notes",
        "split_method",
        "splits",
    },
    "record_expense_payment": {"expense_id", "payer_id", "amount_minor", "notes"},
    "set_budget": {"period", "amount_minor", "category_id"},
    "create_expense_category": {"name", "kind"},
}

SHOPPING_SCHEMAS = {
    "propose_shopping_list_deletion": {"shopping_list_id"},
    "create_shopping_product": {"name", "brand", "category", "unit"},
    "update_shopping_product": {
        "product_id",
        "name",
        "brand",
        "category",
        "unit",
        "is_active",
    },
    "add_shopping_product_alias": {"product_id", "alias"},
    "record_price_observation": {
        "product_id",
        "price_minor",
        "quantity",
        "unit",
        "store_name",
    },
    "add_shopping_list_item": {
        "shopping_list_id",
        "product_id",
        "free_text_name",
        "quantity",
        "unit",
        "priority",
    },
    "update_shopping_list_item": {"item_id", "status", "quantity"},
    "record_inventory_event": {
        "inventory_item_id",
        "event_type",
        "quantity_delta",
        "notes",
    },
    "record_purchase": {
        "purchased_at",
        "store_name",
        "category_id",
        "shopping_list_id",
        "items",
    },
}

CHORE_SCHEMAS = {
    "propose_chore_occurrence_generation": {"chore_id", "start_date", "end_date"},
    "create_chore": {
        "title",
        "description",
        "category",
        "recurrence_rule",
        "due_at",
        "is_active",
        "assignment_ids",
    },
    "update_chore": {
        "chore_id",
        "title",
        "description",
        "category",
        "recurrence_rule",
        "due_at",
        "is_active",
        "assignment_ids",
    },
    "set_chore_occurrence_status": {"occurrence_id", "status"},
}

MEMBERSHIP_SCHEMAS = {
    "propose_household_archive": set(),
    "propose_membership_role_change": {"membership_id", "role"},
    "propose_membership_removal": {"membership_id"},
    "propose_ownership_transfer": {"new_owner_membership_id"},
}
INVITATION_SCHEMAS = {
    "propose_invitation_creation": {"role"},
    "propose_invitation_revocation": {"invitation_id"},
}
ACCOUNT_SCHEMAS = {"propose_account_deactivation": set()}

DIRECT_WRITE_SUMMARIES = {
    "create_shopping_list": "Lista de compras criada",
    "create_shopping_product": "Produto cadastrado",
    "update_shopping_product": "Produto atualizado",
    "add_shopping_product_alias": "Nome alternativo do produto adicionado",
    "record_price_observation": "Preço registrado",
    "add_shopping_list_item": "Item adicionado à lista de compras",
    "update_shopping_list_item": "Item da lista atualizado",
    "record_inventory_event": "Estoque atualizado",
    "record_purchase": "Compra registrada",
    "create_chore": "Tarefa criada",
    "update_chore": "Tarefa atualizada",
    "set_chore_occurrence_status": "Ocorrência da tarefa atualizada",
    "create_expense": "Despesa registrada",
    "update_expense": "Despesa atualizada",
    "record_expense_payment": "Pagamento registrado",
    "set_budget": "Orçamento atualizado",
    "create_expense_category": "Categoria de despesa criada",
}


def is_direct_write(name):
    return DIRECT_WRITE_SUMMARIES.get(name)


TOOL_DESCRIPTIONS = {
    "household_members": "Read household members, roles, and membership IDs before assigning chores or proposing access changes.",
    "finance_categories": "Read expense categories and category IDs for this household.",
    "finance_records": "Read expenses, payments, and budgets for this household.",
    "shopping_products": "Read shopping products and product IDs for this household.",
    "shopping_lists": "Read shopping lists, list items, and their IDs for this household.",
    "inventory": "Read inventory items, quantities, and inventory item IDs for this household.",
    "chores": "Read chores, assignments, occurrences, and their IDs for this household.",
    "household_metadata": "Read household settings and metadata.",
    "create_expense": "Create an expense in household finances; amounts are in minor currency units.",
    "update_expense": "Update an existing household expense by expense ID.",
    "record_expense_payment": "Record a payment for an existing household expense.",
    "set_budget": "Create or update a household budget for a period.",
    "create_expense_category": "Create a category for household expenses.",
    "create_shopping_product": "Create a shopping product in the household catalog.",
    "update_shopping_product": "Update an existing shopping product.",
    "add_shopping_product_alias": "Add an alternative name to a shopping product.",
    "record_price_observation": "Record an observed shopping product price.",
    "add_shopping_list_item": "Add an item to an existing shopping list using its list ID.",
    "update_shopping_list_item": "Update the status or quantity of a shopping list item.",
    "record_inventory_event": "Adjust inventory quantity by recording an inventory event.",
    "record_purchase": "Record a purchase and update the linked shopping and inventory data.",
    "create_chore": "Create a household chore, optionally with assignments and recurrence.",
    "update_chore": "Update an existing household chore.",
    "set_chore_occurrence_status": "Mark a chore occurrence completed, skipped, or cancelled.",
}


def _shopping_write(name, user, household_id, arguments, request_uuid, call_index):
    from rest_framework.exceptions import ValidationError
    from apps.shopping.models import Product, ShoppingList, ShoppingListItem
    from apps.inventory.models import InventoryItem
    from apps.shopping import services
    from apps.inventory.services import record_event

    member = require_membership(user, household_id, write=True)
    household = member.household

    def scoped(model, key, value, **extra):
        try:
            return model.objects.get(pk=value, **extra)
        except (model.DoesNotExist, ValueError, TypeError):
            raise ValidationError({key: "Registro inválido para esta residência."})

    if name == "create_shopping_product":
        p = services.create_product(household=household, actor=user, **arguments)
        return {
            "id": p.id,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "unit": p.unit,
        }
    if name == "update_shopping_product":
        p = scoped(Product, "product_id", arguments["product_id"], household=household)
        p = services.update_product(
            product=p,
            actor=user,
            payload={k: v for k, v in arguments.items() if k != "product_id"},
        )
        return {
            "id": p.id,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "unit": p.unit,
            "is_active": p.is_active,
        }
    if name == "add_shopping_product_alias":
        p = scoped(Product, "product_id", arguments["product_id"], household=household)
        a = services.add_alias(product=p, actor=user, alias=arguments["alias"])
        return {"id": a.id, "product_id": p.id, "alias": a.alias}
    if name == "record_price_observation":
        p = scoped(Product, "product_id", arguments["product_id"], household=household)
        o = services.record_price(
            household=household,
            product=p,
            actor=user,
            price_minor=arguments["price_minor"],
            quantity_value=arguments["quantity"],
            unit=arguments["unit"],
            store_name=arguments.get("store_name", ""),
        )
        return {"id": o.id, "source": o.source}
    if name == "add_shopping_list_item":
        shopping_list = scoped(
            ShoppingList,
            "shopping_list_id",
            arguments["shopping_list_id"],
            household=household,
        )
        product = (
            scoped(Product, "product_id", arguments["product_id"], household=household)
            if arguments.get("product_id")
            else None
        )
        i = services.add_list_item(
            shopping_list=shopping_list,
            actor=user,
            product=product,
            quantity_value=arguments["quantity"],
            unit=arguments.get("unit", product.unit if product else ""),
            free_text_name=arguments.get("free_text_name", ""),
            priority=arguments.get("priority", 0),
        )
        return {
            "id": i.id,
            "quantity": str(i.quantity),
            "unit": i.unit,
            "status": i.status,
        }
    if name == "update_shopping_list_item":
        i = scoped(
            ShoppingListItem,
            "item_id",
            arguments["item_id"],
            shopping_list__household=household,
        )
        i = services.update_list_item(
            item=i,
            actor=user,
            payload={k: v for k, v in arguments.items() if k != "item_id"},
        )
        return {"id": i.id, "status": i.status, "quantity": str(i.quantity)}
    if name == "record_inventory_event":
        i = scoped(
            InventoryItem,
            "inventory_item_id",
            arguments["inventory_item_id"],
            household=household,
        )
        event, i = record_event(
            item=i,
            actor=user,
            event_type=arguments["event_type"],
            quantity_delta=arguments["quantity_delta"],
            notes=arguments.get("notes", ""),
        )
        return {"id": event.id, "quantity": str(i.quantity)}
    if name == "record_purchase":
        purchase, created = services.create_purchase(
            household=household,
            actor=user,
            buyer=member,
            payload=arguments,
            idempotency_key=f"assistant:{user.pk}:{household.pk}:{request_uuid}:{call_index}",
        )
        return {
            "id": purchase.id,
            "total_amount_minor": purchase.total_amount_minor,
            "expense_id": purchase.expense_id,
        }
    raise ValueError("Unsupported assistant tool")


def _strict_arguments(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Invalid assistant tool arguments")
    expected = FINANCE_SCHEMAS[name]
    if set(arguments) - expected:
        raise ValueError("Invalid assistant tool arguments")
    required = {
        "create_expense": expected,
        "update_expense": {"expense_id"},
        "record_expense_payment": {"expense_id", "payer_id", "amount_minor"},
        "set_budget": {"period", "amount_minor"},
        "create_expense_category": {"name", "kind"},
    }[name]
    if not required <= set(arguments):
        raise ValueError("Invalid assistant tool arguments")
    id_fields = {
        "create_expense": {"category_id"},
        "update_expense": {"expense_id", "category_id"},
        "record_expense_payment": {"expense_id", "payer_id"},
        "set_budget": {"category_id"},
    }.get(name, set())
    for field in id_fields & arguments.keys():
        value = arguments[field]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError("Invalid assistant tool arguments")
    if name in {"create_expense", "update_expense"}:
        for field in ("description", "incurred_on", "notes", "split_method"):
            if field in arguments and not isinstance(arguments[field], str):
                raise ValueError("Invalid assistant tool arguments")
        if "incurred_on" in arguments:
            import re

            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", arguments["incurred_on"]):
                raise ValueError("Invalid assistant tool arguments")
    if name == "set_budget":
        import re

        if not isinstance(arguments["period"], str) or not re.fullmatch(
            r"\d{4}-(0[1-9]|1[0-2])", arguments["period"]
        ):
            raise ValueError("Invalid assistant tool arguments")
    if (
        name == "record_expense_payment"
        and "notes" in arguments
        and not isinstance(arguments["notes"], str)
    ):
        raise ValueError("Invalid assistant tool arguments")
    if name == "create_expense_category" and any(
        not isinstance(arguments[k], str) for k in ("name", "kind")
    ):
        raise ValueError("Invalid assistant tool arguments")
    if name in {"create_expense", "update_expense"} and "splits" in arguments:
        method = arguments.get("split_method", "equal")
        keys = (
            {"membership_id"}
            if method == "equal"
            else {
                "membership_id",
                "percent" if method == "percentage" else "amount_minor",
            }
        )
        if not isinstance(arguments["splits"], list) or any(
            not isinstance(row, dict) or set(row) != keys for row in arguments["splits"]
        ):
            raise ValueError("Invalid assistant tool arguments")


def _finance_write(name, user, household_id, arguments):
    from apps.finance.models import Expense
    from apps.households.models import Membership
    from apps.finance.services import (
        create_expense,
        update_expense,
        record_payment,
        set_budget,
        create_expense_category,
    )

    membership = require_membership(user, household_id, write=True)
    household = membership.household
    if name == "create_expense":
        expense = create_expense(household=household, actor=user, payload=arguments)
        return {
            "id": expense.id,
            "description": expense.description,
            "amount_minor": expense.amount_minor,
            "category_id": expense.category_id,
            "incurred_on": expense.incurred_on.isoformat(),
        }
    if name == "update_expense":
        try:
            expense = Expense.objects.get(
                pk=arguments["expense_id"], household=household
            )
        except (Expense.DoesNotExist, ValueError, TypeError):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"expense_id": "Despesa inválida."})
        expense = update_expense(
            expense=expense,
            actor=user,
            payload={k: v for k, v in arguments.items() if k != "expense_id"},
        )
        return {
            "id": expense.id,
            "description": expense.description,
            "amount_minor": expense.amount_minor,
            "category_id": expense.category_id,
            "incurred_on": expense.incurred_on.isoformat(),
        }
    if name == "record_expense_payment":
        try:
            expense = Expense.objects.get(
                pk=arguments["expense_id"], household=household
            )
            payer = Membership.objects.get(
                pk=arguments["payer_id"], household=household, status="active"
            )
        except (Expense.DoesNotExist, Membership.DoesNotExist, ValueError, TypeError):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"expense_id": "Despesa ou pagador inválido."})
        payment = record_payment(
            expense=expense,
            payer=payer,
            actor=user,
            amount_minor=arguments["amount_minor"],
            notes=arguments.get("notes", ""),
        )
        return {
            "id": payment.id,
            "expense_id": expense.id,
            "payer_id": payer.id,
            "amount_minor": payment.amount_minor,
        }
    if name == "set_budget":
        budget = set_budget(
            household=household,
            actor=user,
            period=arguments["period"],
            amount_minor=arguments["amount_minor"],
            category_id=arguments.get("category_id"),
        )
        return {
            "id": budget.id,
            "period": budget.period_start.strftime("%Y-%m"),
            "category_id": budget.category_id,
            "amount_minor": budget.amount_minor,
        }
    category = create_expense_category(
        household=household, actor=user, name=arguments["name"], kind=arguments["kind"]
    )
    return {"id": category.id, "name": category.name, "kind": category.kind}


def _execute_write(name, arguments, user, household_id, request_uuid, call_index):
    from apps.assistant.models import AssistantToolExecution

    if name in ACCOUNT_SCHEMAS:
        require_membership(user, household_id)
        from apps.accounts.services import create_account_deactivation_proposal

        return create_account_deactivation_proposal(user)

    request_uuid = uuid.UUID(str(request_uuid))
    if (
        isinstance(call_index, bool)
        or not isinstance(call_index, int)
        or not 0 <= call_index <= 32767
    ):
        raise ValueError("Invalid assistant tool call index")
    digest = hashlib.sha256(
        json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        member = require_membership(
            user, household_id, write=name not in ACCOUNT_SCHEMAS
        )
        old = AssistantToolExecution.objects.filter(
            user=user,
            household_id=member.household_id,
            request_uuid=request_uuid,
            call_index=call_index,
        ).first()
        if old:
            if old.tool_name != name or old.arguments_hash != digest:
                raise ValueError("Assistant tool identity was reused")
            return old.result
        if name in ACCOUNT_SCHEMAS:
            from apps.accounts.services import create_account_deactivation_proposal

            result = create_account_deactivation_proposal(user)
        elif name == "create_shopping_list":
            result = _create_shopping_list(user, household_id, arguments)
        elif name == "propose_shopping_list_deletion":
            from apps.assistant.proposals import create_shopping_list_deletion

            result = create_shopping_list_deletion(
                user=user,
                household_id=household_id,
                shopping_list_id=arguments["shopping_list_id"],
            )
        elif name == "propose_chore_occurrence_generation":
            from apps.assistant.proposals import create_chore_occurrence_generation

            result = create_chore_occurrence_generation(
                user=user, household_id=household_id, **arguments
            )
        elif name == "propose_membership_role_change":
            from apps.assistant.proposals import create_membership_role_change

            result = create_membership_role_change(
                user=user, household_id=household_id, **arguments
            )
        elif name == "propose_household_archive":
            from apps.assistant.proposals import create_household_archive

            result = create_household_archive(user=user, household_id=household_id)
        elif name == "propose_membership_removal":
            from apps.assistant.proposals import create_membership_removal

            result = create_membership_removal(
                user=user, household_id=household_id, **arguments
            )
        elif name == "propose_ownership_transfer":
            from apps.assistant.proposals import create_ownership_transfer

            result = create_ownership_transfer(
                user=user, household_id=household_id, **arguments
            )
        elif name in INVITATION_SCHEMAS:
            from apps.assistant.proposals import (
                create_invitation_creation,
                create_invitation_revocation,
            )

            creator = (
                create_invitation_creation
                if name == "propose_invitation_creation"
                else create_invitation_revocation
            )
            result = creator(user=user, household_id=household_id, **arguments)
        elif name in SHOPPING_SCHEMAS:
            result = _shopping_write(
                name,
                household_id=household_id,
                user=user,
                arguments=arguments,
                request_uuid=request_uuid,
                call_index=call_index,
            )
        elif name in CHORE_SCHEMAS:
            result = _chore_write(name, user, household_id, arguments)
        else:
            result = _finance_write(name, user, household_id, arguments)
        AssistantToolExecution.objects.create(
            user=user,
            household_id=member.household_id,
            request_uuid=request_uuid,
            call_index=call_index,
            tool_name=name,
            arguments_hash=digest,
            result=result,
        )
    return result


def _chore_write(name, user, household_id, arguments):
    from rest_framework.exceptions import NotFound
    from apps.chores import services
    from apps.chores.models import Chore, ChoreOccurrence

    member = require_membership(user, household_id, write=True)
    if name == "propose_chore_occurrence_generation":
        from apps.assistant.proposals import create_chore_occurrence_generation

        return create_chore_occurrence_generation(
            user=user, household_id=household_id, **arguments
        )
    if name == "create_chore":
        chore = services.create_chore(
            household=member.household, actor=user, payload=arguments
        )
        return services.chore_data(chore)
    if name == "update_chore":
        try:
            chore = Chore.objects.get(
                pk=arguments["chore_id"], household=member.household
            )
        except (Chore.DoesNotExist, ValueError, TypeError):
            raise NotFound()
        chore = services.update_chore(
            chore=chore,
            actor=user,
            payload={k: v for k, v in arguments.items() if k != "chore_id"},
        )
        return services.chore_data(chore)
    try:
        occurrence = ChoreOccurrence.objects.select_related("chore").get(
            pk=arguments["occurrence_id"], chore__household=member.household
        )
    except (ChoreOccurrence.DoesNotExist, ValueError, TypeError):
        raise NotFound()
    occurrence = services.set_occurrence_status(
        occurrence=occurrence, actor=user, status=arguments["status"]
    )
    return {"id": occurrence.id, "status": occurrence.status}


def tool_definitions():
    definitions = [
        {
            "type": "function",
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
        for name in TOOLS
    ]
    definitions.append(
        {
            "type": "function",
            "name": "propose_household_archive",
            "description": "Prepare an explicit-confirmation household archive proposal.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    )
    definitions.append(
        {
            "type": "function",
            "name": "propose_account_deactivation",
            "description": "Prepare an explicit-confirmation account deactivation proposal.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    )
    definitions.append(
        {
            "type": "function",
            "name": "create_shopping_list",
            "description": "Create a shopping list in the authenticated household.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        }
    )
    definitions.append(
        {
            "type": "function",
            "name": "propose_membership_removal",
            "description": "Prepare an explicit-confirmation membership removal proposal.",
            "parameters": {
                "type": "object",
                "properties": {"membership_id": {"type": "integer"}},
                "required": ["membership_id"],
                "additionalProperties": False,
            },
        }
    )
    finance_props = {
        "description": {"type": "string"},
        "category_id": {"type": "integer"},
        "amount_minor": {"type": "integer"},
        "incurred_on": {"type": "string"},
        "split_method": {"type": "string", "enum": ["equal", "fixed", "percentage"]},
        "splits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "membership_id": {"type": "integer"},
                    "amount_minor": {"type": "integer"},
                    "percent": {"type": "number"},
                },
                "required": ["membership_id"],
                "additionalProperties": False,
            },
        },
        "expense_id": {"type": "integer"},
        "payer_id": {"type": "integer"},
        "notes": {"type": "string"},
        "period": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
    }
    requireds = {
        "create_expense": [
            "description",
            "category_id",
            "amount_minor",
            "incurred_on",
            "split_method",
            "splits",
        ],
        "update_expense": ["expense_id"],
        "record_expense_payment": ["expense_id", "payer_id", "amount_minor"],
        "set_budget": ["period", "amount_minor"],
        "create_expense_category": ["name", "kind"],
    }
    for name, keys in FINANCE_SCHEMAS.items():
        definitions.append(
            {
                "type": "function",
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": {
                    "type": "object",
                    "properties": {k: finance_props[k] for k in keys},
                    "required": requireds[name],
                    "additionalProperties": False,
                },
            }
        )
    shopping_props = {
        "name": {"type": "string"},
        "brand": {"type": "string"},
        "category": {"type": "string"},
        "unit": {"type": "string"},
        "product_id": {"type": "integer"},
        "is_active": {"type": "boolean"},
        "alias": {"type": "string"},
        "price_minor": {"type": "integer"},
        "quantity": {"type": "string"},
        "store_name": {"type": "string"},
        "shopping_list_id": {"type": "integer"},
        "free_text_name": {"type": "string"},
        "priority": {"type": "integer"},
        "item_id": {"type": "integer"},
        "status": {"type": "string", "enum": ["needed", "purchased", "skipped"]},
        "inventory_item_id": {"type": "integer"},
        "event_type": {
            "type": "string",
            "enum": ["consumption", "adjustment", "loss", "correction"],
        },
        "quantity_delta": {"type": "string"},
        "notes": {"type": "string"},
        "purchased_at": {"type": "string"},
        "category_id": {"type": "integer"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"},
                    "quantity": {"type": "string"},
                    "unit": {"type": "string"},
                    "unit_price_minor": {"type": "integer"},
                    "line_total_minor": {"type": "integer"},
                    "shopping_list_item_id": {"type": "integer"},
                },
                "required": ["product_id", "quantity", "unit", "unit_price_minor"],
                "additionalProperties": False,
            },
        },
    }
    shopping_required = {
        "propose_shopping_list_deletion": ["shopping_list_id"],
        "create_shopping_product": ["name", "unit"],
        "update_shopping_product": ["product_id"],
        "add_shopping_product_alias": ["product_id", "alias"],
        "record_price_observation": ["product_id", "price_minor", "quantity", "unit"],
        "add_shopping_list_item": ["shopping_list_id", "quantity", "unit"],
        "update_shopping_list_item": ["item_id"],
        "record_inventory_event": ["inventory_item_id", "event_type", "quantity_delta"],
        "record_purchase": ["purchased_at", "items"],
    }
    for name, keys in SHOPPING_SCHEMAS.items():
        definitions.append(
            {
                "type": "function",
                "name": name,
                "description": "Prepare an explicit-confirmation shopping-list deletion proposal."
                if name == "propose_shopping_list_deletion"
                else TOOL_DESCRIPTIONS[name],
                "parameters": {
                    "type": "object",
                    "properties": {k: shopping_props[k] for k in keys},
                    "required": shopping_required[name],
                    "additionalProperties": False,
                },
            }
        )
    chore_props = {
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": "string", "format": "date"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "due_at": {"type": ["string", "null"]},
        "recurrence_rule": {
            "type": ["object", "null"],
            "properties": {
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"]},
                "time": {"type": "string"},
                "weekday": {"type": "integer"},
                "day": {"type": "integer"},
            },
            "required": ["frequency", "time"],
            "additionalProperties": False,
        },
        "assignment_ids": {"type": "array", "items": {"type": "integer"}},
        "is_active": {"type": "boolean"},
        "chore_id": {"type": "integer"},
        "occurrence_id": {"type": "integer"},
        "status": {"type": "string", "enum": ["completed", "skipped", "cancelled"]},
    }
    chore_required = {
        "propose_chore_occurrence_generation": ["chore_id", "start_date", "end_date"],
        "create_chore": ["title"],
        "update_chore": ["chore_id"],
        "set_chore_occurrence_status": ["occurrence_id", "status"],
    }
    for name, keys in CHORE_SCHEMAS.items():
        definitions.append(
            {
                "type": "function",
                "name": name,
                "description": "Prepare an explicit-confirmation chore occurrence proposal."
                if name == "propose_chore_occurrence_generation"
                else TOOL_DESCRIPTIONS[name],
                "parameters": {
                    "type": "object",
                    "properties": {k: chore_props[k] for k in keys},
                    "required": chore_required[name],
                    "additionalProperties": False,
                },
            }
        )
    definitions.append(
        {
            "type": "function",
            "name": "propose_membership_role_change",
            "description": "Prepare an explicit-confirmation membership role change proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "membership_id": {"type": "integer"},
                    "role": {"type": "string", "enum": ["member", "viewer"]},
                },
                "required": ["membership_id", "role"],
                "additionalProperties": False,
            },
        }
    )
    definitions.append(
        {
            "type": "function",
            "name": "propose_ownership_transfer",
            "description": "Prepare an explicit-confirmation household ownership transfer proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_owner_membership_id": {"type": "integer", "minimum": 1}
                },
                "required": ["new_owner_membership_id"],
                "additionalProperties": False,
            },
        }
    )
    definitions.extend(
        [
            {
                "type": "function",
                "name": "propose_invitation_creation",
                "description": "Prepare an explicit-confirmation household invitation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["member", "viewer"]}
                    },
                    "required": ["role"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "propose_invitation_revocation",
                "description": "Prepare an explicit-confirmation invitation revocation.",
                "parameters": {
                    "type": "object",
                    "properties": {"invitation_id": {"type": "integer", "minimum": 1}},
                    "required": ["invitation_id"],
                    "additionalProperties": False,
                },
            },
        ]
    )
    return definitions


def dispatch_tool(
    name, arguments, *, user, household_id, request_uuid=None, call_index=None
):
    write_name = (
        name == "create_shopping_list"
        or name in FINANCE_SCHEMAS
        or name in SHOPPING_SCHEMAS
        or name in CHORE_SCHEMAS
        or name in MEMBERSHIP_SCHEMAS
        or name in INVITATION_SCHEMAS
        or name in ACCOUNT_SCHEMAS
    )
    if write_name:
        if name == "create_shopping_list" and (
            not isinstance(arguments, dict) or set(arguments) != {"name"}
        ):
            raise ValueError("Invalid assistant tool arguments")
        if name in FINANCE_SCHEMAS:
            _strict_arguments(name, arguments)
        if name in MEMBERSHIP_SCHEMAS:
            if name == "propose_household_archive":
                if not isinstance(arguments, dict) or arguments:
                    raise ValueError("Invalid assistant tool arguments")
            else:
                membership_key = (
                    "new_owner_membership_id"
                    if name == "propose_ownership_transfer"
                    else "membership_id"
                )
                if (
                    not isinstance(arguments, dict)
                    or set(arguments) != MEMBERSHIP_SCHEMAS[name]
                    or type(arguments.get(membership_key)) is not int
                    or arguments[membership_key] <= 0
                ):
                    raise ValueError("Invalid assistant tool arguments")
            if name == "propose_membership_role_change" and arguments.get(
                "role"
            ) not in {"member", "viewer"}:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"role": "Invalid membership role."})
        if name in INVITATION_SCHEMAS:
            if (
                not isinstance(arguments, dict)
                or set(arguments) != INVITATION_SCHEMAS[name]
            ):
                raise ValueError("Invalid assistant tool arguments")
        if name in ACCOUNT_SCHEMAS and (not isinstance(arguments, dict) or arguments):
            raise ValueError("Invalid assistant tool arguments")
            if name == "propose_invitation_creation" and arguments["role"] not in {
                "member",
                "viewer",
            }:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"role": "Invalid invitation role."})
            if name == "propose_invitation_revocation" and (
                type(arguments["invitation_id"]) is not int
                or arguments["invitation_id"] <= 0
            ):
                raise ValueError("Invalid assistant tool arguments")
        if name in SHOPPING_SCHEMAS:
            required = {
                "propose_chore_occurrence_generation": {
                    "chore_id",
                    "start_date",
                    "end_date",
                },
                "create_shopping_product": {"name", "unit"},
                "update_shopping_product": {"product_id"},
                "add_shopping_product_alias": {"product_id", "alias"},
                "record_price_observation": {
                    "product_id",
                    "price_minor",
                    "quantity",
                    "unit",
                },
                "add_shopping_list_item": {"shopping_list_id", "quantity", "unit"},
                "update_shopping_list_item": {"item_id"},
                "record_inventory_event": {
                    "inventory_item_id",
                    "event_type",
                    "quantity_delta",
                },
                "record_purchase": {"purchased_at", "items"},
                "propose_shopping_list_deletion": {"shopping_list_id"},
            }[name]
            if (
                not isinstance(arguments, dict)
                or set(arguments) - SHOPPING_SCHEMAS[name]
                or not required <= set(arguments)
            ):
                raise ValueError("Invalid assistant tool arguments")
            if name == "propose_shopping_list_deletion" and (
                type(arguments["shopping_list_id"]) is not int
                or arguments["shopping_list_id"] <= 0
            ):
                raise ValueError("Invalid assistant tool arguments")
        if name in CHORE_SCHEMAS:
            required = {
                "propose_chore_occurrence_generation": {
                    "chore_id",
                    "start_date",
                    "end_date",
                },
                "create_chore": {"title"},
                "update_chore": {"chore_id"},
                "set_chore_occurrence_status": {"occurrence_id", "status"},
            }[name]
            if (
                not isinstance(arguments, dict)
                or set(arguments) - CHORE_SCHEMAS[name]
                or not required <= set(arguments)
            ):
                raise ValueError("Invalid assistant tool arguments")
            id_fields = {"chore_id", "occurrence_id"} & arguments.keys()
            if any(
                type(arguments[k]) is not int or arguments[k] <= 0 for k in id_fields
            ):
                raise ValueError("Invalid assistant tool arguments")
            if name == "propose_chore_occurrence_generation":
                from datetime import date

                try:
                    from datetime import date

                    for field in ("start_date", "end_date"):
                        value = arguments[field]
                        if (
                            not isinstance(value, str)
                            or date.fromisoformat(value).isoformat() != value
                        ):
                            raise ValueError
                except ValueError:
                    raise ValueError("Invalid assistant tool arguments")
        try:
            uuid.UUID(str(request_uuid))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("A valid request UUID is required")
        return _execute_write(
            name, arguments, user, household_id, request_uuid, call_index
        )
    entry = TOOLS.get(name)
    if not entry:
        raise ValueError("Unsupported assistant tool")
    allowed, handler = entry
    if not isinstance(arguments, dict) or set(arguments) != allowed:
        raise ValueError("Invalid assistant tool arguments")
    return handler(user, household_id)
