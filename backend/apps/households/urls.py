from django.urls import path

from apps.households import api

urlpatterns = [
    path("households", api.households),
    path("households/<uuid:household_id>", api.household_detail),
    path("households/<uuid:household_id>/members", api.members),
    path("households/<uuid:household_id>/invitations", api.invitations),
    path("invitations/<str:token>/accept", api.accept_invitation),
]
