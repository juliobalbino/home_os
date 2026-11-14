"""Additional audited household mutations exposed to the assistant."""

from django.db import IntegrityError
from rest_framework.exceptions import ValidationError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.audit.models import AuditEvent
from apps.households.permissions import require_membership


def update_household_settings(user, household_id, arguments):
    household = require_membership(user, household_id, write=True, owner=True).household
    fields = []
    if "name" in arguments:
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValidationError({"name": "Informe um nome de até 120 caracteres."})
        household.name = name.strip()
        fields.append("name")
    if "currency" in arguments:
        currency = arguments["currency"]
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency != currency.upper()
        ):
            raise ValidationError(
                {"currency": "Use um código de moeda de três letras maiúsculas."}
            )
        household.currency = currency
        fields.append("currency")
    if "timezone" in arguments:
        timezone = arguments["timezone"]
        if not isinstance(timezone, str) or len(timezone) > 64:
            raise ValidationError({"timezone": "Fuso horário inválido."})
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone": "Fuso horário inválido."})
        household.timezone = timezone
        fields.append("timezone")
    if not fields:
        raise ValidationError({"name": "Informe uma alteração."})
    household.save(update_fields=fields)
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="household.updated",
        entity_type="household",
        entity_id=str(household.id),
        metadata={"fields": fields},
    )
    return {
        "id": str(household.id),
        "name": household.name,
        "currency": household.currency,
        "timezone": household.timezone,
    }


def update_shopping_list(user, household_id, arguments):
    from apps.shopping.models import ShoppingList

    household = require_membership(user, household_id, write=True).household
    row = ShoppingList.objects.filter(
        pk=arguments["shopping_list_id"], household=household
    ).first()
    if row is None:
        raise ValidationError(
            {"shopping_list_id": "Lista inválida para esta residência."}
        )
    fields = []
    if "name" in arguments:
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValidationError({"name": "Informe um nome de até 120 caracteres."})
        row.name = name.strip()
        fields.append("name")
    if "status" in arguments:
        if arguments["status"] not in ShoppingList.Status.values:
            raise ValidationError({"status": "Status inválido."})
        row.status = arguments["status"]
        fields.append("status")
    if not fields:
        raise ValidationError({"name": "Informe uma alteração."})
    row.save(update_fields=fields)
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="shopping_list.updated",
        entity_type="shopping_list",
        entity_id=str(row.id),
        metadata={"fields": fields},
    )
    return {"id": row.id, "name": row.name, "status": row.status}


def update_expense_category(user, household_id, arguments):
    from apps.finance.models import ExpenseCategory

    household = require_membership(user, household_id, write=True).household
    row = ExpenseCategory.objects.filter(
        pk=arguments["category_id"], household=household
    ).first()
    if row is None:
        raise ValidationError(
            {"category_id": "Categoria inválida para esta residência."}
        )
    fields = []
    if "name" in arguments:
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValidationError({"name": "Informe um nome de até 80 caracteres."})
        row.name = name.strip()
        fields.append("name")
    if "kind" in arguments:
        if arguments["kind"] not in {
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
        row.kind = arguments["kind"]
        fields.append("kind")
    if "is_active" in arguments:
        if type(arguments["is_active"]) is not bool:
            raise ValidationError({"is_active": "Valor inválido."})
        row.is_active = arguments["is_active"]
        fields.append("is_active")
    if not fields:
        raise ValidationError({"name": "Informe uma alteração."})
    try:
        row.save(update_fields=fields)
    except IntegrityError:
        raise ValidationError({"name": "Já existe uma categoria com este nome."})
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="category.updated",
        entity_type="expense_category",
        entity_id=str(row.id),
        metadata={"fields": fields},
    )
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "is_active": row.is_active,
    }


def adjust_product_inventory(user, household_id, arguments):
    from apps.inventory.models import InventoryItem
    from apps.inventory.services import record_event
    from apps.shopping.models import Product

    household = require_membership(user, household_id, write=True).household
    product = Product.objects.filter(
        pk=arguments["product_id"], household=household
    ).first()
    if product is None:
        raise ValidationError({"product_id": "Produto inválido para esta residência."})
    item, _ = InventoryItem.objects.get_or_create(
        household=household,
        product=product,
        unit=product.unit,
    )
    event, item = record_event(
        item=item,
        actor=user,
        event_type=arguments["event_type"],
        quantity_delta=arguments["quantity_delta"],
        notes=arguments["notes"],
    )
    return {
        "id": event.id,
        "inventory_item_id": item.id,
        "quantity": str(item.quantity),
    }
