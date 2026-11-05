"""Validated shopping domain mutations shared by HTTP and assistant tools."""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.finance.models import Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.households.models import Membership
from apps.shopping.models import (
    PriceObservation,
    Product,
    ProductAlias,
    Purchase,
    PurchaseItem,
    ShoppingList,
    ShoppingListItem,
)

MAX_AMOUNT_MINOR = 9223372036854775807


def quantity(value, *, positive=True):
    if isinstance(value, (bool, float)) or not isinstance(value, (int, Decimal, str)):
        raise ValidationError({"quantity": "Quantidade inválida."})
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity": "Quantidade inválida."})
    if (
        not result.is_finite()
        or (result <= 0 if positive else result == 0)
        or result.as_tuple().exponent < -4
        or abs(result) >= Decimal("10000000000")
    ):
        raise ValidationError({"quantity": "Quantidade inválida."})
    return result


def positive_integer(value, field="price_minor"):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > MAX_AMOUNT_MINOR
    ):
        raise ValidationError(
            {field: f"Informe um inteiro positivo até {MAX_AMOUNT_MINOR}."}
        )
    return value


def text(value, maximum, field="detail"):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValidationError({field: "Texto inválido ou muito longo."})
    return value


@transaction.atomic
def create_product(*, household, actor, name, unit, brand="", category=""):
    name = text(name, 120, "name").strip()
    unit = text(unit, 24, "unit").strip()
    brand = text(brand, 120, "brand")
    category = text(category, 80, "category")
    if not name or not unit:
        raise ValidationError({"detail": "Nome e unidade são obrigatórios."})
    if Product.objects.filter(household=household, name=name, brand=brand).exists():
        raise ValidationError({"name": "Este produto já existe."})
    try:
        product = Product.objects.create(
            household=household, name=name, unit=unit, brand=brand, category=category
        )
    except IntegrityError:
        raise ValidationError({"name": "Este produto já existe."})
    audit(household, actor, "product.created", "product", product.id)
    return product


@transaction.atomic
def update_product(*, product, actor, payload):
    for key, maximum in (("name", 120), ("brand", 120), ("category", 80), ("unit", 24)):
        if key in payload:
            value = text(payload[key], maximum, key).strip()
            if not value:
                raise ValidationError({key: "Campo obrigatório."})
            setattr(product, key, value)
    if "is_active" in payload:
        if not isinstance(payload["is_active"], bool):
            raise ValidationError({"is_active": "Valor inválido."})
        product.is_active = payload["is_active"]
    try:
        product.save()
    except IntegrityError:
        raise ValidationError({"name": "Este produto já existe."})
    audit(product.household, actor, "product.updated", "product", product.id)
    return product


@transaction.atomic
def add_alias(*, product, actor, alias):
    alias = text(alias, 120, "alias").strip()
    if not alias:
        raise ValidationError({"alias": "Informe um alias."})
    try:
        obj = ProductAlias.objects.create(product=product, alias=alias)
    except IntegrityError:
        raise ValidationError({"alias": "Este alias já existe para o produto."})
    audit(product.household, actor, "product.alias_added", "product_alias", obj.id)
    return obj


@transaction.atomic
def record_price(
    *, household, product, actor, price_minor, quantity_value, unit, store_name=""
):
    price_minor = positive_integer(price_minor)
    quantity_value = quantity(quantity_value)
    if unit != product.unit:
        raise ValidationError({"unit": "Unidade incompatível com o produto."})
    store_name = text(store_name, 120, "store_name")
    obs = PriceObservation.objects.create(
        household=household,
        product=product,
        price_minor=price_minor,
        quantity=quantity_value,
        unit=unit,
        store_name=store_name,
        source=PriceObservation.Source.MANUAL,
    )
    audit(household, actor, "price_observation.created", "price_observation", obs.id)
    return obs


@transaction.atomic
def add_list_item(
    *,
    shopping_list,
    actor,
    product,
    quantity_value,
    unit,
    free_text_name="",
    priority=0,
):
    shopping_list = ShoppingList.objects.select_for_update().get(pk=shopping_list.pk)
    q = quantity(quantity_value)
    free = text(free_text_name, 120, "free_text_name").strip()
    unit = text(unit, 24, "unit")
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or not 0 <= priority <= 32767
    ):
        raise ValidationError({"priority": "Prioridade inválida."})
    if (
        (product is None and not free)
        or (product is not None and free)
        or (product and unit != product.unit)
    ):
        raise ValidationError({"detail": "Item, quantidade ou unidade inválidos."})
    item = ShoppingListItem.objects.create(
        shopping_list=shopping_list,
        product=product,
        free_text_name=free,
        quantity=q,
        unit=unit,
        added_by=actor,
        priority=priority,
    )
    audit(
        shopping_list.household,
        actor,
        "shopping_list_item.created",
        "shopping_list_item",
        item.id,
    )
    return item


@transaction.atomic
def update_list_item(*, item, actor, payload):
    shopping_list_id = item.shopping_list_id
    ShoppingList.objects.select_for_update().get(pk=shopping_list_id)
    item = (
        ShoppingListItem.objects.select_for_update()
        .select_related("shopping_list")
        .get(pk=item.pk, shopping_list_id=shopping_list_id)
    )
    if "status" in payload:
        if payload["status"] not in ShoppingListItem.Status.values:
            raise ValidationError({"status": "Status inválido."})
        item.status = payload["status"]
    if "quantity" in payload:
        item.quantity = quantity(payload["quantity"])
    if not set(payload) <= {"status", "quantity"}:
        raise ValidationError({"detail": "Campos inválidos."})
    item.save()
    audit(
        item.shopping_list.household,
        actor,
        "shopping_list_item.updated",
        "shopping_list_item",
        item.id,
    )
    return item


