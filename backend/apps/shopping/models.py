from django.conf import settings
from django.db import models

from apps.households.models import Household


class Product(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    brand = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=80, blank=True)
    unit = models.CharField(max_length=24)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "name", "brand"), name="shopping_unique_product"
            )
        ]
        ordering = ("name", "id")


class ProductAlias(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="aliases"
    )
    alias = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("product", "alias"), name="shopping_unique_alias"
            )
        ]


class PriceObservation(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        PURCHASE = "purchase", "Purchase"

    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="price_observations"
    )
    store_name = models.CharField(max_length=120, blank=True)
    price_minor = models.PositiveBigIntegerField()
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=24)
    source = models.CharField(max_length=12, choices=Source.choices)
    observed_at = models.DateTimeField(auto_now_add=True)


class ShoppingList(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        COMPLETED = "completed", "Concluída"
        ARCHIVED = "archived", "Arquivada"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="shopping_lists"
    )
    name = models.CharField(max_length=120)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class ShoppingListItem(models.Model):
    class Status(models.TextChoices):
        NEEDED = "needed", "Necessário"
        PURCHASED = "purchased", "Comprado"
        SKIPPED = "skipped", "Ignorado"

    shopping_list = models.ForeignKey(
        ShoppingList, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.PROTECT
    )
    free_text_name = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=24)
    priority = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEEDED
    )
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(product__isnull=False, free_text_name="")
                    | (models.Q(product__isnull=True) & ~models.Q(free_text_name=""))
                ),
                name="shopping_item_product_xor_free_text",
            )
        ]


class Purchase(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="purchases"
    )
    purchased_at = models.DateField()
    store_name = models.CharField(max_length=120, blank=True)
    total_amount_minor = models.PositiveBigIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    buyer = models.ForeignKey("households.Membership", on_delete=models.PROTECT)
    shopping_list = models.ForeignKey(
        ShoppingList, null=True, blank=True, on_delete=models.PROTECT
    )
    idempotency_key = models.CharField(max_length=200)
    payload_hash = models.CharField(max_length=64)
    expense = models.OneToOneField(
        "finance.Expense", on_delete=models.PROTECT, related_name="purchase"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "idempotency_key"),
                name="shopping_purchase_idempotency",
            )
        ]


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=24)
    unit_price_minor = models.PositiveBigIntegerField()
    line_total_minor = models.PositiveBigIntegerField()
    shopping_list_item = models.ForeignKey(
        ShoppingListItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_items",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("shopping_list_item",),
                condition=models.Q(shopping_list_item__isnull=False),
                name="shopping_list_item_single_purchase",
            )
        ]
