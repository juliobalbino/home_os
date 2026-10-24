from django.urls import path

from apps.chores import api

urlpatterns = [
    path("households/<uuid:household_id>/chores", api.chores),
    path("chores/<int:chore_id>", api.chore_detail),
    path("chores/<int:chore_id>/generate-occurrences", api.generate),
    path("households/<uuid:household_id>/chore-occurrences", api.occurrences),
    path("chore-occurrences/<int:occurrence_id>/complete", api.occurrence_action),
]
