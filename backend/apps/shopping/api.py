import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import F
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.finance.models import Expense, ExpenseCategory, ExpenseSplit, Payment
from apps.households.models import Membership
from apps.households.permissions import require_membership
from apps.inventory.models import InventoryEvent, InventoryItem
from apps.audit.models import AuditEvent
from apps.shopping.models import (
    PriceObservation,
    Product,
    ProductAlias,
    Purchase,
    PurchaseItem,
    ShoppingList,
    ShoppingListItem,
)


class Conflict(APIException):
    status_code = 409
    default_detail = "A chave de idempotência já foi usada com outro conteúdo."


def _quantity(value):
    if isinstance(value, (bool, float)):
        raise ValueError
    if not isinstance(value, (int, Decimal, str)):
        raise ValueError
    result = Decimal(value)
    if (
        not result.is_finite()
        or result <= 0
        or result.as_tuple().exponent < -4
        or result >= Decimal("10000000000")
    ):
        raise ValueError
    return result


def _positive_integer(value):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > 9223372036854775807
    ):
        raise ValueError
    return value


def _text(value, maximum):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError
    return value


def _product(product):
    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "unit": product.unit,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def products(request, household_id):
    member = require_membership(
        request.user, household_id, write=request.method == "POST"
    )
    if request.method == "GET":
        return Response(
            [
                _product(p)
                for p in Product.objects.filter(
                    household=member.household, is_active=True
                )
            ]
        )
    try:
        name = _text(request.data.get("name", ""), 120).strip()
        unit = _text(request.data.get("unit", ""), 24).strip()
        brand = _text(request.data.get("brand", ""), 120)
        category = _text(request.data.get("category", ""), 80)
    except ValueError:
        raise ValidationError({"detail": "Campo inválido ou acima do tamanho máximo."})
    if not name or not unit:
        raise ValidationError({"detail": "Nome e unidade são obrigatórios."})
    try:
        product = Product.objects.create(
            household=member.household,
            name=name,
            unit=unit,
            brand=brand,
            category=category,
        )
    except IntegrityError:
        raise ValidationError({"name": "Este produto já existe."})
    return Response(_product(product), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def alias(request, product_id):
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        raise NotFound()
    require_membership(request.user, product.household_id, write=True)
    try:
        alias_value = _text(request.data.get("alias", ""), 120).strip()
    except ValueError:
        raise ValidationError({"alias": "Alias inválido ou muito longo."})
    if not alias_value:
        raise ValidationError({"alias": "Informe um alias."})
    if len(alias_value) > 120:
        raise ValidationError({"alias": "Alias muito longo."})
    try:
        obj = ProductAlias.objects.create(product=product, alias=alias_value)
    except IntegrityError:
        raise ValidationError({"alias": "Este alias já existe para o produto."})
    return Response(
        {"id": obj.id, "product_id": product.id, "alias": obj.alias}, status=201
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def price_observation(request, household_id):
    member = require_membership(request.user, household_id, write=True)
    try:
        product = Product.objects.get(
            pk=request.data["product_id"], household=member.household
        )
        price = _positive_integer(request.data["price_minor"])
        quantity = _quantity(request.data["quantity"])
        unit = str(request.data["unit"])
        if unit != product.unit:
            raise ValueError
        store_name = _text(request.data.get("store_name", ""), 120)
    except (KeyError, ValueError, TypeError, InvalidOperation, Product.DoesNotExist):
        raise ValidationError(
            {"detail": "Produto, preço, quantidade ou unidade inválidos."}
        )
    obs = PriceObservation.objects.create(
        household=member.household,
        product=product,
        price_minor=price,
        quantity=quantity,
        unit=unit,
        store_name=store_name,
        source=PriceObservation.Source.MANUAL,
    )
    return Response({"id": obs.id, "source": obs.source}, status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lists(request, household_id):
    member = require_membership(
        request.user, household_id, write=request.method == "POST"
    )
    if request.method == "GET":
        return Response(
            [
                {
                    "id": x.id,
                    "name": x.name,
                    "status": x.status,
                    "items": [
                        {
                            "id": i.id,
                            "product_id": i.product_id,
                            "name": i.free_text_name or i.product.name,
                            "quantity": str(i.quantity),
                            "unit": i.unit,
                            "status": i.status,
                        }
                        for i in x.items.select_related("product")
                    ],
                }
                for x in ShoppingList.objects.filter(
                    household=member.household
                ).prefetch_related("items__product")
            ]
        )
    try:
        name = _text(request.data.get("name", ""), 120).strip()
    except ValueError:
        raise ValidationError({"name": "Nome inválido ou muito longo."})
    if not name:
        raise ValidationError({"name": "Informe o nome da lista."})
    if len(name) > 120:
        raise ValidationError({"name": "Nome muito longo."})
    obj = ShoppingList.objects.create(
        household=member.household, name=name, created_by=request.user
    )
    return Response({"id": obj.id, "name": obj.name, "status": obj.status}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def list_items(request, list_id):
    obj = ShoppingList.objects.filter(pk=list_id).first()
    if not obj:
        raise NotFound()
    require_membership(request.user, obj.household_id, write=True)
    try:
        quantity = _quantity(request.data["quantity"])
        product = (
            Product.objects.get(pk=request.data["product_id"], household=obj.household)
            if request.data.get("product_id")
            else None
        )
        free = _text(request.data.get("free_text_name", ""), 120).strip()
        raw_unit = request.data.get("unit") or (product.unit if product else "")
        unit = _text(raw_unit, 24)
        priority = request.data.get("priority", 0)
        if (
            not isinstance(priority, int)
            or isinstance(priority, bool)
            or not 0 <= priority <= 32767
        ):
            raise ValueError
        if (
            quantity <= 0
            or (product is None and not free)
            or (product is not None and bool(free))
            or (product and unit != product.unit)
        ):
            raise ValueError
    except (KeyError, ValueError, TypeError, InvalidOperation, Product.DoesNotExist):
        raise ValidationError({"detail": "Item, quantidade ou unidade inválidos."})
    item = ShoppingListItem.objects.create(
        shopping_list=obj,
        product=product,
        free_text_name=free,
        quantity=quantity,
        unit=unit,
        added_by=request.user,
        priority=priority,
    )
    return Response(
        {
            "id": item.id,
            "quantity": str(item.quantity),
            "unit": item.unit,
            "status": item.status,
        },
        status=201,
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def patch_list_item(request, item_id):
    item = (
        ShoppingListItem.objects.select_related("shopping_list")
        .filter(pk=item_id)
        .first()
    )
    if not item:
        raise NotFound()
    require_membership(request.user, item.shopping_list.household_id, write=True)
    if "status" in request.data:
        if request.data["status"] not in ShoppingListItem.Status.values:
            raise ValidationError({"status": "Status inválido."})
        item.status = request.data["status"]
    if "quantity" in request.data:
        try:
            item.quantity = _quantity(request.data["quantity"])
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({"quantity": "Quantidade inválida."})
    item.save()
    return Response(
        {"id": item.id, "status": item.status, "quantity": str(item.quantity)}
    )


def _purchase_result(purchase):
    return {
        "id": purchase.id,
        "total_amount_minor": purchase.total_amount_minor,
        "expense_id": purchase.expense_id,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def purchases(request, household_id):
    member = require_membership(request.user, household_id, write=True)
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 200:
        raise ValidationError(
            {"Idempotency-Key": "Informe uma chave de idempotência válida."}
        )
    canonical = json.dumps(
        request.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    try:
        rows = request.data["items"]
        if not isinstance(rows, list) or not rows:
            raise ValueError
        parsed, total = [], 0
        for row in rows:
            product = Product.objects.get(
                pk=row["product_id"], household=member.household, is_active=True
            )
            quantity = _quantity(row["quantity"])
            unit = str(row["unit"])
            price = _positive_integer(row["unit_price_minor"])
            if unit != product.unit:
                raise ValueError
            line = int(
                (Decimal(price) * quantity).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            if (
                "line_total_minor" in row
                and _positive_integer(row["line_total_minor"]) != line
            ):
                raise ValueError
            parsed.append(
                (product, quantity, unit, price, line, row.get("shopping_list_item_id"))
            )
            total += line
        purchased_at = date.fromisoformat(request.data["purchased_at"])
        if total <= 0:
            raise ValueError
        list_obj = None
        if request.data.get("shopping_list_id"):
            list_obj = ShoppingList.objects.get(
                pk=request.data["shopping_list_id"], household=member.household
            )
        store_name = _text(request.data.get("store_name", ""), 120)
    except (
        KeyError,
        ValueError,
        TypeError,
        InvalidOperation,
        Product.DoesNotExist,
        ShoppingList.DoesNotExist,
    ):
        raise ValidationError(
            {"detail": "Linhas, quantidades, totais, data ou lista inválidos."}
        )
    with transaction.atomic():
        from apps.households.models import Household

        Household.objects.select_for_update().get(pk=member.household_id)
        existing = Purchase.objects.filter(
            household=member.household, idempotency_key=key
        ).first()
        if existing:
            if existing.payload_hash != digest:
                raise Conflict()
            return Response(_purchase_result(existing), status=200)
        category, _ = ExpenseCategory.objects.get_or_create(
            household=member.household, name="Compras", defaults={"kind": "general"}
        )
        expense = Expense.objects.create(
            household=member.household,
            description=f"Compra - {store_name or 'Mercado'}",
            category=category,
            amount_minor=total,
            currency=member.household.currency,
            incurred_on=purchased_at,
            created_by=request.user,
        )
        active = list(
            Membership.objects.filter(
                household=member.household, status="active"
            ).order_by("id")
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
            household=member.household,
            expense=expense,
            payer=member,
            amount_minor=total,
            notes="Pagamento da compra",
        )
        purchase = Purchase.objects.create(
            household=member.household,
            purchased_at=purchased_at,
            store_name=store_name,
            total_amount_minor=total,
            created_by=request.user,
            buyer=member,
            shopping_list=list_obj,
            idempotency_key=key,
            payload_hash=digest,
            expense=expense,
        )
        for product, quantity, unit, price, line, list_item_id in parsed:
            list_item = None
            if list_item_id is not None:
                if not list_obj:
                    raise ValidationError(
                        {"detail": "Vínculo exige uma lista de compras."}
                    )
                try:
                    list_item = ShoppingListItem.objects.select_for_update().get(
                        pk=list_item_id,
                        shopping_list=list_obj,
                        product=product,
                        status=ShoppingListItem.Status.NEEDED,
                    )
                except ShoppingListItem.DoesNotExist:
                    raise Conflict(
                        "O item da lista não está mais disponível para compra."
                    )
            item = PurchaseItem.objects.create(
                purchase=purchase,
                product=product,
                quantity=quantity,
                unit=unit,
                unit_price_minor=price,
                line_total_minor=line,
                shopping_list_item=list_item,
            )
            if list_item:
                list_item.status = ShoppingListItem.Status.PURCHASED
                list_item.save(update_fields=["status"])
            inventory, _ = InventoryItem.objects.get_or_create(
                household=member.household, product=product, unit=unit
            )
            inventory = InventoryItem.objects.select_for_update().get(pk=inventory.pk)
            InventoryItem.objects.filter(pk=inventory.pk).update(
                quantity=F("quantity") + quantity
            )
            InventoryEvent.objects.create(
                item=inventory,
                event_type=InventoryEvent.Type.PURCHASE,
                quantity_delta=quantity,
                created_by=request.user,
                source_purchase_item=item,
            )
            PriceObservation.objects.create(
                household=member.household,
                product=product,
                store_name=purchase.store_name,
                price_minor=price,
                quantity=quantity,
                unit=unit,
                source=PriceObservation.Source.PURCHASE,
            )
        AuditEvent.objects.create(
            household=member.household,
            actor=request.user,
            action="purchase.confirmed",
            entity_type="purchase",
            entity_id=str(purchase.id),
            metadata={"total_amount_minor": total, "item_count": len(parsed)},
        )
    return Response(_purchase_result(purchase), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def price_history(request, household_id, product_id):
    member = require_membership(request.user, household_id)
    if not Product.objects.filter(pk=product_id, household=member.household).exists():
        raise NotFound()
    return Response(
        list(
            PriceObservation.objects.filter(
                household=member.household, product_id=product_id
            )
            .order_by("-observed_at")
            .values(
                "id",
                "store_name",
                "price_minor",
                "quantity",
                "unit",
                "source",
                "observed_at",
            )
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inventory(request, household_id):
    member = require_membership(request.user, household_id)
    return Response(
        [
            {
                "product_id": i.product_id,
                "name": i.product.name,
                "quantity": str(i.quantity),
                "unit": i.unit,
            }
            for i in InventoryItem.objects.filter(household=member.household)
            .select_related("product")
            .order_by("product__name")
        ]
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def inventory_event(request, item_id):
    initial = InventoryItem.objects.filter(pk=item_id).first()
    if not initial:
        raise NotFound()
    require_membership(request.user, initial.household_id, write=True)
    try:
        raw_delta = request.data["quantity_delta"]
        if isinstance(raw_delta, (bool, float)) or not isinstance(
            raw_delta, (int, Decimal, str)
        ):
            raise ValueError
        delta = Decimal(raw_delta)
        kind = request.data["event_type"]
        if not delta.is_finite() or delta == 0 or delta.as_tuple().exponent < -4:
            raise ValueError
        if (
            kind not in InventoryEvent.Type.values
            or kind == InventoryEvent.Type.PURCHASE
        ):
            raise ValueError
        if (
            kind in (InventoryEvent.Type.CONSUMPTION, InventoryEvent.Type.LOSS)
            and delta >= 0
        ):
            raise ValueError
        if (
            kind in (InventoryEvent.Type.ADJUSTMENT, InventoryEvent.Type.CORRECTION)
            and not str(request.data.get("notes", "")).strip()
        ):
            raise ValueError
        notes = _text(request.data.get("notes", ""), 240)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise ValidationError(
            {
                "detail": "Movimento inválido; ajuste exige justificativa e saldo não pode ser negativo."
            }
        )
    with transaction.atomic():
        item = InventoryItem.objects.select_for_update().get(pk=item_id)
        if item.quantity + delta < 0:
            raise ValidationError({"detail": "Saldo não pode ser negativo."})
        item.quantity += delta
        item.save(update_fields=["quantity"])
        event = InventoryEvent.objects.create(
            item=item,
            event_type=kind,
            quantity_delta=delta,
            created_by=request.user,
            notes=notes,
        )
    return Response({"id": event.id, "quantity": str(item.quantity)}, status=201)
