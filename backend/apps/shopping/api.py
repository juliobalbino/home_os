import json
from decimal import Decimal, InvalidOperation
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.households.permissions import require_membership
from apps.inventory.models import InventoryEvent, InventoryItem
from apps.shopping.models import (
    PriceObservation,
    Product,
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
    from apps.shopping.services import create_product

    product = create_product(
        household=member.household,
        actor=request.user,
        name=request.data.get("name", ""),
        unit=request.data.get("unit", ""),
        brand=request.data.get("brand", ""),
        category=request.data.get("category", ""),
    )
    return Response(_product(product), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def alias(request, product_id):
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        raise NotFound()
    require_membership(request.user, product.household_id, write=True)
    from apps.shopping.services import add_alias

    obj = add_alias(
        product=product, actor=request.user, alias=request.data.get("alias", "")
    )
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
    from apps.shopping.services import record_price

    obs = record_price(
        household=member.household,
        product=product,
        actor=request.user,
        price_minor=price,
        quantity_value=quantity,
        unit=unit,
        store_name=store_name,
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
    from apps.shopping.services import add_list_item

    item = add_list_item(
        shopping_list=obj,
        actor=request.user,
        product=product,
        free_text_name=free,
        quantity_value=quantity,
        unit=unit,
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
    payload = {}
    if "status" in request.data:
        if request.data["status"] not in ShoppingListItem.Status.values:
            raise ValidationError({"status": "Status inválido."})
        payload["status"] = request.data["status"]
    if "quantity" in request.data:
        try:
            payload["quantity"] = _quantity(request.data["quantity"])
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({"quantity": "Quantidade inválida."})
    from apps.shopping.services import update_list_item

    item = update_list_item(item=item, actor=request.user, payload=payload)
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
    from hashlib import sha256

    canonical = json.dumps(
        request.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = sha256(canonical.encode()).hexdigest()
    from apps.shopping.services import create_purchase

    try:
        purchase, created = create_purchase(
            household=member.household,
            actor=request.user,
            buyer=member,
            payload=request.data,
            idempotency_key=key,
            payload_hash=digest,
        )
    except ShoppingListItem.DoesNotExist:
        raise Conflict("O item da lista não está mais disponível para compra.")
    except ValidationError as exc:
        if "reutilizada" in str(exc):
            raise Conflict()
        raise
    return Response(_purchase_result(purchase), status=201 if created else 200)


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
    from apps.inventory.services import record_event

    event, item = record_event(
        item=initial,
        actor=request.user,
        event_type=kind,
        quantity_delta=delta,
        notes=notes,
    )
    return Response({"id": event.id, "quantity": str(item.quantity)}, status=201)
