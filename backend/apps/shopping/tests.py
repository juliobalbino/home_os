from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.households.models import Household, Membership
from apps.finance.models import Expense
from apps.inventory.models import InventoryEvent
from apps.shopping.models import Purchase, ShoppingListItem
from apps.audit.models import AuditEvent


class PurchaseContractTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="buyer@example.com", password="abcdef", name="Buyer"
        )
        self.house = Household.objects.create(name="Casa", created_by=self.user)
        self.member = Membership.objects.create(
            household=self.house, user=self.user, role="owner"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_purchase_atomically_creates_expense_payment_and_stock_once(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Arroz", "unit": "kg"},
            format="json",
        ).data
        payload = {
            "purchased_at": date.today().isoformat(),
            "store_name": "Mercado",
            "items": [
                {
                    "product_id": product["id"],
                    "quantity": "2.00",
                    "unit": "kg",
                    "unit_price_minor": 750,
                    "line_total_minor": 1500,
                }
            ],
        }
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/purchases",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="purchase-1",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_amount_minor"], 1500)
        self.assertEqual(
            self.client.get(f"/api/v1/households/{self.house.pk}/inventory").data[0][
                "quantity"
            ],
            "2.0000",
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/households/{self.house.pk}/financial-summary"
            ).data["spent_total"],
            1500,
        )
        repeated = self.client.post(
            f"/api/v1/households/{self.house.pk}/purchases",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="purchase-1",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data["id"], response.data["id"])
        from apps.finance.models import Expense, Payment

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_reusing_key_with_different_payload_conflicts(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Leite", "unit": "un"},
            format="json",
        ).data
        endpoint = f"/api/v1/households/{self.house.pk}/purchases"
        payload = {
            "purchased_at": date.today().isoformat(),
            "items": [
                {
                    "product_id": product["id"],
                    "quantity": "1",
                    "unit": "un",
                    "unit_price_minor": 500,
                    "line_total_minor": 500,
                }
            ],
        }
        self.assertEqual(
            self.client.post(
                endpoint, payload, format="json", HTTP_IDEMPOTENCY_KEY="same"
            ).status_code,
            201,
        )
        payload["store_name"] = "Outra loja"
        self.assertEqual(
            self.client.post(
                endpoint, payload, format="json", HTTP_IDEMPOTENCY_KEY="same"
            ).status_code,
            409,
        )
        self.assertEqual(Purchase.objects.count(), 1)

    def test_invalid_line_total_leaves_no_partial_financial_or_stock_records(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Feijão", "unit": "kg"},
            format="json",
        ).data
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/purchases",
            {
                "purchased_at": date.today().isoformat(),
                "items": [
                    {
                        "product_id": product["id"],
                        "quantity": "2",
                        "unit": "kg",
                        "unit_price_minor": 500,
                        "line_total_minor": 999,
                    }
                ],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="invalid",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(InventoryEvent.objects.count(), 0)

    def test_free_text_list_item_preserves_exact_decimal_quantity(self):
        listing = self.client.post(
            f"/api/v1/households/{self.house.pk}/shopping-lists",
            {"name": "Feira"},
            format="json",
        ).data
        response = self.client.post(
            f"/api/v1/shopping-lists/{listing['id']}/items",
            {"free_text_name": "Manjericão", "quantity": "0.125", "unit": "maço"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ShoppingListItem.objects.get().quantity, Decimal("0.125"))

    def test_purchase_computes_each_line_with_half_up_and_accepts_multiple_rows(self):
        products = [
            self.client.post(
                f"/api/v1/households/{self.house.pk}/products",
                {"name": name, "unit": "un"},
                format="json",
            ).data
            for name in ("A", "B")
        ]
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/purchases",
            {
                "purchased_at": date.today().isoformat(),
                "items": [
                    {
                        "product_id": products[0]["id"],
                        "quantity": "0.5",
                        "unit": "un",
                        "unit_price_minor": 1,
                    },
                    {
                        "product_id": products[1]["id"],
                        "quantity": "1.5",
                        "unit": "un",
                        "unit_price_minor": 1,
                    },
                ],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="half-up-multi",
        )
        self.assertEqual(response.status_code, 201)
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.total_amount_minor, 3)
        self.assertEqual(
            list(purchase.items.values_list("line_total_minor", flat=True)), [1, 2]
        )

    def test_duplicate_product_and_alias_return_conflict_not_server_error(self):
        endpoint = f"/api/v1/households/{self.house.pk}/products"
        self.assertEqual(
            self.client.post(
                endpoint, {"name": "Tea", "unit": "un"}, format="json"
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                endpoint, {"name": "Tea", "unit": "un"}, format="json"
            ).status_code,
            400,
        )

    def test_manual_purchase_event_and_invalid_numeric_inputs_are_rejected(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Oil", "unit": "un"},
            format="json",
        ).data
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/price-observations",
            {
                "product_id": product["id"],
                "price_minor": 1.5,
                "quantity": "1",
                "unit": "un",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_purchase_linked_list_item_retry_with_new_key_conflicts_atomically(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Café", "unit": "kg"},
            format="json",
        ).data
        listing = self.client.post(
            f"/api/v1/households/{self.house.pk}/shopping-lists",
            {"name": "Mercado"},
            format="json",
        ).data
        item = self.client.post(
            f"/api/v1/shopping-lists/{listing['id']}/items",
            {"product_id": product["id"], "quantity": "1", "unit": "kg"},
            format="json",
        ).data
        endpoint = f"/api/v1/households/{self.house.pk}/purchases"
        payload = {
            "purchased_at": date.today().isoformat(),
            "shopping_list_id": listing["id"],
            "items": [
                {
                    "product_id": product["id"],
                    "quantity": "1",
                    "unit": "kg",
                    "unit_price_minor": 500,
                    "shopping_list_item_id": item["id"],
                }
            ],
        }
        first = self.client.post(
            endpoint, payload, format="json", HTTP_IDEMPOTENCY_KEY="linked-1"
        )
        self.assertEqual(first.status_code, 201)
        retry = self.client.post(
            endpoint, payload, format="json", HTTP_IDEMPOTENCY_KEY="linked-2"
        )
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(Purchase.objects.count(), 1)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(InventoryEvent.objects.count(), 1)
        self.assertEqual(
            ShoppingListItem.objects.get(pk=item["id"]).status, "purchased"
        )
        from apps.finance.models import Payment
        from apps.inventory.models import InventoryItem

        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(
            InventoryItem.objects.get(product_id=product["id"]).quantity,
            Decimal("1.0000"),
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="purchase.confirmed").count(), 1
        )

    def test_purchase_creates_minimized_confirmation_audit_event(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Sal", "unit": "un"},
            format="json",
        ).data
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/purchases",
            {
                "purchased_at": date.today().isoformat(),
                "store_name": "private store",
                "notes": "secret",
                "items": [
                    {
                        "product_id": product["id"],
                        "quantity": "1",
                        "unit": "un",
                        "unit_price_minor": 10,
                    }
                ],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="audit-purchase",
        )
        self.assertEqual(response.status_code, 201)
        event = AuditEvent.objects.get(action="purchase.confirmed")
        self.assertEqual(event.entity_type, "purchase")
        self.assertEqual(event.entity_id, str(response.data["id"]))
        self.assertEqual(event.metadata, {"total_amount_minor": 10, "item_count": 1})

    def test_inventory_event_rejects_float_bool_wrong_types_and_long_notes(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Água", "unit": "l"},
            format="json",
        ).data
        from apps.inventory.models import InventoryItem

        inventory = InventoryItem.objects.create(
            household=self.house,
            product_id=product["id"],
            unit="l",
            quantity=Decimal("2"),
        )
        endpoint = f"/api/v1/inventory/{inventory.pk}/events"
        for value in (1.25, True, [], None):
            response = self.client.post(
                endpoint,
                {
                    "quantity_delta": value,
                    "event_type": "adjustment",
                    "notes": "ajuste",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        for value, kind in (
            ("1.12345", "adjustment"),
            ("NaN", "adjustment"),
            ("0", "adjustment"),
            ("1", "consumption"),
        ):
            response = self.client.post(
                endpoint,
                {"quantity_delta": value, "event_type": kind, "notes": "ajuste"},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        response = self.client.post(
            endpoint,
            {"quantity_delta": "1", "event_type": "adjustment", "notes": "x" * 241},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(InventoryEvent.objects.count(), 0)

    def test_shopping_rejects_max_length_and_invalid_type_inputs(self):
        endpoint = f"/api/v1/households/{self.house.pk}/products"
        for payload in (
            {"name": "x", "unit": "un", "brand": "b" * 121},
            {"name": "x", "unit": "u" * 25},
            {"name": "x" * 121, "unit": "un"},
            {"name": 42, "unit": "un"},
        ):
            self.assertEqual(
                self.client.post(endpoint, payload, format="json").status_code, 400
            )
        product = self.client.post(
            endpoint, {"name": "Produto", "unit": "un"}, format="json"
        ).data
        self.assertEqual(
            self.client.post(
                f"/api/v1/products/{product['id']}/aliases",
                {"alias": "a" * 121},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/households/{self.house.pk}/shopping-lists",
                {"name": "n" * 121},
                format="json",
            ).status_code,
            400,
        )
        listing = self.client.post(
            f"/api/v1/households/{self.house.pk}/shopping-lists",
            {"name": "Lista"},
            format="json",
        ).data
        self.assertEqual(
            self.client.post(
                f"/api/v1/shopping-lists/{listing['id']}/items",
                {"free_text_name": "f" * 121, "quantity": "1", "unit": "un"},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/shopping-lists/{listing['id']}/items",
                {"free_text_name": "Livre", "quantity": "1", "unit": "u" * 25},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/shopping-lists/{listing['id']}/items",
                {
                    "free_text_name": "Livre",
                    "quantity": "1",
                    "unit": "un",
                    "priority": -1,
                },
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/shopping-lists/{listing['id']}/items",
                {
                    "free_text_name": "Livre",
                    "quantity": "1",
                    "unit": "un",
                    "priority": "high",
                },
                format="json",
            ).status_code,
            400,
        )

    def test_manual_price_observation_rejects_invalid_store_name(self):
        product = self.client.post(
            f"/api/v1/households/{self.house.pk}/products",
            {"name": "Farinha", "unit": "kg"},
            format="json",
        ).data
        response = self.client.post(
            f"/api/v1/households/{self.house.pk}/price-observations",
            {
                "product_id": product["id"],
                "price_minor": 100,
                "quantity": "1",
                "unit": "kg",
                "store_name": "s" * 121,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
