from django.urls import path

from apps.shopping import api

urlpatterns = [
    path("households/<uuid:household_id>/products", api.products),
    path("products/<int:product_id>/aliases", api.alias),
    path("households/<uuid:household_id>/price-observations", api.price_observation),
    path(
        "households/<uuid:household_id>/products/<int:product_id>/price-history",
        api.price_history,
    ),
    path("households/<uuid:household_id>/shopping-lists", api.lists),
    path("shopping-lists/<int:list_id>/items", api.list_items),
    path("shopping-items/<int:item_id>", api.patch_list_item),
    path("households/<uuid:household_id>/purchases", api.purchases),
    path("households/<uuid:household_id>/inventory", api.inventory),
    path("inventory/<int:item_id>/events", api.inventory_event),
]
