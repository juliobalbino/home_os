from django.conf import settings
from django.db import models

from apps.households.models import Household


class InventoryItem(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    product = models.ForeignKey("shopping.Product", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    unit = models.CharField(max_length=24)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "product", "unit"), name="inventory_unique_balance"
            )
        ]


class InventoryEvent(models.Model):
    class Type(models.TextChoices):
        PURCHASE = "purchase", "Compra"
        CONSUMPTION = "consumption", "Consumo"
        ADJUSTMENT = "adjustment", "Ajuste"
        LOSS = "loss", "Perda"
        CORRECTION = "correction", "Correção"

    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="events"
    )
    event_type = models.CharField(max_length=12, choices=Type.choices)
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=4)
    occurred_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_purchase_item = models.OneToOneField(
        "shopping.PurchaseItem", null=True, blank=True, on_delete=models.PROTECT
    )
    notes = models.CharField(max_length=240, blank=True)
