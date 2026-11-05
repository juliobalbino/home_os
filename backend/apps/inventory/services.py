"""Validated inventory balance and event mutations."""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InventoryEvent, InventoryItem
from apps.shopping.services import quantity, text
from apps.shopping.services import audit


@transaction.atomic
def record_event(*, item, actor, event_type, quantity_delta, notes=""):
    if (
        event_type not in InventoryEvent.Type.values
        or event_type == InventoryEvent.Type.PURCHASE
    ):
        raise ValidationError({"event_type": "Tipo de movimento inválido."})
    try:
        delta = quantity(quantity_delta, positive=False)
        notes = text(notes, 240, "notes")
    except ValidationError:
        raise
    if (
        event_type in (InventoryEvent.Type.CONSUMPTION, InventoryEvent.Type.LOSS)
        and delta >= 0
    ):
        raise ValidationError(
            {"quantity_delta": "Consumo e perda devem reduzir o saldo."}
        )
    if (
        event_type in (InventoryEvent.Type.ADJUSTMENT, InventoryEvent.Type.CORRECTION)
        and not notes.strip()
    ):
        raise ValidationError({"notes": "Ajuste e correção exigem justificativa."})
    item = InventoryItem.objects.select_for_update().get(pk=item.pk)
    if item.quantity + delta < 0:
        raise ValidationError({"quantity_delta": "Saldo não pode ser negativo."})
    item.quantity += delta
    item.save(update_fields=["quantity"])
    event = InventoryEvent.objects.create(
        item=item,
        event_type=event_type,
        quantity_delta=delta,
        created_by=actor,
        notes=notes,
    )
    audit(
        item.household,
        actor,
        "inventory.event_recorded",
        "inventory_event",
        event.id,
        {"event_type": event_type},
    )
    return event, item


def apply_purchase_stock(*, household, product, quantity_delta, actor, purchase_item):
    inventory, _ = InventoryItem.objects.get_or_create(
        household=household, product=product, unit=product.unit
    )
    inventory = InventoryItem.objects.select_for_update().get(pk=inventory.pk)
    inventory.quantity += quantity_delta
    inventory.save(update_fields=["quantity"])
    return InventoryEvent.objects.create(
        item=inventory,
        event_type=InventoryEvent.Type.PURCHASE,
        quantity_delta=quantity_delta,
        created_by=actor,
        source_purchase_item=purchase_item,
    )
