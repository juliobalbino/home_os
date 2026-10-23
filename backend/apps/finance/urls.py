from django.urls import path

from apps.finance import api

urlpatterns = [
    path("finance/categories", api.categories),
    path("households/<uuid:household_id>/expenses", api.expenses),
    path("expenses/<int:expense_id>", api.expense_detail),
    path("expenses/<int:expense_id>/splits", api.expense_detail),
    path("expenses/<int:expense_id>/payments", api.payments),
    path("households/<uuid:household_id>/budgets/<str:period>", api.budgets),
    path("households/<uuid:household_id>/financial-summary", api.financial_summary),
    path("households/<uuid:household_id>/settlements", api.financial_settlements),
]