def audit(household, actor, action, entity_type, entity_id, metadata=None):
    AuditEvent.objects.create(
        household=household,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata=metadata or {},
    )


@transaction.atomic
def create_purchase(
    *, household, actor, buyer, payload, idempotency_key, payload_hash=None
):
    rows = payload.get("items")
    if not isinstance(rows, list) or not rows:
        raise ValidationError({"items": "Informe linhas de compra."})
    parsed = []
    total = 0
    try:
        for row in rows:
            product = Product.objects.get(
                pk=row["product_id"], household=household, is_active=True
            )
            q = quantity(row["quantity"])
            unit = row["unit"]
            price = positive_integer(row["unit_price_minor"], "unit_price_minor")
            if unit != product.unit:
                raise ValueError
            line = int(
                (Decimal(price) * q).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            if line > MAX_AMOUNT_MINOR or (
                "line_total_minor" in row
                and positive_integer(row["line_total_minor"], "line_total_minor")
                != line
            ):
                raise ValueError
            total += line
            if total > MAX_AMOUNT_MINOR:
                raise ValueError
            parsed.append(
                (product, q, unit, price, line, row.get("shopping_list_item_id"))
            )
        if total <= 0:
            raise ValueError
        purchased_at = date.fromisoformat(payload["purchased_at"])
        store = text(payload.get("store_name", ""), 120, "store_name")
        list_obj = (
            ShoppingList.objects.get(
                pk=payload["shopping_list_id"], household=household
            )
            if payload.get("shopping_list_id")
            else None
        )
        category_id = payload.get("category_id")
        if category_id is not None:
            category = ExpenseCategory.objects.get(
                pk=category_id, household=household, is_active=True
            )
        else:
            category, _ = ExpenseCategory.objects.get_or_create(
                household=household, name="Compras", defaults={"kind": "general"}
            )
    except (
        KeyError,
        ValueError,
        TypeError,
        Product.DoesNotExist,
        ShoppingList.DoesNotExist,
        ExpenseCategory.DoesNotExist,
    ):
        raise ValidationError(
            {"detail": "Linhas, quantidades, totais, data ou lista inválidos."}
        )
    digest = (
        payload_hash
        or hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    old = Purchase.objects.filter(
        household=household, idempotency_key=idempotency_key
    ).first()
    if old:
        if old.payload_hash != digest:
            raise ValidationError({"detail": "Chave de idempotência reutilizada."})
        return old, False
    expense = Expense.objects.create(
        household=household,
        description=f"Compra - {store or 'Mercado'}",
        category=category,
        amount_minor=total,
        currency=household.currency,
        incurred_on=purchased_at,
        created_by=actor,
    )
    active = list(
        Membership.objects.filter(household=household, status="active").order_by("id")
    )
    base, rem = divmod(total, len(active))
    ExpenseSplit.objects.bulk_create(
        [
            ExpenseSplit(
                expense=expense, membership=m, amount_minor=base + (index < rem)
            )
            for index, m in enumerate(active)
        ]
    )
    Payment.objects.create(
        household=household,
        expense=expense,
        payer=buyer,
        amount_minor=total,
        notes="Pagamento da compra",
    )
    purchase = Purchase.objects.create(
        household=household,
        purchased_at=purchased_at,
        store_name=store,
        total_amount_minor=total,
        created_by=actor,
        buyer=buyer,
        shopping_list=list_obj,
        idempotency_key=idempotency_key,
        payload_hash=digest,
        expense=expense,
    )
    seen = set()
    for product, q, unit, price, line, item_id in parsed:
        linked = None
        if item_id is not None:
            if not list_obj:
                raise ValidationError({"detail": "Vínculo exige uma lista de compras."})
            linked = ShoppingListItem.objects.select_for_update().get(
                pk=item_id,
                shopping_list=list_obj,
                product=product,
                status=ShoppingListItem.Status.NEEDED,
            )
            if linked.id in seen:
                raise ValidationError({"detail": "Item da lista duplicado."})
            seen.add(linked.id)
            linked.status = ShoppingListItem.Status.PURCHASED
            linked.save(update_fields=["status"])
        item = PurchaseItem.objects.create(
            purchase=purchase,
            product=product,
            quantity=q,
            unit=unit,
            unit_price_minor=price,
            line_total_minor=line,
            shopping_list_item=linked,
        )
        from apps.inventory.services import apply_purchase_stock

        apply_purchase_stock(
            household=household,
            product=product,
            quantity_delta=q,
            actor=actor,
            purchase_item=item,
        )
        PriceObservation.objects.create(
            household=household,
            product=product,
            store_name=store,
            price_minor=price,
            quantity=q,
            unit=unit,
            source=PriceObservation.Source.PURCHASE,
        )
    audit(
        household,
        actor,
        "purchase.confirmed",
        "purchase",
        purchase.id,
        {"total_amount_minor": total, "item_count": len(parsed)},
    )
    return purchase, True
